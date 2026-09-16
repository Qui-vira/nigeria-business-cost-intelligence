"""Analysis pass 03 - inputs for business decisions.

Discovery (a01) established WHAT the data shows and verification (a02) established
which of it is safe to use. This pass computes only what a specific management
DECISION needs and that neither earlier pass produced. Everything else in the
Business Decision Analysis Report is reused from the committed evidence set.

Six new calculations, each tied to one decision:

  D1  Historical movement flags  - how large a monthly move has been by past
                                   standards. DESCRIPTIVE ONLY: ELEVATED = above
                                   p90, EXTREME = above p95. These are not action
                                   thresholds
  D2  Reference-tariff compare   - diesel fuel cost per kWh against a FIXED July
                                   2025 NERC reference tariff. Not a live tariff
                                   comparison: the two series end 10 months apart
  D3  Fare vs CPI indexation gap - did CPI track observed transport-fare growth,
                                   i.e. would a CPI-indexed allowance have lagged
  D4  Exposure sensitivity       - what a cost move does to total cost, per one
                                   percentage point of that cost's share. The
                                   business supplies its own share; no weights are
                                   invented here and nothing is aggregated
  D5  Jurisdiction spread in NGN - the money value of location, per cost. Each
                                   month's rank is a valid snapshot; jurisdictions
                                   are NAMED only where the order is STABLE enough
                                   for a persistent decision (a02 V4 heuristic)
  D6  Persistent local-mobility  - which jurisdictions are reliably dear or cheap
      positions                    for staff commute and last-mile, named, because
                                   these modes rank stably over time

    python src/analysis/a03_decision_inputs.py

Reads   : mart.* over a READ-ONLY connection
Writes  : outputs/analysis/decisions/*.csv and a03_decision_log.txt
Modifies: nothing.

NOT DONE HERE, deliberately: no composite index, no weighting of one cost against
another, no dashboards, and no PERSISTENT jurisdiction ranking on the five metrics
whose order is unstable month to month.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nbci_analysis as na  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)
pd.set_option("display.max_rows", 400)

OUT = "decisions"

# D2 ASSUMPTIONS - both are assumptions, not measurements, and both are labelled
# as such everywhere they appear.
#
# (1) GENERATOR EFFICIENCY. A small/medium diesel generator is ASSUMED to deliver
#     roughly 3.0-3.5 kWh per litre at load. The wider range 2.5-4.0 is carried
#     through the whole calculation rather than a point estimate, so the result can
#     be read at whatever efficiency a business actually measures.
# (2) REFERENCE TARIFF. The grid side is a FIXED BENCHMARK, not a live price:
#     the NERC Band A tariff from the July 2025 cross-section. It is the only band
#     with zero spread across all 11 DisCos, which is why it serves as the
#     reference. It may have changed since July 2025 - this corpus cannot say.
GENSET_KWH_PER_LITRE = [2.5, 3.0, 3.5, 4.0]
GENSET_CENTRAL = 3.0


def head(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 40) -> None:
    print(df.head(n).to_string(index=False))


def load_panel(conn, ck):
    panel = na.q(conn, """
        SELECT state_id, state_name, zone_name, observation_month, metric_code,
               metric_value::double precision AS metric_value, unit,
               in_primary_release_window
        FROM mart.mv_state_cost_panel_monthly
    """)
    ck.eq(len(panel), 9435, "panel unchanged since the committed milestone")
    ck.eq(panel.state_id.nunique(), na.N_STATES, "panel covers all 37 jurisdictions")
    return panel


# ===========================================================================
def d1_movement_flags(panel, ck):
    head("D1 - HISTORICAL MOVEMENT FLAGS: how large is this month by past standards?")
    print("  PURPOSE: to say how unusual a month is BY THE HISTORICAL STANDARD OF THIS\n"
          "  SERIES. Nothing more.\n\n"
          "  THESE ARE DESCRIPTIVE FLAGS, NOT BUSINESS ACTION THRESHOLDS:\n"
          "    ELEVATED = above the p90 of historical absolute monthly moves\n"
          "    EXTREME  = above the p95\n\n"
          "  A flag says a move is large relative to this series past. It does NOT\n"
          "  say a business should act, reprice or renegotiate. Whether a move\n"
          "  matters depends on that company cost exposure, its margin and its\n"
          "  ability to pass cost through - none of which is in this dataset. Turning\n"
          "  a flag into a trigger requires those three inputs first.\n\n"
          "  METHOD: distribution of each jurisdiction own month-over-month %\n"
          "  change, pooled across the 37 jurisdictions and the 14 month-pairs in the\n"
          "  primary window. Signed and absolute percentiles are both reported: a cost\n"
          "  FALLING hard is equally notable, so an absolute-only view would hide\n"
          "  half the events.\n")

    pw = panel[panel.in_primary_release_window
               & panel.metric_code.isin(na.PRICE_METRICS)].copy()
    pw = pw.sort_values(["state_id", "metric_code", "observation_month"])
    pw["mom"] = pw.groupby(["state_id", "metric_code"]).metric_value.pct_change() * 100
    d = pw.dropna(subset=["mom"])
    ck.eq(len(d), len(na.PRICE_METRICS) * na.N_STATES * (na.PRIMARY_WINDOW_MONTHS - 1),
          "month-over-month grid is complete (9 metrics x 37 x 14)")

    rows = []
    for m, g in d.groupby("metric_code"):
        a = g.mom.abs()
        rows.append({
            "metric_code": m, "label": na.SHORT_LABEL[m], "observations": len(g),
            "median_abs_pct": a.median(), "p75_abs_pct": a.quantile(.75),
            "elevated_p90_abs_pct": a.quantile(.90),
            "extreme_p95_abs_pct": a.quantile(.95),
            "worst_rise_pct": g.mom.max(), "worst_fall_pct": g.mom.min()})
    th = pd.DataFrame(rows).sort_values("extreme_p95_abs_pct", ascending=False)
    print("  Historical movement flags (|month-over-month %|), per cost:")
    show(th.round(2))
    na.write_csv(th.round(4), OUT, "d1_movement_flags.csv")
    ck.check((th.elevated_p90_abs_pct <= th.extreme_p95_abs_pct).all(),
             "the ELEVATED flag level never exceeds the EXTREME level for any cost")
    ck.check((th.observations == na.N_STATES * (na.PRIMARY_WINDOW_MONTHS - 1)).all(),
             "every flag level is built on the same 518 observations")

    # How often is each threshold crossed, and does it cluster in time?
    d = d.merge(th[["metric_code", "extreme_p95_abs_pct"]], on="metric_code")
    d["breach"] = d.mom.abs() >= d.extreme_p95_abs_pct
    by_month = (d[d.breach].groupby(["metric_code", "observation_month"])
                  .size().reset_index(name="jurisdictions_flagged_extreme"))
    worst = (by_month.sort_values("jurisdictions_flagged_extreme", ascending=False)
                     .head(12).copy())
    worst["label"] = worst.metric_code.map(na.SHORT_LABEL)
    print("\n  Months in which the EXTREME flag was raised in the most jurisdictions:")
    show(worst[["label", "observation_month", "jurisdictions_flagged_extreme"]], 12)
    na.write_csv(by_month, OUT, "d2_extreme_flags_by_month.csv")
    conc = (by_month.groupby("metric_code")
              .agg(months_with_any_extreme=("observation_month", "nunique"))
              .reset_index())
    conc["label"] = conc.metric_code.map(na.SHORT_LABEL)
    print("\n  EXTREME months are episodic, not spread evenly - months with any\n"
          "  EXTREME flag, out of the 14 month-pairs available:")
    show(conc[["label", "months_with_any_extreme"]]
         .sort_values("months_with_any_extreme"))
    ck.check((conc.months_with_any_extreme <= na.PRIMARY_WINDOW_MONTHS - 1).all(),
             "EXTREME-flag months never exceed the 14 available month-pairs")
    return th


# ===========================================================================
def d2_selfgen_vs_reference(conn, panel, ck):
    head("D2 - DIESEL SELF-GENERATION AGAINST A FIXED JULY 2025 REFERENCE TARIFF")
    print("  QUESTION: how does the fuel cost of self-generation compare with a FIXED\n"
          "  GRID REFERENCE TARIFF, and how has that comparison moved as diesel rose?\n\n"
          "  THE TWO SIDES DO NOT COVER THE SAME PERIOD. Diesel runs monthly to\n"
          "  2026-05. The NERC tariff is a SINGLE JULY 2025 CROSS-SECTION and is held\n"
          "  FIXED throughout. This is therefore a comparison against a REFERENCE\n"
          "  BENCHMARK, not a like-for-like comparison of two current prices. If the\n"
          "  tariff has risen since July 2025, the true multiples are smaller than\n"
          "  those shown. This corpus cannot say whether it has.\n")
    print("  ASSUMPTION 1 - GENERATOR EFFICIENCY (assumed, not measured): a diesel\n"
          "  generator is assumed to deliver 3.0-3.5 kWh per litre at load. The range\n"
          "  2.5-4.0 is carried through so the result can be read at any efficiency.\n"
          "  A business MUST substitute its own measured burn per hour divided by\n"
          "  load before using this.\n\n"
          "  ASSUMPTION 2 - REFERENCE TARIFF (fixed benchmark, July 2025): the grid\n"
          "  side is the NERC Band A tariff as published in the July 2025 order. It is\n"
          "  held constant across all months shown.\n\n"
          "  Neither side includes the generator itself, servicing, oil or downtime,\n"
          "  nor grid connection charges, fixed charges or outage losses.\n")
    print("  GRAIN WARNING: diesel is jurisdiction-grain, NERC tariffs are DisCo-grain\n"
          "  and DisCos are not jurisdictions. This is NOT a geographic join. It\n"
          "  compares a cross-jurisdiction median diesel cost against a national band\n"
          "  benchmark. Band A is used as the reference precisely because it is the\n"
          "  one band with ZERO spread across all 11 DisCos (a01 F8), so no geographic\n"
          "  assignment is needed for it.\n")

    # ::double precision - psycopg returns SQL numeric as Decimal, which will not
    # multiply with the float efficiency constants further down.
    bands = na.q(conn, """
        SELECT service_band,
               round((percentile_cont(0.5) WITHIN GROUP
                     (ORDER BY tariff_ngn_per_kwh))::numeric,2)::double precision
                   AS tariff_ngn_per_kwh,
               count(DISTINCT disco_code) AS discos,
               round((max(tariff_ngn_per_kwh)-min(tariff_ngn_per_kwh))::numeric,2)
                   ::double precision AS spread
        FROM mart.v_tariff_band_cross_section
        WHERE is_current_period AND tariff_ngn_per_kwh IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
    """)
    ck.eq(len(bands), 6, "all six NERC service bands present")
    band_a = float(bands[bands.service_band == "A"].tariff_ngn_per_kwh.iloc[0])
    ck.eq(float(bands[bands.service_band == "A"].spread.iloc[0]), 0.0,
          "Band A has zero spread across DisCos, so the comparison needs no geography")

    dz = panel[panel.metric_code == "DIESEL_PRICE_NGN_PER_LITRE"]
    med = (dz.groupby("observation_month").metric_value.median()
             .reset_index(name="diesel_ngn_per_litre"))
    key_months = [pd.Timestamp("2025-09-01").date(), pd.Timestamp("2026-04-01").date(),
                  pd.Timestamp("2026-05-01").date()]
    rows = []
    for _, r in med[med.observation_month.isin(key_months)].iterrows():
        for eff in GENSET_KWH_PER_LITRE:
            cost = r.diesel_ngn_per_litre / eff
            rows.append({"observation_month": r.observation_month,
                         "diesel_ngn_per_litre": round(r.diesel_ngn_per_litre, 2),
                         "genset_kwh_per_litre": eff,
                         "self_gen_ngn_per_kwh": round(cost, 2),
                         "band_a_reference_ngn_per_kwh": band_a,
                         "reference_period": "NERC July 2025 cross-section",
                         "multiple_of_reference_tariff": round(cost / band_a, 2)})
    gen = pd.DataFrame(rows)
    print(f"  Diesel fuel cost per kWh against the FIXED July 2025 Band A reference"
          f" tariff of NGN {band_a:,.2f}/kWh." )
    print("  FUEL ONLY - excludes the generator, servicing, oil and downtime.")
    show(gen, 20)
    na.write_csv(gen, OUT, "d3_selfgen_vs_reference_tariff.csv")

    # Does grid ever lose? Break-even diesel price at each band.
    be = bands.copy()
    be["reference_period"] = "NERC July 2025 cross-section"
    be["breakeven_diesel_ngn_per_litre_at_3kwh"] = (be.tariff_ngn_per_kwh
                                                    * GENSET_CENTRAL).round(2)
    lowest_diesel = float(med.diesel_ngn_per_litre.min())
    be["selfgen_ever_below_reference"] = (
        be.breakeven_diesel_ngn_per_litre_at_3kwh > lowest_diesel)
    print(f"\n  Break-even diesel price at {GENSET_CENTRAL} kWh/litre - below this the\n"
          f"  generator would win. Cheapest diesel ever observed in the series is\n"
          f"  NGN {lowest_diesel:,.2f}/litre ({med.loc[med.diesel_ngn_per_litre.idxmin(),
                                                       'observation_month']}):")
    show(be)
    na.write_csv(be, OUT, "d4_selfgen_breakeven.csv")
    ck.check(not be.selfgen_ever_below_reference.any(),
             "against the July 2025 reference tariff, and at no band, does diesel "
             "self-generation fall below the reference at any month in the series",
             f"cheapest diesel {lowest_diesel:,.0f} vs highest break-even "
             f"{be.breakeven_diesel_ngn_per_litre_at_3kwh.max():,.0f}")

    first, last = med.iloc[0], med.iloc[-1]
    ck.check(last.diesel_ngn_per_litre > first.diesel_ngn_per_litre,
             "self-generation cost rose over the series while the reference tariff "
             "is held fixed at its July 2025 value",
             f"{first.diesel_ngn_per_litre:,.0f} -> {last.diesel_ngn_per_litre:,.0f} NGN/l")
    return gen, be


# ===========================================================================
def d3_fare_vs_cpi(panel, ck):
    head("D3 - DID CPI TRACK OBSERVED TRANSPORT-FARE GROWTH?")
    print("  QUESTION: transport allowances are commonly uprated by headline inflation.\n"
          "  Over the measured months, did CPI growth track observed fare growth?\n\n"
          "  WHAT THIS MEASURES: the gap between two published growth rates. A\n"
          "  positive gap means an allowance indexed ONLY to CPI would have LAGGED\n"
          "  observed fare growth, reducing the commuting purchasing power that\n"
          "  allowance provides. It is NOT a statement about total real pay, which\n"
          "  depends on salary, other allowances and actual commuting patterns that\n"
          "  this dataset does not contain.\n\n"
          "  METHOD: per jurisdiction, year-on-year growth in okada and intracity bus\n"
          "  fares against year-on-year CPI all-items, in the months where BOTH exist.\n")

    p = panel.copy()
    p["observation_month"] = pd.to_datetime(p.observation_month)
    fares = ["TRANSPORT_OKADA_NGN_PER_JOURNEY", "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY"]
    f = p[p.metric_code.isin(fares)]
    prev = f.copy()
    prev["observation_month"] = prev.observation_month + pd.DateOffset(months=12)
    prev = prev.rename(columns={"metric_value": "v_year_ago"})
    fy = f.merge(prev[["state_id", "metric_code", "observation_month", "v_year_ago"]],
                 on=["state_id", "metric_code", "observation_month"], how="inner")
    fy["fare_yoy_pct"] = 100 * (fy.metric_value / fy.v_year_ago - 1)

    cpi = p[p.metric_code == "CPI_ALL_ITEMS_YOY_PCT"][
        ["state_id", "observation_month", "metric_value"]].rename(
        columns={"metric_value": "cpi_yoy_pct"})

    fare_months = set(fy.observation_month.unique())
    cpi_months = set(cpi.observation_month.unique())
    overlap = sorted(fare_months & cpi_months)
    missing = sorted(fare_months - cpi_months)
    print(f"  fare YoY months available : {len(fare_months)} "
          f"({min(fare_months).date()} .. {max(fare_months).date()})")
    print(f"  months usable (CPI too)   : {len(overlap)}")
    print(f"  fare months with NO CPI   : {[str(m.date()) for m in missing]}"
          "  <- the 2026-02 CPI YoY hole (a01 S4). Excluded, not imputed.\n")
    ck.check(pd.Timestamp("2026-02-01") in missing,
             "the known 2026-02 CPI YoY gap is excluded explicitly, not silently",
             f"{len(missing)} month(s) dropped for absent CPI")

    j = fy.merge(cpi, on=["state_id", "observation_month"], how="inner")
    j["gap_pp"] = j.fare_yoy_pct - j.cpi_yoy_pct
    ck.eq(len(j), len(fares) * na.N_STATES * len(overlap),
          "fare-vs-CPI grid is complete over the usable months")

    summ = (j.groupby("metric_code")
              .agg(observations=("gap_pp", "size"),
                   jurisdictions=("state_id", "nunique"),
                   months=("observation_month", "nunique"),
                   median_fare_yoy=("fare_yoy_pct", "median"),
                   median_cpi_yoy=("cpi_yoy_pct", "median"),
                   median_gap_pp=("gap_pp", "median"),
                   share_fare_above_cpi=("gap_pp", lambda s: (s > 0).mean()))
              .reset_index())
    summ["label"] = summ.metric_code.map(na.SHORT_LABEL)
    print("  Fare growth vs CPI growth, matched by jurisdiction and month:")
    show(summ[["label", "observations", "jurisdictions", "months", "median_fare_yoy",
               "median_cpi_yoy", "median_gap_pp", "share_fare_above_cpi"]].round(2))
    na.write_csv(j.round(4), OUT, "d5_fare_vs_cpi_detail.csv")
    na.write_csv(summ.round(4), OUT, "d6_fare_vs_cpi_summary.csv")
    print("\n      READ AS: a CPI-indexed allowance would have lagged observed fare\n"
          "      growth by the median gap shown, reducing commuting purchasing power.\n"
          "      It is not a measure of real pay.")
    ck.check((summ.median_gap_pp > 0).all(),
             "in both modes the median fare grew faster than CPI",
             f"gaps {summ.median_gap_pp.round(1).tolist()} pp")
    ck.check((summ.share_fare_above_cpi > 0.8).all(),
             "fare growth exceeded CPI growth in the large majority of observations",
             f"shares {summ.share_fare_above_cpi.round(3).tolist()}")
    return summ


# ===========================================================================
def d4_exposure_sensitivity(panel, ck):
    head("D4 - EXPOSURE SENSITIVITY: what a cost move does per 1pp of cost share")
    print("  DECISION: how much of a total-cost problem is each of these movements?\n"
          "  That depends on how much of YOUR cost base the item is - which is company\n"
          "  data we do not hold. So the multiplier is published instead of a total.\n"
          "  A business multiplies the figure by its own cost share.\n"
          "  This is arithmetic, not an index: nothing is normalised, weighted or\n"
          "  added across costs, and the shares are supplied by the reader.\n")

    p = panel[panel.metric_code.isin(na.PRICE_METRICS)]
    windows = {
        "PRIMARY_WINDOW_2025_02_to_2026_04": (pd.Timestamp("2025-02-01").date(),
                                              pd.Timestamp("2026-04-01").date()),
        "TROUGH_TO_LATEST_2025_09_to_2026_05": (pd.Timestamp("2025-09-01").date(),
                                                pd.Timestamp("2026-05-01").date()),
    }
    rows = []
    for wname, (a, b) in windows.items():
        for m, g in p.groupby("metric_code"):
            ga = g[g.observation_month == a]
            gb = g[g.observation_month == b]
            if ga.empty or gb.empty:
                rows.append({"window": wname, "metric_code": m,
                             "label": na.SHORT_LABEL[m], "jurisdictions": 0,
                             "median_pct_change": None,
                             "total_cost_impact_pp_per_1pp_share": None,
                             "note": "series does not cover this window"})
                continue
            j = ga[["state_id", "metric_value"]].merge(
                gb[["state_id", "metric_value"]], on="state_id", suffixes=("_a", "_b"))
            pct = (100 * (j.metric_value_b / j.metric_value_a - 1)).median()
            rows.append({"window": wname, "metric_code": m, "label": na.SHORT_LABEL[m],
                         "jurisdictions": len(j), "median_pct_change": round(pct, 2),
                         "total_cost_impact_pp_per_1pp_share": round(pct / 100, 4),
                         "note": ""})
    sens = pd.DataFrame(rows)
    print("  Read as: a cost that is X% of your cost base and rose P% adds\n"
          "  X * (P/100) percentage points to total cost.\n")
    show(sens.sort_values(["window", "median_pct_change"], ascending=[True, False]), 30)
    na.write_csv(sens, OUT, "d7_exposure_sensitivity.csv")

    covered = sens[sens.jurisdictions > 0]
    ck.check((covered.jurisdictions == na.N_STATES).all(),
             "every covered sensitivity figure uses all 37 jurisdictions")
    lpg_gap = sens[(sens.window.str.startswith("TROUGH"))
                   & (sens.metric_code.str.startswith("LPG"))]
    ck.eq(int(lpg_gap.jurisdictions.sum()), 0,
          "LPG is correctly absent from the trough-to-latest window (ends 2026-04)")

    # A worked illustration, with the share supplied as an explicit example.
    diesel = sens[(sens.metric_code == "DIESEL_PRICE_NGN_PER_LITRE")
                  & sens.window.str.startswith("TROUGH")].iloc[0]
    print(f"\n  ILLUSTRATION (the share is an example, not a finding):")
    for share in [5, 15, 30]:
        print(f"    diesel at {share:>2}% of cost base, +{diesel.median_pct_change:.1f}% "
              f"-> +{share * diesel.median_pct_change / 100:.1f} pp on total cost")
    return sens


# ===========================================================================
def d5_location_value(panel, ck):
    head("D5 - THE MONEY VALUE OF LOCATION, PER COST")
    print("  DECISION: is there enough difference between jurisdictions for location to\n"
          "  be worth acting on for this cost - and if so, how much money is it?\n")
    print("  RANK-STABILITY HEURISTIC ENFORCED (a02 V4). Every month ranking below is a\n"
          "  VALID SNAPSHOT of that month. For the five metrics whose order reshuffles\n"
          "  on ordinary monthly movement, the SPREAD is reported but no jurisdiction\n"
          "  is NAMED - not because the value is doubtful, but because the name would\n"
          "  not survive to the next month and so cannot anchor a PERSISTENT location\n"
          "  decision. This is a project decision-use heuristic, not a data-quality\n"
          "  verdict.\n")

    last = panel[panel.in_primary_release_window].observation_month.max()
    lm = panel[(panel.observation_month == last)
               & panel.metric_code.isin(na.PRICE_METRICS)]
    safe = set(pd.read_csv(na.OUTPUT_ROOT.parent / "analysis" / "discovery"
                           / "f40_rank_stability.csv")
               .query("stable_for_persistent_ranking")["metric_code"])
    ck.eq(len(safe), 4, "rank-stable metric list loaded from the a01 evidence")

    rows = []
    for m, g in lm.groupby("metric_code"):
        lo, hi = g.metric_value.min(), g.metric_value.max()
        is_safe = m in safe
        rows.append({
            "metric_code": m, "label": na.SHORT_LABEL[m], "month": last,
            "jurisdictions": len(g),
            "cheapest_ngn": round(lo, 2), "dearest_ngn": round(hi, 2),
            "spread_ngn": round(hi - lo, 2), "dearest_over_cheapest": round(hi / lo, 2),
            "stable_for_persistent_ranking": is_safe,
            "cheapest_jurisdiction": (g.loc[g.metric_value.idxmin(), "state_name"]
                                      if is_safe
                                      else "NOT NAMED - order unstable over time"),
            "dearest_jurisdiction": (g.loc[g.metric_value.idxmax(), "state_name"]
                                     if is_safe
                                     else "NOT NAMED - order unstable over time")})
    sp = pd.DataFrame(rows).sort_values("dearest_over_cheapest", ascending=False)
    show(sp, 12)
    na.write_csv(sp, OUT, "d8_location_value_by_cost.csv")
    UNSTABLE_LABEL = "NOT NAMED - order unstable over time"
    named = sp[sp.cheapest_jurisdiction != UNSTABLE_LABEL]
    ck.eq(len(named), 4, "exactly the four rank-stable metrics name a jurisdiction")
    ck.check((sp[~sp.stable_for_persistent_ranking].cheapest_jurisdiction
              == UNSTABLE_LABEL).all(),
             "no rank-unstable metric names a cheapest or dearest jurisdiction")
    return sp


# ===========================================================================
def d6_persistent_local_mobility(panel, ck):
    head("D6 - PERSISTENT LOCAL-MOBILITY POSITIONS (staff commute, last mile)")
    print("  DECISION: for a business whose costs turn on people and goods moving\n"
          "  locally - office siting, rider pay, delivery-fee setting - which\n"
          "  jurisdictions are reliably dear, and which reliably cheap?\n")
    print("  These three metrics are RANK-STABLE and LOCAL (a02 V2, V4), so naming\n"
          "  jurisdictions here is defensible. Air and intercity bus are inter-regional\n"
          "  and are deliberately excluded from this view.\n")

    lm = na.LOCAL_MOBILITY_METRICS
    pw = panel[panel.in_primary_release_window & panel.metric_code.isin(lm)].copy()
    ck.eq(len(pw), len(lm) * na.N_STATES * na.PRIMARY_WINDOW_MONTHS,
          "local-mobility grid is complete (3 metrics x 37 x 15)")
    pw["pr"] = pw.groupby(["metric_code", "observation_month"]).metric_value.rank(
        pct=True, method=na.RANK_METHOD)
    pw["high"] = pw.pr > na.HIGH_COST_QUANTILE
    pw["low"] = pw.pr <= na.LOW_COST_QUANTILE

    rec = (pw.groupby(["state_id", "state_name", "zone_name", "metric_code"])
             .agg(months=("high", "size"), months_high=("high", "sum"),
                  months_low=("low", "sum"))
             .reset_index())
    rec["share_high"] = rec.months_high / rec.months
    rec["share_low"] = rec.months_low / rec.months
    rec["persistent_high"] = rec.share_high >= na.PERSISTENCE_THRESHOLD
    rec["persistent_low"] = rec.share_low >= na.PERSISTENCE_THRESHOLD

    def roll(flag, name):
        t = (rec[rec[flag]].groupby(["state_name", "zone_name"])
               .agg(**{name: ("metric_code", "count"),
                       "modes": ("metric_code", lambda s: "; ".join(
                           sorted(na.SHORT_LABEL[x] for x in s)))})
               .reset_index().sort_values(name, ascending=False))
        return t

    dear, cheap = roll("persistent_high", "modes_dear"), roll("persistent_low", "modes_cheap")
    print(f"  Persistently DEAR on local mobility (>= {na.PERSISTENCE_THRESHOLD:.0%} of "
          f"{na.PRIMARY_WINDOW_MONTHS} months):")
    show(dear, 20)
    print(f"\n  Persistently CHEAP on local mobility:")
    show(cheap, 20)
    na.write_csv(rec.round(4), OUT, "d9_local_mobility_persistence.csv")
    na.write_csv(dear, OUT, "d10_local_mobility_dear.csv")
    na.write_csv(cheap, OUT, "d11_local_mobility_cheap.csv")

    # A jurisdiction CAN be dear on one mode and cheap on another - that is not a
    # contradiction, it is the same "name the cost" point one level finer. What
    # WOULD be a logic error is being both on the SAME mode.
    same_mode = rec[rec.persistent_high & rec.persistent_low]
    ck.eq(len(same_mode), 0,
          "no jurisdiction is persistently dear AND cheap on the same mode")
    both = sorted(set(dear.state_name) & set(cheap.state_name))
    ck.check(True, "split positions measured (dear on one mode, cheap on another)",
             f"{len(both)} jurisdictions: {', '.join(both) if both else 'none'}")
    if both:
        print(f"\n  SPLIT POSITIONS - dear on one local mode, cheap on another:")
        for s in both:
            d_modes = dear[dear.state_name == s].modes.iloc[0]
            c_modes = cheap[cheap.state_name == s].modes.iloc[0]
            print(f"    {s:<14} dear: {d_modes:<52} cheap: {c_modes}")
        print("    Even inside local mobility, 'expensive' has to name the mode.")
        na.write_csv(pd.DataFrame({"state_name": both}), OUT, "d12_split_positions.csv")
    ck.check(len(dear) > 0 and len(cheap) > 0,
             "the persistence view returns usable lists at both ends",
             f"{len(dear)} dear, {len(cheap)} cheap")
    all3 = dear[dear.modes_dear == 3]
    print(f"\n  Dear on ALL THREE local modes: "
          f"{', '.join(all3.state_name) if len(all3) else 'none'}")
    return dear, cheap


# ===========================================================================
def main() -> int:
    log_path = na.OUTPUT_ROOT / OUT / "a03_decision_log.txt"
    tee = na.Tee(log_path)
    sys.stdout = tee
    try:
        print("NIGERIA BUSINESS COST INTELLIGENCE - ANALYSIS PASS 03 (DECISION INPUTS)")
        print(f"database: {na.DB_NAME}   primary window: {na.PRIMARY_WINDOW}")
        ck = na.Checks()
        conn = na.connect()
        try:
            na.check_read_only(conn, ck)
            na.check_windows_match_database(conn, ck)
            panel = load_panel(conn, ck)
            d1_movement_flags(panel, ck)
            d2_selfgen_vs_reference(conn, panel, ck)
            d3_fare_vs_cpi(panel, ck)
            d4_exposure_sensitivity(panel, ck)
            d5_location_value(panel, ck)
            d6_persistent_local_mobility(panel, ck)
        finally:
            conn.close()
        failed = ck.summary("ANALYSIS PASS 03 VALIDATION")
        print(f"\noutputs written to: {(na.OUTPUT_ROOT / OUT).relative_to(na.PROJECT_ROOT)}")
        return 1 if failed else 0
    finally:
        sys.stdout = tee.stdout
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
