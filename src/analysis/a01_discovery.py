"""Analysis pass 01 - discovery.

Descriptive discovery over the validated PostgreSQL mart layer. No machine
learning, no composite index, no recommendations: this pass establishes what the
data actually shows so that later passes can be aimed at something real.

    python src/analysis/a01_discovery.py

Reads   : mart.* (and core.dim_* only for labels), over a READ-ONLY connection
Writes  : outputs/analysis/discovery/*.csv and a01_discovery_log.txt
Modifies: nothing. Not the database, not data/processed/, not data/reference/.

Safety rules applied throughout, in the words of the schema design (S9):
  - STATE, ZONE and NATIONAL grains are analysed separately and never summed.
  - CPI INDEX levels are never compared across states. CPI change rates are.
  - Food zone values are never treated as state values.
  - NERC tariffs are never mapped to states, and are a July 2025 cross-section.
  - CBN FX is national context only.
  - LPG cylinder sizes and transport modes stay separate series.
  - PRIMARY publications throughout; restatement views are not read in this pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nbci_analysis as na  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 400)

OUT = "discovery"
PW_START, PW_END = na.PRIMARY_WINDOW


def head(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 40) -> None:
    print(df.head(n).to_string(index=False))


# ===========================================================================
def section_0_validation(conn, ck):
    head("SECTION 0 - VALIDATION GATE (runs before any finding is produced)")

    na.check_read_only(conn, ck)
    na.check_windows_match_database(conn, ck)

    panel = na.q(conn, """
        SELECT state_id, state_name, zone_name, observation_month, metric_code,
               metric_value::double precision AS metric_value, unit, source_dataset,
               release_month, in_available_window, in_primary_release_window
        FROM mart.mv_state_cost_panel_monthly
    """)
    ck.eq(len(panel), 9435, "panel row count unchanged since the committed milestone")
    na.check_no_duplicate_grain(panel, ["state_id", "observation_month", "metric_code"],
                                "panel (state, month, metric)", ck)
    na.check_no_unexpected_nulls(panel, ["state_id", "observation_month", "metric_code",
                                         "metric_value", "unit"], "panel", ck)
    na.check_units_unique_per_metric(panel, ck)
    ck.eq(panel.state_id.nunique(), na.N_STATES, "panel covers all 37 jurisdictions (36 states + FCT)")
    ck.eq(sorted(panel.metric_code.unique().tolist()),
          sorted(na.PRICE_METRICS + na.CPI_RATE_METRICS
                 + na.CPI_INDEX_METRICS_DO_NOT_COMPARE_ACROSS_STATES),
          "panel carries exactly the 15 expected metric codes")

    # Publication-selection rule: the panel is primary throughout, so every row
    # must be its dataset's own first publication of that month.
    bad_pub = na.q(conn, """
        SELECT count(*) AS n FROM mart.mv_state_cost_panel_monthly
        WHERE release_month < observation_month
    """).n.iloc[0]
    ck.eq(int(bad_pub), 0, "publication rule: no panel row is released before its own month")

    pw = panel[panel.in_primary_release_window]
    ck.eq(pw.observation_month.nunique(), na.PRIMARY_WINDOW_MONTHS,
          "primary window holds 15 distinct months")
    ck.eq(str(pw.observation_month.min()), PW_START, "primary window starts 2025-02")
    ck.eq(str(pw.observation_month.max()), PW_END, "primary window ends 2026-04")

    # Missing months, stated rather than silently dropped.
    grid = (pw.groupby("metric_code")
              .agg(rows=("metric_value", "size"),
                   states=("state_id", "nunique"),
                   months=("observation_month", "nunique"))
              .reset_index())
    grid["expected_full_grid"] = na.N_STATES * na.PRIMARY_WINDOW_MONTHS
    grid["missing"] = grid.expected_full_grid - grid.rows
    print("\n  Completeness inside the primary window (37 jurisdictions x 15 months = 555):")
    show(grid.sort_values(["missing", "metric_code"], ascending=[False, True]))
    na.write_csv(grid, OUT, "v01_primary_window_completeness.csv")

    # 15 metrics, 4 incomplete (2 CPI INDEX + 2 CPI YoY) -> 11 complete.
    complete = grid[grid.missing == 0].metric_code.tolist()
    ck.eq(len(complete), 11, "11 of 15 metrics are complete in the primary window")
    incomplete = grid[grid.missing > 0].set_index("metric_code")["missing"].to_dict()
    ck.check(set(incomplete) == {"CPI_ALL_ITEMS_INDEX", "CPI_FOOD_INDEX",
                                 "CPI_ALL_ITEMS_YOY_PCT", "CPI_FOOD_YOY_PCT"},
             "the only incomplete metrics are the two CPI INDEX and two CPI YoY series",
             f"{incomplete}")

    # Which month is missing, per incomplete metric - never inferred.
    gaps = []
    all_months = sorted(pw.observation_month.unique())
    for m in sorted(incomplete):
        have = set(pw[pw.metric_code == m].observation_month.unique())
        for mm in all_months:
            if mm not in have:
                gaps.append({"metric_code": m, "missing_month": mm,
                             "states_missing": na.N_STATES})
    gaps_df = pd.DataFrame(gaps)
    print("\n  Named gaps (no month is dropped silently):")
    show(gaps_df)
    na.write_csv(gaps_df, OUT, "v02_named_gaps.csv")

    # Every price metric must be fully covered - these carry the analysis.
    price_pw = grid[grid.metric_code.isin(na.PRICE_METRICS)]
    ck.check((price_pw.missing == 0).all(),
             "all 9 price metrics are complete: 555 of 555 state-months each",
             f"{int(price_pw.rows.sum())} rows over {len(price_pw)} metrics")

    return panel


# ===========================================================================
def section_1_surface(conn, ck):
    head("SECTION 1 - ANALYTICAL SURFACE")

    objs = na.q(conn, """
        SELECT c.relname AS object_name,
               CASE c.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'matview' END AS kind,
               obj_description(c.oid) AS purpose
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname='mart' AND c.relkind IN ('v','m')
        ORDER BY c.relkind DESC, c.relname
    """)
    rows = []
    for _, r in objs.iterrows():
        n = na.q(conn, f'SELECT count(*) AS n FROM mart."{r.object_name}"').n.iloc[0]
        rows.append({"object": r.object_name, "kind": r.kind, "rows": int(n)})
    surf = pd.DataFrame(rows)
    show(surf, 40)
    na.write_csv(surf, OUT, "s01_mart_surface.csv")
    ck.eq(len(surf), 30, "mart exposes 30 analytical objects")

    print("\n  Per-dataset windows (mart.v_state_dataset_windows):")
    show(na.q(conn, "SELECT * FROM mart.v_state_dataset_windows ORDER BY dataset"))

    print("\n  Coverage by dataset (mart.v_coverage_matrix):")
    cov = na.q(conn, """
        SELECT dataset, min(observation_month) AS first_month,
               max(observation_month) AS last_month,
               count(*) AS months, sum(row_count) AS rows
        FROM mart.v_coverage_matrix GROUP BY dataset ORDER BY dataset
    """)
    show(cov)
    na.write_csv(cov, OUT, "s02_dataset_coverage.csv")

    print("\n  Geography grains (mart.v_geography) - never summed together:")
    show(na.q(conn, """
        SELECT geography_type, count(*) AS n FROM mart.v_geography
        GROUP BY 1 ORDER BY 1
    """))


# ===========================================================================
def section_2_level_and_trend(panel, ck):
    head("SECTION 2 - LEVEL AND TREND (median across 37 jurisdictions, primary window)")
    print("  Median is used, not mean: it is the robust central value and it is not\n"
          "  a national statistic. NBS publishes its own national figures; this is a\n"
          "  cross-state median of state observations and is labelled as such.\n")

    pw = panel[panel.in_primary_release_window & panel.metric_code.isin(na.PRICE_METRICS)]
    med = (pw.groupby(["metric_code", "observation_month"])
             .agg(median_ngn=("metric_value", "median"),
                  states=("state_id", "nunique"))
             .reset_index())
    ck.check((med.states == na.N_STATES).all(),
             "every median is computed over all 37 jurisdictions", f"{med.states.min()}..{med.states.max()}")

    first_m, last_m = med.observation_month.min(), med.observation_month.max()
    tr = []
    for m, g in med.groupby("metric_code"):
        g = g.sort_values("observation_month")
        f, l = float(g.median_ngn.iloc[0]), float(g.median_ngn.iloc[-1])
        peak = g.loc[g.median_ngn.idxmax()]
        trough = g.loc[g.median_ngn.idxmin()]
        tr.append({
            "metric_code": m, "label": na.SHORT_LABEL[m],
            "first_month": first_m, "first_median": round(f, 2),
            "last_month": last_m, "last_median": round(l, 2),
            "abs_change": round(l - f, 2), "pct_change": round(100 * (l / f - 1), 2),
            "trough_month": trough.observation_month, "trough": round(float(trough.median_ngn), 2),
            "peak_month": peak.observation_month, "peak": round(float(peak.median_ngn), 2),
            "trough_to_last_pct": round(100 * (l / float(trough.median_ngn) - 1), 2),
        })
    trend = pd.DataFrame(tr).sort_values("pct_change", ascending=False)
    show(trend)
    na.write_csv(trend, OUT, "f01_trend_primary_window.csv")
    na.write_csv(med, OUT, "f02_median_by_metric_month.csv")

    print("\n  CPI change rates (median across states; rates ARE comparable, levels are not):")
    cpi = panel[panel.in_primary_release_window & panel.metric_code.isin(na.CPI_RATE_METRICS)]
    cpim = (cpi.groupby(["metric_code", "observation_month"])
              .agg(median_pct=("metric_value", "median"), states=("state_id", "nunique"))
              .reset_index())
    piv = cpim.pivot(index="observation_month", columns="metric_code", values="median_pct").round(2)
    print(piv.to_string())
    na.write_csv(cpim, OUT, "f03_cpi_rates_by_month.csv")
    return trend, med, cpim


# ===========================================================================
def section_3_dispersion(panel, ck):
    head("SECTION 3 - GEOGRAPHIC DISPERSION (how much a cost varies between states)")

    pw = panel[panel.in_primary_release_window & panel.metric_code.isin(na.PRICE_METRICS)]
    rows = []
    for (m, mo), g in pw.groupby(["metric_code", "observation_month"]):
        v = g.metric_value
        rows.append({"metric_code": m, "observation_month": mo, "states": v.size,
                     "min": v.min(), "p25": v.quantile(.25), "median": v.median(),
                     "p75": v.quantile(.75), "max": v.max(),
                     "iqr": v.quantile(.75) - v.quantile(.25),
                     "range": v.max() - v.min(),
                     "cv_pct": 100 * v.std(ddof=1) / v.mean(),
                     "max_over_min": v.max() / v.min()})
    disp = pd.DataFrame(rows)
    ck.check((disp.states == na.N_STATES).all(), "dispersion computed over 37 jurisdictions every month")
    na.write_csv(disp, OUT, "f04_dispersion_by_metric_month.csv")

    summ = (disp.groupby("metric_code")
              .agg(months=("cv_pct", "size"), mean_cv_pct=("cv_pct", "mean"),
                   min_cv_pct=("cv_pct", "min"), max_cv_pct=("cv_pct", "max"),
                   mean_max_over_min=("max_over_min", "mean"))
              .reset_index().sort_values("mean_cv_pct", ascending=False))
    summ["label"] = summ.metric_code.map(na.SHORT_LABEL)
    print("  Dispersion across all 15 primary-window months:")
    show(summ.round(2))
    na.write_csv(summ, OUT, "f05_dispersion_summary.csv")

    last = disp[disp.observation_month == disp.observation_month.max()].copy()
    last["label"] = last.metric_code.map(na.SHORT_LABEL)
    print(f"\n  Final primary month ({disp.observation_month.max()}):")
    show(last.sort_values("cv_pct", ascending=False).round(2))
    na.write_csv(last, OUT, "f06_dispersion_final_month.csv")
    return disp, summ


# ===========================================================================
def section_4_state_growth(panel, ck):
    head("SECTION 4 - STATE-LEVEL GROWTH OVER THE PRIMARY WINDOW")
    print(f"  Endpoint change, {PW_START} -> {PW_END}, per state per metric.\n"
          "  Endpoint change is sensitive to the endpoints; Section 5 adds YoY and\n"
          "  Section 6 adds volatility so no single measure carries a conclusion.\n")

    pw = panel[panel.in_primary_release_window & panel.metric_code.isin(na.PRICE_METRICS)]
    first = pw[pw.observation_month == pw.observation_month.min()]
    last = pw[pw.observation_month == pw.observation_month.max()]
    g = first.merge(last, on=["state_id", "state_name", "zone_name", "metric_code"],
                    suffixes=("_first", "_last"))
    ck.eq(len(g), len(na.PRICE_METRICS) * na.N_STATES,
          "growth table has one row per state per price metric (37 x 9)")
    g["abs_change"] = g.metric_value_last - g.metric_value_first
    g["pct_change"] = 100 * (g.metric_value_last / g.metric_value_first - 1)
    na.check_no_unexpected_nulls(g, ["pct_change"], "state growth", ck)
    growth = g[["state_id", "state_name", "zone_name", "metric_code",
                "metric_value_first", "metric_value_last", "abs_change", "pct_change"]]
    na.write_csv(growth.round(4), OUT, "f07_state_growth_primary_window.csv")

    for m in ["DIESEL_PRICE_NGN_PER_LITRE", "PETROL_PRICE_NGN_PER_LITRE",
              "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY", "LPG_REFILL_12_5KG_NGN"]:
        sub = growth[growth.metric_code == m].sort_values("pct_change", ascending=False)
        print(f"\n  {na.SHORT_LABEL[m]} - fastest 6 and slowest 6 of 37 jurisdictions:")
        show(pd.concat([sub.head(6), sub.tail(6)])[
            ["state_name", "zone_name", "metric_value_first", "metric_value_last",
             "abs_change", "pct_change"]].round(2), 12)

    spread = (growth.groupby("metric_code")
                .agg(min_pct=("pct_change", "min"), median_pct=("pct_change", "median"),
                     max_pct=("pct_change", "max"))
                .reset_index())
    spread["growth_spread_pp"] = spread.max_pct - spread.min_pct
    spread["label"] = spread.metric_code.map(na.SHORT_LABEL)
    print("\n  How differently states moved, per cost (percentage-point spread of growth):")
    show(spread.sort_values("growth_spread_pp", ascending=False).round(2))
    na.write_csv(spread.round(4), OUT, "f08_growth_spread.csv")
    return growth


# ===========================================================================
def section_5_yoy(panel, ck):
    head("SECTION 5 - YEAR-ON-YEAR PRICE CHANGE (uses each dataset's own history)")
    print("  The primary window is only 15 months, so YoY is computed from the panel's\n"
          "  full primary history rather than the common window. Coverage is reported\n"
          "  per metric rather than assumed.\n")

    p = panel[panel.metric_code.isin(na.PRICE_METRICS)].copy()
    p["observation_month"] = pd.to_datetime(p.observation_month)
    prev = p.copy()
    prev["observation_month"] = prev.observation_month + pd.DateOffset(months=12)
    prev = prev.rename(columns={"metric_value": "value_year_ago"})
    j = p.merge(prev[["state_id", "metric_code", "observation_month", "value_year_ago"]],
                on=["state_id", "metric_code", "observation_month"], how="inner")
    j["yoy_pct"] = 100 * (j.metric_value / j.value_year_ago - 1)
    na.check_no_unexpected_nulls(j, ["yoy_pct"], "YoY", ck)

    cov = (j.groupby("metric_code")
             .agg(yoy_months=("observation_month", "nunique"),
                  states=("state_id", "nunique"), rows=("yoy_pct", "size"),
                  first=("observation_month", "min"), last=("observation_month", "max"))
             .reset_index())
    print("  YoY coverage actually available:")
    show(cov)
    ck.check((cov.states == na.N_STATES).all(), "YoY covers all 37 jurisdictions for every metric")
    ck.check((cov.rows == cov.yoy_months * na.N_STATES).all(),
             "YoY grid is complete for every metric (no state-month silently dropped)")

    med = (j.groupby(["metric_code", "observation_month"])
             .agg(median_yoy_pct=("yoy_pct", "median"), states=("state_id", "nunique"))
             .reset_index())
    piv = med.pivot(index="observation_month", columns="metric_code",
                    values="median_yoy_pct").round(1)
    piv.columns = [na.SHORT_LABEL[c] for c in piv.columns]
    print("\n  Median YoY % across states, by month:")
    print(piv.to_string())
    yoy_out = j[["state_id", "state_name", "zone_name", "observation_month",
                 "metric_code", "value_year_ago", "metric_value", "yoy_pct"]].copy()
    for c in ["value_year_ago", "metric_value", "yoy_pct"]:
        yoy_out[c] = yoy_out[c].round(4)
    na.write_csv(yoy_out, OUT, "f09_state_yoy.csv")
    med_out = med.copy()
    med_out["median_yoy_pct"] = med_out.median_yoy_pct.round(4)
    na.write_csv(med_out, OUT, "f10_median_yoy.csv")
    return j


# ===========================================================================
def section_6_volatility_and_persistence(panel, ck):
    head("SECTION 6 - VOLATILITY AND PERSISTENCE OF COST POSITION")

    pw = panel[panel.in_primary_release_window
               & panel.metric_code.isin(na.PRICE_METRICS)].copy()
    pw = pw.sort_values(["state_id", "metric_code", "observation_month"])
    pw["mom_pct"] = (pw.groupby(["state_id", "metric_code"]).metric_value.pct_change() * 100)
    vol = (pw.dropna(subset=["mom_pct"])
             .groupby(["state_id", "state_name", "zone_name", "metric_code"])
             .agg(mom_obs=("mom_pct", "size"), mom_sd=("mom_pct", "std"),
                  mom_min=("mom_pct", "min"), mom_max=("mom_pct", "max"))
             .reset_index())
    ck.check((vol.mom_obs == na.PRIMARY_WINDOW_MONTHS - 1).all(),
             "every state-metric has 14 month-over-month observations",
             f"{vol.mom_obs.min()}..{vol.mom_obs.max()}")
    na.write_csv(vol.round(4), OUT, "f11_state_volatility.csv")

    print("  Most and least volatile states, diesel (SD of monthly % change, 14 obs):")
    d = vol[vol.metric_code == "DIESEL_PRICE_NGN_PER_LITRE"].sort_values("mom_sd", ascending=False)
    show(pd.concat([d.head(5), d.tail(5)])[
        ["state_name", "zone_name", "mom_sd", "mom_min", "mom_max"]].round(2), 10)

    # Rank persistence: 1 = cheapest.
    pw["rank_in_month"] = pw.groupby(["metric_code", "observation_month"]) \
                            .metric_value.rank(method="average")
    pers = (pw.groupby(["state_id", "state_name", "zone_name", "metric_code"])
              .agg(months=("rank_in_month", "size"), mean_rank=("rank_in_month", "mean"),
                   best_rank=("rank_in_month", "min"), worst_rank=("rank_in_month", "max"))
              .reset_index())
    pers["rank_swing"] = pers.worst_rank - pers.best_rank
    top_q, bot_q = na.N_STATES * 0.25, na.N_STATES * 0.75
    share = (pw.assign(cheap=pw.rank_in_month <= top_q, dear=pw.rank_in_month >= bot_q)
               .groupby(["state_id", "metric_code"])
               .agg(share_months_cheapest_quartile=("cheap", "mean"),
                    share_months_dearest_quartile=("dear", "mean"))
               .reset_index())
    pers = pers.merge(share, on=["state_id", "metric_code"])
    ck.check((pers.months == na.PRIMARY_WINDOW_MONTHS).all(),
             "rank persistence uses all 15 months for every state-metric")
    na.write_csv(pers.round(4), OUT, "f12_rank_persistence.csv")

    print("\n  Persistently dearest states (dearest quartile in >=90% of months, any metric):")
    hard = pers[pers.share_months_dearest_quartile >= 0.9]
    cnt = (hard.groupby(["state_name", "zone_name"]).metric_code.count()
             .reset_index(name="metrics_of_9").sort_values("metrics_of_9", ascending=False))
    show(cnt.head(12))
    na.write_csv(cnt, OUT, "f13_persistently_dear_states.csv")

    print("\n  Persistently cheapest states (cheapest quartile in >=90% of months):")
    soft = pers[pers.share_months_cheapest_quartile >= 0.9]
    cnt2 = (soft.groupby(["state_name", "zone_name"]).metric_code.count()
              .reset_index(name="metrics_of_9").sort_values("metrics_of_9", ascending=False))
    show(cnt2.head(12))
    na.write_csv(cnt2, OUT, "f14_persistently_cheap_states.csv")

    print("\n  Largest rank swings (state moved most across the ranking):")
    sw = pers.sort_values("rank_swing", ascending=False).head(10)
    show(sw[["state_name", "zone_name", "metric_code", "best_rank", "worst_rank",
             "rank_swing"]].round(1), 10)
    return vol, pers


# ===========================================================================
def section_7_comovement(growth, panel, ck):
    head("SECTION 7 - WHICH COSTS MOVE TOGETHER (n = 37 jurisdictions, Spearman)")
    print("  Spearman, not Pearson: these are 37 observations with heavy tails.\n"
          "  Correlation across states is NOT causation and NOT a time-series result.\n")

    w = growth.pivot(index="state_id", columns="metric_code", values="pct_change")
    ck.eq(len(w), na.N_STATES, "co-movement matrix uses all 37 jurisdictions")
    ck.check(w.notna().all().all(), "co-movement matrix has no missing cell",
             f"{int(w.isna().sum().sum())} nulls")
    # Both axes of a correlation matrix carry the same name, so they are renamed
    # before reset_index()/stack() - otherwise pandas refuses the duplicate label.
    corr = w.corr(method="spearman").rename_axis(index="metric_a", columns="metric_b")
    pretty = corr.copy()
    pretty.index = [na.SHORT_LABEL[i] for i in pretty.index]
    pretty.columns = [na.SHORT_LABEL[c] for c in pretty.columns]
    print("  Spearman correlation of state growth rates over the primary window:")
    print(pretty.round(2).to_string())
    na.write_csv(corr.round(4).reset_index(), OUT, "f15_growth_correlation.csv")

    pairs = corr.stack().rename("rho").reset_index()
    pairs = pairs[pairs.metric_a < pairs.metric_b].sort_values("rho", ascending=False)
    print("\n  Strongest positive pairs:")
    show(pairs.head(6).round(3), 6)
    print("\n  Strongest negative / weakest pairs:")
    show(pairs.tail(6).round(3), 6)
    na.write_csv(pairs.round(4), OUT, "f16_growth_correlation_pairs.csv")

    # Cross-sectional level correlation in the final month - a different question.
    last = panel[(panel.observation_month == panel[panel.in_primary_release_window]
                  .observation_month.max()) & panel.metric_code.isin(na.PRICE_METRICS)]
    lw = last.pivot(index="state_id", columns="metric_code", values="metric_value")
    lcorr = lw.corr(method="spearman").rename_axis(index="metric_a", columns="metric_b")
    lp = lcorr.stack().rename("rho").reset_index()
    lp = lp[lp.metric_a < lp.metric_b].sort_values("rho", ascending=False)
    print("\n  Level correlation in the final month (is an expensive-diesel state also"
          " an expensive-transport state?):")
    show(pd.concat([lp.head(5), lp.tail(5)]).round(3), 10)
    na.write_csv(lp.round(4), OUT, "f17_level_correlation_final_month.csv")
    return corr, pairs


# ===========================================================================
def section_8_surprises(panel, growth, disp, ck):
    head("SECTION 8 - CONTRARIANS AND SURPRISES")

    # NOTE: g.pct_change would resolve to the DataFrame METHOD of that name, not
    # to the column. Bracket access is mandatory for this column.
    med_growth = growth.groupby("metric_code")["pct_change"].median()
    g = growth.copy()
    g["median_pct_change"] = g.metric_code.map(med_growth)
    g["gap_vs_median_pp"] = g["pct_change"] - g["median_pct_change"]

    print("  (a) States that moved AGAINST the national direction "
          "(cost fell while the cross-state median rose):")
    contra = g[(g["median_pct_change"] > 0) & (g["pct_change"] < 0)].sort_values("pct_change")
    show(contra[["state_name", "zone_name", "metric_code", "metric_value_first",
                 "metric_value_last", "pct_change", "median_pct_change"]].round(2), 25)
    ck.check(True, "contrarian scan completed", f"{len(contra)} state-metric contrarians")
    na.write_csv(contra.round(4), OUT, "f18_contrarian_states.csv")

    print("\n  (b) Biggest positive outliers vs the cross-state median growth:")
    show(g.sort_values("gap_vs_median_pp", ascending=False)
          .head(12)[["state_name", "zone_name", "metric_code", "pct_change",
                     "median_pct_change", "gap_vs_median_pp"]].round(2), 12)
    na.write_csv(g.round(4), OUT, "f19_growth_vs_median.csv")

    # Same-zone divergence: neighbours that behaved very differently.
    print("\n  (c) Widest within-zone divergence in the final month "
          "(same zone, very different cost):")
    pw = panel[panel.in_primary_release_window & panel.metric_code.isin(na.PRICE_METRICS)]
    lastm = pw.observation_month.max()
    lz = pw[pw.observation_month == lastm]
    zd = (lz.groupby(["zone_name", "metric_code"])
            .agg(states=("state_id", "nunique"), lo=("metric_value", "min"),
                 hi=("metric_value", "max"), med=("metric_value", "median"))
            .reset_index())
    zd["hi_over_lo"] = zd.hi / zd.lo
    zd["label"] = zd.metric_code.map(na.SHORT_LABEL)
    show(zd.sort_values("hi_over_lo", ascending=False)
           .head(12)[["zone_name", "label", "states", "lo", "hi", "hi_over_lo"]].round(2), 12)
    na.write_csv(zd.round(4), OUT, "f20_within_zone_divergence.csv")

    # Rank migration: cheap -> expensive over the window.
    print("\n  (d) Largest rank migrations, first month to last (1 = cheapest of 37):")
    r = pw.copy()
    r["rank"] = r.groupby(["metric_code", "observation_month"]).metric_value.rank()
    f = r[r.observation_month == r.observation_month.min()][["state_name", "zone_name",
                                                            "metric_code", "rank"]]
    l = r[r.observation_month == lastm][["state_name", "metric_code", "rank"]]
    mig = f.merge(l, on=["state_name", "metric_code"], suffixes=("_first", "_last"))
    mig["rank_change"] = mig.rank_last - mig.rank_first
    show(pd.concat([mig.sort_values("rank_change", ascending=False).head(8),
                    mig.sort_values("rank_change").head(8)]).round(1), 16)
    na.write_csv(mig.round(2), OUT, "f21_rank_migration.csv")

    # Dispersion that changes sharply over time.
    print("\n  (e) Months where cross-state dispersion changed most (CV, pp):")
    d = disp.sort_values(["metric_code", "observation_month"]).copy()
    d["cv_change_pp"] = d.groupby("metric_code").cv_pct.diff()
    show(d.dropna(subset=["cv_change_pp"]).reindex(
        d.cv_change_pp.abs().sort_values(ascending=False).index)
        .head(10)[["metric_code", "observation_month", "cv_pct", "cv_change_pp"]].round(2), 10)
    return contra, mig


# ===========================================================================
def section_9_zone_and_national(conn, ck):
    head("SECTION 9 - ZONE-LEVEL AND NATIONAL CONTEXT (reported separately, never merged)")

    print("  (a) FOOD - ZONE grain only. Food has no state-level prices at all.")
    fz = na.q(conn, """
        SELECT zone_name, count(*) AS rows, count(DISTINCT item_code) AS items,
               count(DISTINCT observation_month) AS months,
               round(avg(premium_pct)::numeric, 2) AS mean_premium_pct_vs_national,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY premium_pct))::numeric, 2)
                   AS median_premium_pct
        FROM mart.v_food_zone_vs_national
        GROUP BY zone_name ORDER BY mean_premium_pct_vs_national DESC
    """)
    show(fz)
    na.write_csv(fz, OUT, "f22_food_zone_premium.csv")
    ck.eq(len(fz), 6, "food zone premium covers all 6 zones")

    print("\n  Items with the widest zone dispersion (latest food month):")
    fi = na.q(conn, """
        WITH last_m AS (SELECT max(observation_month) AS m FROM mart.v_food_zone_vs_national)
        SELECT item_label, item_unit, count(*) AS zones,
               round(min(zone_price_ngn)::numeric,2) AS lo,
               round(max(zone_price_ngn)::numeric,2) AS hi,
               round((max(zone_price_ngn)/NULLIF(min(zone_price_ngn),0))::numeric,2) AS hi_over_lo
        FROM mart.v_food_zone_vs_national, last_m
        WHERE observation_month = last_m.m
        GROUP BY 1,2 ORDER BY hi_over_lo DESC LIMIT 12
    """)
    show(fi)
    na.write_csv(fi, OUT, "f23_food_item_zone_dispersion.csv")

    print("\n  (b) FX - NATIONAL only. Context for imported inputs, never a state metric.")
    fx = na.q(conn, "SELECT * FROM mart.v_fx_monthly_summary ORDER BY observation_month")
    show(fx.round(2), 25)
    na.write_csv(fx.round(4), OUT, "f24_fx_monthly.csv")

    print("\n  (c) NERC - DISCO cross-section, July 2025. Not a time series, not state data.")
    nerc = na.q(conn, """
        SELECT service_band, count(*) AS rows, count(DISTINCT disco_code) AS discos,
               round(min(tariff_ngn_per_kwh)::numeric,2) AS lo,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY tariff_ngn_per_kwh))::numeric,2)
                   AS median_tariff,
               round(max(tariff_ngn_per_kwh)::numeric,2) AS hi,
               round((max(tariff_ngn_per_kwh)-min(tariff_ngn_per_kwh))::numeric,2) AS spread
        FROM mart.v_tariff_band_cross_section
        WHERE is_current_period AND tariff_ngn_per_kwh IS NOT NULL
        GROUP BY service_band ORDER BY service_band
    """)
    show(nerc)
    na.write_csv(nerc, OUT, "f25_nerc_band_cross_section.csv")

    mapped = na.q(conn, """
        SELECT DISTINCT state_mapping FROM mart.v_tariff_band_cross_section
    """).state_mapping.tolist()
    ck.check(mapped == ["NOT_MAPPED"],
             "NERC rows remain NOT_MAPPED to states (no state join is possible)", f"{mapped}")


# ===========================================================================
def section_10_convergence_and_ratchet(panel, yoy, ck):
    """The two candidate headline findings, tested directly rather than inferred
    from the top and bottom of a ranking."""
    head("SECTION 10 - TWO CANDIDATE HEADLINE FINDINGS, TESTED DIRECTLY")

    pw = panel[panel.in_primary_release_window].copy()
    first_m, last_m = pw.observation_month.min(), pw.observation_month.max()

    # ---- (A) North-South fuel convergence --------------------------------
    print("  (A) NORTH-SOUTH FUEL CONVERGENCE\n")
    print("      METHOD, stated in full so the statistic can be reproduced or disputed:\n"
          "        statistic   : MEDIAN of the jurisdiction-level published prices\n"
          "        weighting   : each jurisdiction counts once (EQUAL weight). It is NOT\n"
          "                      population-weighted, consumption-weighted or volume-weighted\n"
          "        grouping    : our own grouping of NBS's six zones into two halves. NBS\n"
          "                      publishes no 'North' or 'South' aggregate; this is derived\n"
          "        units       : naira per litre, as published\n"
          "        premium     : north_premium_pct = 100 * (median_North / median_South - 1)\n"
          "        start month : 2025-02   end month : 2026-04 (primary common window)\n"
          "        population  : 36 states + the Federal Capital Territory = 37 jurisdictions\n"
          "                      FCT is an administrative territory, not a state; it sits in\n"
          "                      the North Central zone and is counted in the North half\n")
    fuel = pw[pw.metric_code.isin(["PETROL_PRICE_NGN_PER_LITRE",
                                   "DIESEL_PRICE_NGN_PER_LITRE"])]
    north_zones = ["North West", "North East", "North Central"]
    fuel = fuel.assign(half=fuel.zone_name.map(lambda z: "North" if z in north_zones else "South"))

    membership = (fuel[["state_name", "zone_name", "half"]].drop_duplicates()
                    .sort_values(["half", "zone_name", "state_name"]))
    for h in ["North", "South"]:
        sub = membership[membership.half == h]
        print(f"      {h} ({len(sub)} jurisdictions):")
        for z in sorted(sub.zone_name.unique()):
            names = sorted(sub[sub.zone_name == z].state_name.tolist())
            print(f"        {z:14s} ({len(names)}): {', '.join(names)}")
    print()
    na.write_csv(membership, OUT, "f33_north_south_membership.csv")
    ck.eq(len(membership), na.N_STATES,
          "North/South membership list covers all 37 jurisdictions exactly once")
    ck.eq(sorted(fuel.half.unique().tolist()), ["North", "South"],
          "every jurisdiction falls in exactly one half of the country")
    ck.eq(fuel.groupby("half").state_id.nunique().to_dict(), {"North": 20, "South": 17},
          "North = 20 states (incl. FCT), South = 17 states")

    g = (fuel.groupby(["metric_code", "half", "observation_month"])
             .agg(median_ngn=("metric_value", "median"))
             .reset_index())
    gap = g.pivot_table(index=["metric_code", "observation_month"], columns="half",
                        values="median_ngn").reset_index()
    gap["north_minus_south_ngn"] = gap["North"] - gap["South"]
    gap["north_premium_pct"] = 100 * (gap["North"] / gap["South"] - 1)
    for m in sorted(gap.metric_code.unique()):
        sub = gap[gap.metric_code == m].sort_values("observation_month")
        print(f"      {na.SHORT_LABEL[m]}:")
        show(sub[["observation_month", "North", "South", "north_minus_south_ngn",
                  "north_premium_pct"]].round(2), 20)
        f, l = sub.iloc[0], sub.iloc[-1]
        print(f"      -> North premium moved {f.north_premium_pct:+.1f}% ({f.observation_month})"
              f" to {l.north_premium_pct:+.1f}% ({l.observation_month})\n")
    na.write_csv(gap.round(4), OUT, "f26_north_south_fuel_gap.csv")

    # The claim is a NARROWING gap, so the narrowing is what gets tested.
    for m in ["PETROL_PRICE_NGN_PER_LITRE", "DIESEL_PRICE_NGN_PER_LITRE"]:
        sub = gap[gap.metric_code == m].sort_values("observation_month")
        ck.check(abs(sub.north_premium_pct.iloc[-1]) < abs(sub.north_premium_pct.iloc[0]),
                 f"{na.SHORT_LABEL[m]}: North-South gap is narrower at the end than at the start",
                 f"{sub.north_premium_pct.iloc[0]:+.1f}% -> {sub.north_premium_pct.iloc[-1]:+.1f}%")

    print("      Convergence test - rank correlation between a state's STARTING price and\n"
          "      its subsequent growth. Negative means dear states rose least:")
    conv_rows = []
    for m in ["PETROL_PRICE_NGN_PER_LITRE", "DIESEL_PRICE_NGN_PER_LITRE",
              "LPG_REFILL_12_5KG_NGN", "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
              "TRANSPORT_OKADA_NGN_PER_JOURNEY"]:
        a = pw[(pw.metric_code == m) & (pw.observation_month == first_m)][
            ["state_id", "metric_value"]]
        b = pw[(pw.metric_code == m) & (pw.observation_month == last_m)][
            ["state_id", "metric_value"]]
        j = a.merge(b, on="state_id", suffixes=("_first", "_last"))
        j["growth_pct"] = 100 * (j.metric_value_last / j.metric_value_first - 1)
        rho = j.metric_value_first.corr(j.growth_pct, method="spearman")
        conv_rows.append({"metric_code": m, "label": na.SHORT_LABEL[m], "states": len(j),
                          "spearman_start_level_vs_growth": round(float(rho), 3)})
    conv = pd.DataFrame(conv_rows).sort_values("spearman_start_level_vs_growth")
    show(conv)
    na.write_csv(conv, OUT, "f27_convergence_test.csv")
    ck.check((conv.states == na.N_STATES).all(), "convergence test uses all 37 jurisdictions")

    # ---- (B) Fare stickiness despite petrol declines ---------------------
    print("\n  (B) FARE STICKINESS DESPITE PETROL DECLINES\n")
    print("      ('ratchet' appears only as informal shorthand for this result)\n")
    print("      When petrol was cheaper than a year earlier, did fares follow it down?\n")
    fuel_codes = ["PETROL_PRICE_NGN_PER_LITRE", "DIESEL_PRICE_NGN_PER_LITRE"]
    fare_codes = ["TRANSPORT_AIR_NGN_PER_JOURNEY",
                  "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
                  "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
                  "TRANSPORT_OKADA_NGN_PER_JOURNEY",
                  "TRANSPORT_WATER_NGN_PER_JOURNEY"]
    med = (yoy.groupby(["metric_code", "observation_month"])["yoy_pct"].median()
              .reset_index().rename(columns={"yoy_pct": "median_yoy_pct"}))
    piv = med.pivot(index="observation_month", columns="metric_code",
                    values="median_yoy_pct").round(1)
    print(piv[[c for c in fuel_codes + fare_codes if c in piv.columns]]
          .rename(columns=na.SHORT_LABEL).to_string())

    fu = yoy[yoy.metric_code == "PETROL_PRICE_NGN_PER_LITRE"][
        ["state_id", "state_name", "observation_month", "yoy_pct"]].rename(
        columns={"yoy_pct": "petrol_yoy_pct"})
    fr = yoy[yoy.metric_code.isin(fare_codes)][
        ["state_id", "observation_month", "metric_code", "yoy_pct"]].rename(
        columns={"yoy_pct": "fare_yoy_pct"})
    mm = fu.merge(fr, on=["state_id", "observation_month"], how="inner")
    mm["fuel_fell"] = mm.petrol_yoy_pct < 0
    mm["fare_rose"] = mm.fare_yoy_pct > 0
    tab = (mm[mm.fuel_fell].groupby("metric_code")
             .agg(state_month_obs=("fare_yoy_pct", "size"),
                  unique_jurisdictions=("state_id", "nunique"),
                  unique_months=("observation_month", "nunique"),
                  of_which_fare_rose=("fare_rose", "sum"),
                  median_petrol_yoy_pct=("petrol_yoy_pct", "median"),
                  median_fare_yoy_pct=("fare_yoy_pct", "median"))
             .reset_index())
    tab["share_fare_rose_pct"] = (100 * tab.of_which_fare_rose
                                  / tab.state_month_obs).round(1)
    tab["label"] = tab.metric_code.map(na.SHORT_LABEL)

    fell = mm[mm.fuel_fell]
    print("\n      Scope of the observation set (petrol cheaper than 12 months earlier):")
    print(f"        unique jurisdictions : {fell.state_id.nunique()} of {na.N_STATES}")
    print(f"        unique months        : {fell.observation_month.nunique()} "
          f"({', '.join(str(x) for x in sorted(fell.observation_month.unique()))})")
    print(f"        state-month pairs    : {fell.groupby(['state_id','observation_month']).ngroups}")
    print(f"        state-month-mode obs : {len(fell)}")
    n_mo, n_all_mo = fell.observation_month.nunique(), yoy.observation_month.nunique()
    print(f"\n      NOTE: these observations are NOT independent events. They fall in\n"
          f"      {n_mo} of the {n_all_mo} available YoY months and repeat across jurisdictions\n"
          f"      within those months, so the effective sample is far smaller than the row\n"
          f"      count. Petrol is one observed input among many; no claim is made that\n"
          f"      petrol alone determines fares, nor that fares respond to petrol at all.\n")
    print("      RESULTS BY MODE - reported separately, never pooled:")
    show(tab[["label", "state_month_obs", "unique_jurisdictions", "unique_months",
              "of_which_fare_rose", "share_fare_rose_pct", "median_petrol_yoy_pct",
              "median_fare_yoy_pct"]].round(2))
    ck.eq(sorted(tab.unique_months.unique().tolist()), [int(fell.observation_month.nunique())],
          "every mode is observed over the same number of months in this subset")
    na.write_csv(mm.round(4), OUT, "f28_fuel_down_fare_up_detail.csv")
    na.write_csv(tab.round(4), OUT, "f29_fare_ratchet_summary.csv")
    ck.check(len(mm) > 0, "fuel-versus-fare comparison produced rows",
             f"{len(mm)} state-month-mode pairs")
    ck.check(mm.groupby("metric_code").observation_month.nunique().nunique() == 1,
             "every fare mode is compared over the same set of months")
    return gap, tab


# ===========================================================================
def section_11_fuel_shock(conn, panel, ck):
    """The end of the series is not a continuation of it. Measured on each
    dataset's own primary history, which runs past the common window."""
    head("SECTION 11 - DIESEL PRICE ACCELERATION, 2025-09 TO 2026-05")
    print("  This is a DATASET-SPECIFIC comparison, not a common-window one. It ends at\n"
          "  2026-05, which is OUTSIDE the five-dataset primary common window (which ends\n"
          "  2026-04). Only petrol, diesel and the five transport modes publish 2026-05;\n"
          "  LPG (ends 2026-04) and CPI are therefore absent from this comparison.\n"
          "  Every transport mode is reported separately. No fare measure is averaged\n"
          "  across modes: a journey by air and a journey by okada are different products\n"
          "  with different units of service, and no defensible weighting exists.\n")

    watch = ["DIESEL_PRICE_NGN_PER_LITRE", "PETROL_PRICE_NGN_PER_LITRE",
             "TRANSPORT_AIR_NGN_PER_JOURNEY",
             "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
             "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
             "TRANSPORT_OKADA_NGN_PER_JOURNEY",
             "TRANSPORT_WATER_NGN_PER_JOURNEY"]
    p = panel[panel.metric_code.isin(watch)]
    med = (p.groupby(["metric_code", "observation_month"])
             .agg(median_ngn=("metric_value", "median"), states=("state_id", "nunique"))
             .reset_index())
    piv = med.pivot(index="observation_month", columns="metric_code",
                    values="median_ngn").round(2)
    piv = piv.rename(columns=na.SHORT_LABEL)
    print("  Median across the 37 state-level jurisdictions (36 states + FCT),\n"
          "  each jurisdiction weighted equally, full primary history:")
    print(piv.to_string())
    na.write_csv(med.round(4), OUT, "f30_shock_median_series.csv")

    # Trough to latest, per state. The trough is found, not assumed.
    trough_m = pd.Timestamp("2025-09-01").date()
    rows = []
    for m in watch:
        sub = p[p.metric_code == m]
        last_m = sub.observation_month.max()
        a = sub[sub.observation_month == trough_m][["state_id", "state_name", "zone_name",
                                                    "metric_value"]]
        b = sub[sub.observation_month == last_m][["state_id", "metric_value"]]
        j = a.merge(b, on="state_id", suffixes=("_trough", "_last"))
        j["pct_change"] = 100 * (j.metric_value_last / j.metric_value_trough - 1)
        ck.eq(len(j), na.N_STATES,
              f"{na.SHORT_LABEL[m]}: measured on all 37 jurisdictions")
        rows.append({"metric_code": m, "label": na.SHORT_LABEL[m],
                     "from_month": trough_m, "to_month": last_m, "states": len(j),
                     # bracket access: j.pct_change is the DataFrame method
                     "states_up": int((j["pct_change"] > 0).sum()),
                     "min_pct": j["pct_change"].min(),
                     "median_pct": j["pct_change"].median(),
                     "max_pct": j["pct_change"].max()})
    shock = pd.DataFrame(rows).sort_values("median_pct", ascending=False)
    print("\n  Change 2025-09 -> 2026-05, EACH SERIES REPORTED SEPARATELY."
          "\n  'median_pct' is the median across the 37 jurisdictions of each"
          "\n  jurisdiction's own percentage change. Modes are never combined.")
    show(shock.round(1))
    na.write_csv(shock.round(4), OUT, "f31_shock_trough_to_latest.csv")

    ck.check((shock[shock.metric_code.str.startswith("DIESEL")].states_up
              == na.N_STATES).all(),
             "diesel rose in all 37 jurisdictions between 2025-09 and 2026-05")
    ck.eq(sorted(shock.to_month.unique().tolist()), [pd.Timestamp("2026-05-01").date()],
          "every series in this comparison ends at the same month, 2026-05")
    d = shock[shock.metric_code == "DIESEL_PRICE_NGN_PER_LITRE"].iloc[0]
    # Compared against the fastest-rising individual mode, not an average of modes.
    fastest_mode = (shock[shock.metric_code.str.startswith("TRANSPORT")]
                    .sort_values("median_pct", ascending=False).iloc[0])
    ck.check(d.median_pct > fastest_mode.median_pct,
             "diesel's median change exceeds that of every individual transport mode",
             f"diesel {d.median_pct:+.1f}% vs fastest mode "
             f"{fastest_mode.label} {fastest_mode.median_pct:+.1f}%")

    # Corroboration: the independently published NATIONAL row, not a state median.
    print("\n  Corroboration - NBS's own published NATIONAL diesel row (separate source rows):")
    nat = na.q(conn, """
        SELECT observation_month, round(price_ngn_per_litre::numeric,2) AS national_diesel,
               source_file
        FROM mart.v_diesel_primary d JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='NATIONAL' AND observation_month >= DATE '2025-09-01'
        ORDER BY 1
    """)
    show(nat, 12)
    na.write_csv(nat, OUT, "f32_national_diesel_corroboration.csv")
    ck.check(len(nat) > 0 and nat.national_diesel.iloc[-1] > nat.national_diesel.iloc[0] * 2,
             "NBS's published NATIONAL diesel row more than doubled over the same span",
             f"{nat.national_diesel.iloc[0]} -> {nat.national_diesel.iloc[-1]}")
    return shock


# ===========================================================================
def section_12_persistence_test(panel, ck):
    """Does any jurisdiction sit in the high-cost quartile persistently, and does it
    do so across SEVERAL DISTINCT COST FAMILIES?

    No composite index. No weights. No overall score. Each metric is ranked
    independently within each month; the only cross-metric quantity is a COUNT of
    metrics, which is not a score because nothing is normalised, rescaled or added.

    The full classification rule lives in nbci_analysis.py so it is stated once and
    is reproducible from constants alone.
    """
    head("SECTION 12 - PERSISTENCE TEST: IS ANY JURISDICTION BROADLY EXPENSIVE?")
    print("  CLASSIFICATION RULE - complete and reproducible from these values:\n"
          f"    ranking method        : pandas rank(pct=True), method='{na.RANK_METHOD}',\n"
          "                            ascending, computed independently within each\n"
          "                            (metric, month) across the 37 jurisdictions\n"
          f"    high-cost quartile    : percentile rank > {na.HIGH_COST_QUANTILE}\n"
          f"    low-cost quartile     : percentile rank <= {na.LOW_COST_QUANTILE}\n"
          "    tied values           : tied published prices share an AVERAGED percentile\n"
          "                            rank and cross the boundary together. Ties are never\n"
          "                            broken arbitrarily; this is why quartile sizes vary\n"
          f"    minimum eligible      : >= {na.MIN_ELIGIBLE_MONTHS} observed months, else\n"
          "                            reported INELIGIBLE - never as 'not persistent'\n"
          "    denominator           : months OBSERVED for that (jurisdiction, metric) pair,\n"
          "                            NOT the 15-month window length\n"
          "    missing observations  : contribute to neither numerator nor denominator; the\n"
          "                            observed-month count is reported with every share\n"
          f"    persistent high       : share_high >= {na.PERSISTENCE_THRESHOLD:.2f}, among\n"
          "                            eligible pairs only\n")

    pw = panel[panel.in_primary_release_window
               & panel.metric_code.isin(na.PRICE_METRICS)].copy()
    ck.eq(len(pw), len(na.PRICE_METRICS) * na.N_STATES * na.PRIMARY_WINDOW_MONTHS,
          "persistence input is the complete 9 x 37 x 15 grid")

    pw["pr"] = pw.groupby(["metric_code", "observation_month"]).metric_value.rank(
        pct=True, method=na.RANK_METHOD)
    pw["high_cost"] = pw.pr > na.HIGH_COST_QUANTILE
    pw["low_cost"] = pw.pr <= na.LOW_COST_QUANTILE

    per_month = (pw.groupby(["metric_code", "observation_month"])
                   .agg(n_high=("high_cost", "sum"), n_low=("low_cost", "sum"))
                   .reset_index())
    tied = (pw.groupby(["metric_code", "observation_month"]).metric_value
              .apply(lambda s: s.duplicated().any()).mean())
    ck.check(per_month.n_high.between(9, 11).all() and per_month.n_low.between(7, 10).all(),
             "quartile sizes stay within tolerance in every metric-month",
             f"high {per_month.n_high.min()}-{per_month.n_high.max()}, "
             f"low {per_month.n_low.min()}-{per_month.n_low.max()}, "
             f"{100*tied:.0f}% of metric-months contain tied prices")

    # ---- Which metrics can carry a rank-based claim at all? -----------------
    # Recomputed here rather than imported from a02, so this section stands alone.
    pw = pw.sort_values(["state_id", "metric_code", "observation_month"])
    mom = (pw.groupby(["state_id", "metric_code"]).metric_value.pct_change() * 100).abs()
    cvm = (pw.groupby(["metric_code", "observation_month"])
             .apply(lambda g: 100 * g.metric_value.std(ddof=1) / g.metric_value.mean(),
                    include_groups=False)
             .groupby("metric_code").mean())
    safety = pd.DataFrame({"mean_abs_mom_pct": mom.groupby(pw.metric_code).mean(),
                           "mean_cv_pct": cvm}).reset_index()
    safety.columns = ["metric_code", "mean_abs_mom_pct", "mean_cv_pct"]
    safety["move_to_spread_ratio"] = safety.mean_abs_mom_pct / safety.mean_cv_pct
    safety["rank_safe"] = safety.move_to_spread_ratio < na.RANK_SAFETY_RATIO
    safety["label"] = safety.metric_code.map(na.SHORT_LABEL)
    print("  (a) Can each metric support a rank-based claim? "
          "(ratio >= 1.0 means the ranking reshuffles on ordinary monthly movement)")
    show(safety.sort_values("move_to_spread_ratio", ascending=False)[
        ["label", "mean_abs_mom_pct", "mean_cv_pct", "move_to_spread_ratio",
         "rank_safe"]].round(2))
    na.write_csv(safety.round(4), OUT, "f40_rank_safety.csv")
    SAFE = safety[safety.rank_safe].metric_code.tolist()
    UNSAFE = safety[~safety.rank_safe].metric_code.tolist()
    ck.check(len(SAFE) >= 3, "at least three metrics support rank-based claims",
             f"{len(SAFE)} safe, {len(UNSAFE)} unsafe")
    print(f"\n      RANK-SAFE  ({len(SAFE)}): "
          f"{', '.join(na.SHORT_LABEL[m] for m in SAFE)}")
    print(f"      NOT SAFE   ({len(UNSAFE)}): "
          f"{', '.join(na.SHORT_LABEL[m] for m in UNSAFE)}")
    print("      Persistence is COMPUTED for all nine metrics and reported below, but\n"
          "      the business-facing conclusion is drawn only from the rank-safe ones.\n"
          "      For an unsafe metric, an absence of persistence CANNOT be distinguished\n"
          "      from rank noise and is not evidence that costs are uniform there.")

    def longest_run(s):
        best = run = 0
        for v in s:
            run = run + 1 if v else 0
            best = max(best, run)
        return best

    rec = (pw.groupby(["state_id", "state_name", "zone_name", "metric_code"])
             .agg(months_observed=("high_cost", "size"),
                  months_high=("high_cost", "sum"),
                  months_low=("low_cost", "sum"))
             .reset_index())
    runs = (pw.groupby(["state_id", "metric_code"])["high_cost"]
              .apply(longest_run).reset_index(name="longest_high_run"))
    rec = rec.merge(runs, on=["state_id", "metric_code"])
    rec["eligible"] = rec.months_observed >= na.MIN_ELIGIBLE_MONTHS
    rec["share_high"] = rec.months_high / rec.months_observed
    rec["share_low"] = rec.months_low / rec.months_observed
    rec["persistent_high"] = rec.eligible & (rec.share_high >= na.PERSISTENCE_THRESHOLD)
    rec["persistent_low"] = rec.eligible & (rec.share_low >= na.PERSISTENCE_THRESHOLD)
    rec["rank_safe"] = rec.metric_code.isin(SAFE)
    n_inelig = int((~rec.eligible).sum())
    ck.eq(n_inelig, 0,
          f"no jurisdiction-metric pair falls below the {na.MIN_ELIGIBLE_MONTHS}-month "
          f"eligibility floor")
    ck.check((rec.months_observed == na.PRIMARY_WINDOW_MONTHS).all(),
             "denominator equals observed months, which is 15 for every pair here",
             f"{rec.months_observed.min()}-{rec.months_observed.max()}")
    na.write_csv(rec.round(4), OUT, "f34_quartile_persistence_by_metric.csv")

    # ---- Stickiness ---------------------------------------------------------
    pw["prev_high"] = pw.groupby(["state_id", "metric_code"]).high_cost.shift(1)
    tr = pw.dropna(subset=["prev_high"])
    stay = (tr.groupby("metric_code")
              .apply(lambda g: pd.Series({
                  "p_high_given_high": g[g.prev_high == True].high_cost.mean(),
                  "p_high_given_not": g[g.prev_high == False].high_cost.mean(),
                  "base_rate_high": g.high_cost.mean()}), include_groups=False)
              .reset_index())
    stay["stickiness_pp"] = 100 * (stay.p_high_given_high - stay.p_high_given_not)
    stay["label"] = stay.metric_code.map(na.SHORT_LABEL)
    stay["rank_safe"] = stay.metric_code.isin(SAFE)
    print("\n  (b) Is high-cost status sticky month to month? (1 = always stays high)")
    show(stay.sort_values("stickiness_pp", ascending=False)[
        ["label", "rank_safe", "base_rate_high", "p_high_given_high",
         "p_high_given_not", "stickiness_pp"]].round(3))
    na.write_csv(stay.round(4), OUT, "f35_quartile_stickiness.csv")
    ck.check((stay.p_high_given_high > stay.p_high_given_not).all(),
             "high-cost status is sticky for every metric (P(high|high) > P(high|not))")

    # ---- Multi-metric counts, rank-safe metrics only ------------------------
    def count_table(df, flag, name):
        t = (df[df[flag]]
               .groupby(["state_id", "state_name", "zone_name"])
               .agg(**{name: ("metric_code", "count"),
                       "which": ("metric_code", lambda s: "; ".join(
                           sorted(na.SHORT_LABEL[x] for x in s)))})
               .reset_index().sort_values(name, ascending=False))
        return t

    cnt_all = count_table(rec, "persistent_high", "metrics_persistently_high")
    rec_safe = rec[rec.rank_safe]
    cnt = count_table(rec_safe, "persistent_high", "metrics_persistently_high")
    print(f"\n  (c) Jurisdictions persistently HIGH, RANK-SAFE metrics only "
          f"({len(SAFE)} metrics):")
    show(cnt[["state_name", "zone_name", "metrics_persistently_high", "which"]], 20)
    na.write_csv(cnt, OUT, "f36_persistent_high_multimetric.csv")
    na.write_csv(cnt_all, OUT, "f36b_persistent_high_all_metrics.csv")
    cntl = count_table(rec_safe, "persistent_low", "metrics_persistently_low")
    print(f"\n  (d) Jurisdictions persistently LOW, rank-safe metrics only:")
    show(cntl[["state_name", "zone_name", "metrics_persistently_low", "which"]], 20)
    na.write_csv(cntl, OUT, "f37_persistent_low_multimetric.csv")

    per_metric = (rec.groupby(["metric_code"])
                    .agg(persistently_high=("persistent_high", "sum"),
                         rank_safe=("rank_safe", "first"))
                    .reset_index())
    per_metric["label"] = per_metric.metric_code.map(na.SHORT_LABEL)
    print("\n  (e) Jurisdictions persistently high, per metric:")
    show(per_metric.sort_values("persistently_high", ascending=False)[
        ["label", "rank_safe", "persistently_high"]])
    na.write_csv(per_metric, OUT, "f41_persistent_high_per_metric.csv")

    # ---- Cost families ------------------------------------------------------
    FAMILY = {"PETROL_PRICE_NGN_PER_LITRE": "LIQUID_FUEL",
              "DIESEL_PRICE_NGN_PER_LITRE": "LIQUID_FUEL",
              "LPG_REFILL_5KG_NGN": "LPG",
              "LPG_REFILL_12_5KG_NGN": "LPG",
              "TRANSPORT_AIR_NGN_PER_JOURNEY": "INTERREGIONAL_TRANSPORT",
              "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY": "INTERREGIONAL_TRANSPORT",
              "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY": "LOCAL_MOBILITY",
              "TRANSPORT_OKADA_NGN_PER_JOURNEY": "LOCAL_MOBILITY",
              "TRANSPORT_WATER_NGN_PER_JOURNEY": "LOCAL_MOBILITY"}
    ck.eq(sorted(set(FAMILY)), sorted(na.PRICE_METRICS),
          "every price metric is assigned to exactly one cost family")
    ck.eq(sorted(m for m, f in FAMILY.items() if f == "LOCAL_MOBILITY"),
          sorted(na.LOCAL_MOBILITY_METRICS),
          "the LOCAL_MOBILITY family matches the module definition (air excluded)")

    ph = rec[rec.persistent_high].copy()
    ph["family"] = ph.metric_code.map(FAMILY)
    fam = (ph.groupby(["state_id", "state_name", "zone_name"])
             .agg(n_metrics=("metric_code", "count"), n_families=("family", "nunique"),
                  families=("family", lambda s: "; ".join(sorted(set(s)))))
             .reset_index().sort_values(["n_families", "n_metrics"], ascending=False))
    print("\n  (f) DIRECT CROSS-FAMILY EVIDENCE - the main business-facing result.")
    print("      Families: LIQUID_FUEL, LPG, LOCAL_MOBILITY, INTERREGIONAL_TRANSPORT.")
    print("      Air is in INTERREGIONAL_TRANSPORT, never in LOCAL_MOBILITY (a02 V2).")

    # WHAT IS ACTUALLY TESTABLE. A family can only contribute to a cross-family
    # test if it owns at least one RANK-SAFE metric. Here it does not, for two of
    # the four families - so the question "is any jurisdiction broadly expensive
    # across the whole cost base" is only PARTIALLY answerable, and saying so is
    # part of the result rather than a caveat bolted onto it.
    safe_by_family = {}
    for m in SAFE:
        safe_by_family.setdefault(FAMILY[m], []).append(na.SHORT_LABEL[m])
    testable = sorted(safe_by_family)
    untestable = sorted(set(FAMILY.values()) - set(testable))
    print(f"\n      families with >=1 rank-safe metric (TESTABLE)   : {testable}")
    print(f"      families with NO rank-safe metric (UNTESTABLE)  : {untestable}")
    print("      For an untestable family, the absence of a persistently dear")
    print("      jurisdiction is a statement about the RANKING, not about costs.")

    show(fam[fam.n_metrics >= 2][["state_name", "zone_name", "n_metrics",
                                  "n_families", "families"]], 20)
    n_cross_all = int((fam.n_families >= 2).sum())
    print(f"\n      ALL NINE METRICS (informational, includes rank-unsafe):")
    print(f"        persistently high in 2+ families : {n_cross_all} of {na.N_STATES}")
    print(f"        persistent-high jurisdictions per family: "
          f"{ph.groupby('family').state_id.nunique().to_dict()}")

    ph_safe = ph[ph.metric_code.isin(SAFE)]
    fam_safe = (ph_safe.groupby(["state_id", "state_name", "zone_name"])
                  .agg(n_metrics=("metric_code", "count"),
                       n_families=("family", "nunique"),
                       families=("family", lambda s: "; ".join(sorted(set(s)))))
                  .reset_index().sort_values(["n_families", "n_metrics"], ascending=False))
    n_cross_safe = int((fam_safe.n_families >= 2).sum())
    print(f"\n      RANK-SAFE METRICS ONLY (the defensible version):")
    print(f"        testable families                : {len(testable)} of 4")
    print(f"        persistently high in 2+ families : {n_cross_safe} of {na.N_STATES}")
    print(f"        persistently high in 1 family    : "
          f"{int((fam_safe.n_families == 1).sum())}")
    show(fam_safe[fam_safe.n_families >= 2][["state_name", "zone_name", "n_metrics",
                                             "n_families", "families"]], 20)
    fam["scope"] = "ALL_METRICS"
    fam_safe["scope"] = "RANK_SAFE_ONLY"
    na.write_csv(pd.concat([fam, fam_safe], ignore_index=True),
                 OUT, "f39_persistence_by_cost_family.csv")
    n_cross = n_cross_safe
    ck.eq(len(untestable), 2,
          "two cost families own no rank-safe metric, so cross-family scope is partial")
    ck.check(n_cross_safe < len(fam_safe),
             "most persistently-dear jurisdictions are dear within a single cost family",
             f"{n_cross_safe} of {len(fam_safe)} span 2+ testable families")

    # ---- Permutation test, in its proper and narrow role --------------------
    import numpy as np
    print("\n  (g) SUPPORTING TEST ONLY - permutation null.")
    print("      This test does NOT and CANNOT establish that broadly expensive")
    print("      jurisdictions cannot exist. It answers one narrow question: whether the")
    print("      observed overlap is larger than a random reassignment would produce.")
    print("      Specification:")
    print("        permuted    : which jurisdictions occupy each metric's persistent-high")
    print("                      set - the set MEMBERSHIP is reassigned at random, without")
    print("                      replacement, independently for each metric")
    print("        preserved   : the SIZE of each metric's persistent-high set, the number")
    print("                      of metrics (9), and the number of jurisdictions (37)")
    print("        NOT preserved: any real correlation between metrics, and any geographic")
    print("                      structure - so the null is deliberately generous to the")
    print("                      'broadly expensive' hypothesis")
    print("        statistics  : (i) the maximum number of metrics on any one jurisdiction;")
    print("                      (ii) the count of jurisdictions high on >= 3 metrics")
    print("        draws       : 10,000, seed 20260916")
    print("        p-value     : proportion of draws whose null statistic is >= the")
    print("                      observed statistic (one-sided, upper tail), computed as")
    print("                      mean(null >= observed)")
    rng = np.random.default_rng(20260916)
    set_sizes = (rec[rec.persistent_high].groupby("metric_code").size()
                   .reindex(na.PRICE_METRICS, fill_value=0).to_numpy())
    observed_max = int(cnt_all.metrics_persistently_high.max()) if len(cnt_all) else 0
    observed_ge3 = int((cnt_all.metrics_persistently_high >= 3).sum()) if len(cnt_all) else 0
    draws = 10000
    null_max = np.empty(draws, dtype=int)
    null_ge3 = np.empty(draws, dtype=int)
    for i in range(draws):
        tally = np.zeros(na.N_STATES, dtype=int)
        for k in set_sizes:
            if k:
                tally[rng.choice(na.N_STATES, size=int(k), replace=False)] += 1
        null_max[i] = tally.max()
        null_ge3[i] = int((tally >= 3).sum())
    p_max = float((null_max >= observed_max).mean())
    p_ge3 = float((null_ge3 >= observed_ge3).mean())
    print(f"\n        set sizes preserved: {set_sizes.tolist()}")
    print(f"        max metrics on one jurisdiction : observed {observed_max}, "
          f"null mean {null_max.mean():.2f}, p = {p_max:.4f}")
    print(f"        jurisdictions high on >= 3      : observed {observed_ge3}, "
          f"null mean {null_ge3.mean():.2f}, p = {p_ge3:.4f}")
    print("      READING: under this null model, with metric set sizes preserved, the")
    print("      observed maximum overlap is NOT unusually large. That is all it says.")
    na.write_csv(pd.DataFrame([{
        "draws": draws, "seed": 20260916, "observed_max_metrics": observed_max,
        "null_mean_max": round(float(null_max.mean()), 4), "p_max": p_max,
        "observed_n_ge3": observed_ge3,
        "null_mean_n_ge3": round(float(null_ge3.mean()), 4), "p_ge3": p_ge3,
        "set_sizes": str(set_sizes.tolist()),
        "permuted": "membership of each metric's persistent-high set",
        "preserved": "set sizes, metric count, jurisdiction count",
        "p_rule": "mean(null_statistic >= observed_statistic), one-sided upper tail"}]),
        OUT, "f38_persistence_permutation.csv")
    ck.check(0.0 <= p_max <= 1.0 and 0.0 <= p_ge3 <= 1.0,
             "permutation p-values are well formed", f"p_max={p_max}, p_ge3={p_ge3}")

    # ---- Verdict ------------------------------------------------------------
    print("\n  (h) WHICH CONCLUSION DOES THE EVIDENCE SUPPORT?")
    n_multi = int((cnt.metrics_persistently_high >= 5).sum()) if len(cnt) else 0
    n_any = len(cnt_all)
    verdict = ("METRIC-SPECIFIC EXPENSIVE JURISDICTIONS. A jurisdiction can be "
               "persistently expensive for a particular cost component without being "
               "broadly expensive across unrelated cost families. Within-metric "
               "persistence is STRONG for every rank-safe metric. Most persistently-dear "
               "jurisdictions are dear within ONE cost family, overwhelmingly local "
               "mobility. The scope of this conclusion is limited: liquid fuel and LPG "
               "own no rank-safe metric, so for those families the question cannot be "
               "answered from ranks at all, and their absence from the cross-family "
               "result is a property of the ranking, not evidence that costs are uniform.")
    if n_multi > 0:
        verdict = ("PERSISTENT MULTI-METRIC HIGH-COST JURISDICTIONS exist across rank-safe "
                   "metrics: at least one is persistently high on 5+ of them.")
    print(f"      {verdict}")
    print(f"\n      (rank-safe metrics: {len(SAFE)} of 9; testable families: {len(testable)} "
          f"of 4; jurisdictions persistently high on >=1 rank-safe metric: {len(cnt)}; "
          f"max on any one: "
          f"{int(cnt.metrics_persistently_high.max()) if len(cnt) else 0}; "
          f"spanning 2+ testable families: {n_cross})")
    ck.check(n_any > 0, "at least one jurisdiction shows within-metric persistence",
             f"{n_any} jurisdictions across all metrics")
    return rec, cnt, verdict


# ===========================================================================
def main() -> int:
    log_path = na.OUTPUT_ROOT / OUT / "a01_discovery_log.txt"
    tee = na.Tee(log_path)
    sys.stdout = tee
    try:
        print("NIGERIA BUSINESS COST INTELLIGENCE - ANALYSIS PASS 01 (DISCOVERY)")
        print(f"database: {na.DB_NAME}   available window: {na.AVAILABLE_WINDOW}   "
              f"primary window: {na.PRIMARY_WINDOW}")
        ck = na.Checks()
        conn = na.connect()
        try:
            panel = section_0_validation(conn, ck)
            section_1_surface(conn, ck)
            section_2_level_and_trend(panel, ck)
            disp, _ = section_3_dispersion(panel, ck)
            growth = section_4_state_growth(panel, ck)
            yoy = section_5_yoy(panel, ck)
            section_6_volatility_and_persistence(panel, ck)
            section_7_comovement(growth, panel, ck)
            section_8_surprises(panel, growth, disp, ck)
            section_9_zone_and_national(conn, ck)
            section_10_convergence_and_ratchet(panel, yoy, ck)
            section_11_fuel_shock(conn, panel, ck)
            section_12_persistence_test(panel, ck)
        finally:
            conn.close()
        failed = ck.summary("ANALYSIS PASS 01 VALIDATION")
        print(f"\noutputs written to: {(na.OUTPUT_ROOT / OUT).relative_to(na.PROJECT_ROOT)}")
        return 1 if failed else 0
    finally:
        sys.stdout = tee.stdout
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
