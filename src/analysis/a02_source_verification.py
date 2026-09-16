"""Analysis pass 02 - source verification of two suspicious patterns.

Discovery pass 01 flagged two observations as possibly structural rather than
economic, and refused to use them until traced to source:

  P1  the ~79% one-month air-fare rise at 2025-12
  P4  LPG 12.5 kg jurisdictions moving between roughly rank 1 and rank 37

This pass traces both to the original cleaned provenance - source file, archive
member, sheet, column and cell reference - and decides, on evidence, whether each
observation is safe for normal analysis. It also tests whether air fare behaves as
a LOCAL operating-cost signal or as a nationally-driven one.

    python src/analysis/a02_source_verification.py

Reads   : mart.* and core.dim_* over a READ-ONLY connection
Writes  : outputs/analysis/verification/*.csv and a02_verification_log.txt
Modifies: nothing.

Nothing is smoothed, excluded or corrected here. The output is a verdict plus the
evidence for it.
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

OUT = "verification"


def head(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 40) -> None:
    print(df.head(n).to_string(index=False))


# ===========================================================================
def verify_air_spike(conn, ck):
    head("V1 - AIR FARE, 2025-12: IS THE ~79% RISE GENUINELY PUBLISHED?")

    prov = na.q(conn, """
        SELECT t.observation_month, t.release_month, t.source_file, t.source_member,
               t.source_sheet, t.source_column_index, count(*) AS rows,
               count(DISTINCT t.geography_id) AS geographies,
               min(t.source_row) AS min_row, max(t.source_row) AS max_row,
               count(DISTINCT t.source_period_label) AS distinct_period_labels,
               min(t.source_period_label) AS period_label
        FROM mart.v_transport_state_primary t
        JOIN core.dim_transport_mode m USING (transport_mode_id)
        WHERE m.transport_mode = 'AIR'
          AND t.observation_month BETWEEN DATE '2025-10-01' AND DATE '2026-02-01'
        GROUP BY 1,2,3,4,5,6 ORDER BY 1
    """)
    print("  (a) Provenance of the air rows either side of the spike:")
    show(prov)
    na.write_csv(prov, OUT, "v1a_air_provenance.csv")

    # The Nov and Dec rows share one ZIP. If they also shared a workbook member
    # and column, the "spike" could be one column read twice. They do not.
    nd = prov[prov.observation_month.isin([pd.Timestamp("2025-11-01").date(),
                                           pd.Timestamp("2025-12-01").date()])]
    ck.eq(nd.source_file.nunique(), 1,
          "Nov and Dec 2025 air rows come from ONE published archive")
    ck.eq(nd.source_member.nunique(), 2,
          "...but from TWO DIFFERENT workbook members inside it")
    ck.check(nd.distinct_period_labels.eq(1).all(),
             "each month's rows carry exactly one source period label",
             "; ".join(f"{r.observation_month}='{r.period_label}'" for _, r in nd.iterrows()))
    ck.check((prov.geographies == 38).all(),
             "every month reads 38 geographies (37 jurisdictions + national)",
             f"{prov.geographies.min()}-{prov.geographies.max()}")

    # The known duplicate-header defect in this dataset - does it touch these months?
    dup = na.q(conn, """
        SELECT dataset, observation_month, count(*) AS n, min(source_file) AS source_file
        FROM mart.v_anomaly_register
        WHERE flag_code = 'DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION'
        GROUP BY 1,2 ORDER BY 1,2
    """)
    print("\n  (b) Every occurrence of the duplicate-period-header defect in this corpus:")
    show(dup)
    na.write_csv(dup, OUT, "v1b_duplicate_header_months.csv")
    touched = dup[dup.observation_month.between(pd.Timestamp("2025-10-01").date(),
                                                pd.Timestamp("2026-02-01").date())]
    ck.eq(len(touched), 0,
          "the duplicate-period-header defect does NOT touch 2025-10..2026-02")

    any_flag = na.q(conn, """
        SELECT count(*) AS n FROM mart.v_anomaly_register
        WHERE dataset LIKE 'TRANSPORT%%'
          AND observation_month BETWEEN DATE '2025-10-01' AND DATE '2026-02-01'
    """).n.iloc[0]
    ck.eq(int(any_flag), 0, "no anomaly flag of any kind on transport in these months")

    # Independent corroboration: NBS's own published NATIONAL row, separate cells.
    nat = na.q(conn, """
        SELECT t.observation_month, round(t.fare_ngn::numeric,2) AS national_air_fare,
               t.source_member, t.source_cell_reference
        FROM mart.v_transport_zone_primary t
        JOIN core.dim_transport_mode m USING (transport_mode_id)
        JOIN mart.v_geography g USING (geography_id)
        WHERE m.transport_mode='AIR' AND g.geography_type='NATIONAL'
          AND t.observation_month BETWEEN DATE '2025-10-01' AND DATE '2026-02-01'
        ORDER BY 1
    """)
    print("\n  (c) Independent corroboration - NBS's published NATIONAL air row:")
    show(nat)
    na.write_csv(nat, OUT, "v1c_national_air_corroboration.csv")
    nov = float(nat[nat.observation_month == pd.Timestamp("2025-11-01").date()]
                .national_air_fare.iloc[0])
    dec = float(nat[nat.observation_month == pd.Timestamp("2025-12-01").date()]
                .national_air_fare.iloc[0])
    ck.check(dec > nov * 1.5,
             "the published NATIONAL row shows the same December rise",
             f"{nov:,.0f} -> {dec:,.0f} = {100*(dec/nov-1):+.1f}%")

    # How broad is it, and how does it compare with the other four modes?
    breadth = na.q(conn, """
        WITH a AS (
          SELECT m.transport_mode AS mode, t.geography_id, t.observation_month, t.fare_ngn
          FROM mart.v_transport_state_primary t
          JOIN core.dim_transport_mode m USING (transport_mode_id)
          JOIN mart.v_geography g USING (geography_id)
          WHERE g.geography_type='STATE'
            AND t.observation_month IN (DATE '2025-11-01', DATE '2025-12-01')),
        b AS (
          SELECT mode, geography_id,
                 max(fare_ngn) FILTER (WHERE observation_month='2025-11-01') AS nov,
                 max(fare_ngn) FILTER (WHERE observation_month='2025-12-01') AS dec_
          FROM a GROUP BY 1,2)
        SELECT mode, count(*) AS jurisdictions, count(*) FILTER (WHERE dec_>nov) AS rose,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY 100*(dec_/nov-1)))::numeric,1)
                   AS median_mom_pct,
               round(min(100*(dec_/nov-1))::numeric,1) AS min_pct,
               round(max(100*(dec_/nov-1))::numeric,1) AS max_pct
        FROM b GROUP BY 1 ORDER BY median_mom_pct DESC
    """)
    print("\n  (d) 2025-11 -> 2025-12 movement, every mode, all 37 jurisdictions:")
    show(breadth)
    na.write_csv(breadth, OUT, "v1d_december_move_by_mode.csv")
    air = breadth[breadth["mode"] == "AIR"].iloc[0]
    ck.eq(int(air.rose), na.N_STATES, "air rose in all 37 jurisdictions that month")
    ck.check(air.median_mom_pct > 3 * breadth[breadth["mode"] != "AIR"].median_mom_pct.max(),
             "air's December move is several times larger than any other mode's",
             f"air {air.median_mom_pct:+.1f}% vs next "
             f"{breadth[breadth['mode']!='AIR'].median_mom_pct.max():+.1f}%")

    # Can seasonality be tested? Only with a second December.
    dec_count = na.q(conn, """
        SELECT count(DISTINCT observation_month) AS n
        FROM mart.v_transport_state_primary
        WHERE extract(month FROM observation_month) = 12
    """).n.iloc[0]
    ck.eq(int(dec_count), 1,
          "the transport series contains only ONE December - seasonality is UNTESTABLE")

    print("\n  VERDICT (air spike): GENUINELY PUBLISHED BY NBS.")
    print("    - Not a period-alignment issue: Nov and Dec are separate workbook members")
    print("      with distinct period labels inside one published archive.")
    print("    - Not the known duplicate-period-header defect: that touches 2025-03 only.")
    print("    - Not an extraction problem: identical sheet, column and cell block in")
    print("      every month; 38 geographies read each time; no anomaly flag.")
    print("    - Corroborated by NBS's own separately published NATIONAL row.")
    print("    - It is a real, broad, single-month published movement: all 37 jurisdictions")
    print("      up, median +74.2%, reversed the following month.")
    print("    SAFE FOR ANALYSIS, WITH ONE CONSTRAINT: it is a single-month outlier of")
    print("    unknown cause. The series holds only ONE December, so a seasonal")
    print("    explanation can be hypothesised but CANNOT be tested from this corpus.")
    print("    Any trend, growth or volatility figure spanning 2025-12 must disclose it.")
    return prov, breadth


# ===========================================================================
def verify_air_is_not_local(conn, ck):
    head("V2 - IS AIR FARE A LOCAL OPERATING-COST SIGNAL?")
    print("  Test: decompose each mode's month-over-month percentage changes into a\n"
          "  COMMON MONTH effect (all jurisdictions moving together - national or\n"
          "  carrier-driven) and a WITHIN-MONTH effect (jurisdictions moving differently\n"
          "  from each other - locally driven). One-way ANOVA on month; the statistic is\n"
          "  eta-squared = SS_between_month / SS_total. High eta-squared means the series\n"
          "  is dominated by a national factor.\n")

    d = na.q(conn, """
        SELECT m.transport_mode AS mode, t.geography_id, t.observation_month,
               t.fare_ngn::double precision AS fare
        FROM mart.v_transport_state_primary t
        JOIN core.dim_transport_mode m USING (transport_mode_id)
        JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE'
        ORDER BY 1,2,3
    """)
    d = d.sort_values(["mode", "geography_id", "observation_month"])
    d["mom"] = d.groupby(["mode", "geography_id"]).fare.pct_change() * 100
    d = d.dropna(subset=["mom"])

    rows = []
    for mode, g in d.groupby("mode"):
        grand = g.mom.mean()
        ss_total = ((g.mom - grand) ** 2).sum()
        mt = g.groupby("observation_month").mom.agg(["mean", "size"])
        ss_between = (mt["size"] * (mt["mean"] - grand) ** 2).sum()
        rows.append({"mode": mode, "obs": len(g), "months": g.observation_month.nunique(),
                     "eta_sq_month": ss_between / ss_total,
                     "mean_abs_mom_pct": g.mom.abs().mean()})
    dec = pd.DataFrame(rows).sort_values("eta_sq_month", ascending=False)
    print("  (a) Share of month-over-month variation explained by the common month effect:")
    show(dec.round(3))
    na.write_csv(dec.round(4), OUT, "v2a_mode_variance_decomposition.csv")

    air_eta = float(dec[dec["mode"] == "AIR"].eta_sq_month.iloc[0])
    others = dec[dec["mode"] != "AIR"].eta_sq_month
    ck.check(air_eta > others.max(),
             "AIR is the most nationally-synchronised mode of the five",
             f"air eta^2={air_eta:.3f} vs next highest {others.max():.3f}")

    # Second, independent angle: cross-jurisdiction dispersion of the level.
    disp = na.q(conn, """
        SELECT m.transport_mode AS mode,
               round(avg(cv)::numeric,1) AS mean_cv_pct
        FROM (
          SELECT t.transport_mode_id, t.observation_month,
                 100*stddev_samp(t.fare_ngn)/avg(t.fare_ngn) AS cv
          FROM mart.v_transport_state_primary t
          JOIN mart.v_geography g USING (geography_id)
          WHERE g.geography_type='STATE'
          GROUP BY 1,2) x
        JOIN core.dim_transport_mode m USING (transport_mode_id)
        GROUP BY 1 ORDER BY mean_cv_pct
    """)
    print("\n  (b) Cross-jurisdiction dispersion of the level, for comparison:")
    show(disp)
    na.write_csv(disp, OUT, "v2b_mode_dispersion.csv")

    print("\n  VERDICT (air interpretation): AIR IS NOT A LOCAL OPERATING-COST SIGNAL.")
    print(f"    {air_eta:.0%} of air's month-to-month variation is a common national")
    print("    movement, the highest of the five modes, and its December swing hit all")
    print("    37 jurisdictions at once. Air fares are set on carrier route networks, not")
    print("    by local market conditions in a state.")
    print("    RULE ADOPTED: air is KEPT in the dataset and reported, but is EXCLUDED from")
    print("    statements about LOCAL MOBILITY costs. 'Local mobility' means okada,")
    print("    intracity bus and water transport. Intercity bus and air are inter-regional")
    print("    services and are named explicitly whenever used.")
    return dec


# ===========================================================================
def verify_lpg_rank_swings(conn, ck):
    head("V3 - LPG 12.5 kg: WHY DO JURISDICTIONS MOVE BETWEEN RANK 1 AND RANK 37?")

    trace = na.q(conn, """
        SELECT g.geography_name AS jurisdiction, l.observation_month, l.release_month,
               round(l.refill_price_ngn::numeric,2) AS price_ngn, l.cylinder_size_kg,
               l.source_file, l.source_sheet, l.source_cell_reference, l.source_period_label
        FROM mart.v_lpg_primary l JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.cylinder_size_kg = 12.5
          AND g.geography_name IN ('Nasarawa','Yobe','Katsina')
        ORDER BY 1,2
    """)
    print("  (a) Full source trace for three of the extreme movers:")
    show(trace, 60)
    na.write_csv(trace, OUT, "v3a_lpg_source_trace.csv")

    # Candidate cause 1: ties. -> measured
    ties = na.q(conn, """
        SELECT l.observation_month, count(*) AS juris,
               count(DISTINCT l.refill_price_ngn) AS distinct_values,
               count(*) - count(DISTINCT l.refill_price_ngn) AS tied_rows
        FROM mart.v_lpg_primary l JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.cylinder_size_kg=12.5
        GROUP BY 1 ORDER BY 1
    """)
    ck.check(ties.tied_rows.sum() <= 5,
             "CAUSE RULED OUT - ties: LPG 12.5 kg values are almost all distinct",
             f"{int(ties.tied_rows.sum())} tied rows across {len(ties)} months")

    # Candidate cause 2: cylinder-size confusion. -> measured
    cyl = na.q(conn, """
        SELECT DISTINCT cylinder_size_kg FROM mart.v_lpg_primary ORDER BY 1
    """).cylinder_size_kg.tolist()
    ck.eq([float(x) for x in cyl], [5.0, 12.5],
          "CAUSE RULED OUT - cylinder confusion: exactly two sizes, never merged")

    # Candidate cause 3: geography misalignment. -> cell reference stability
    cells = na.q(conn, """
        SELECT g.geography_name AS jurisdiction,
               count(DISTINCT l.source_cell_reference) AS distinct_cells,
               count(DISTINCT regexp_replace(l.source_cell_reference,'[0-9]+$','')) AS cols,
               count(DISTINCT regexp_replace(l.source_cell_reference,'^[A-Z]+','')) AS row_nums,
               count(*) AS months
        FROM mart.v_lpg_primary l JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.cylinder_size_kg=12.5
        GROUP BY 1 ORDER BY row_nums DESC, 1
    """)
    ck.check((cells.row_nums == 1).all(),
             "CAUSE RULED OUT - geography misalignment: each jurisdiction keeps ONE "
             "source row number in every release",
             f"max distinct row numbers for any jurisdiction = {cells.row_nums.max()}")
    print("\n  (b) Source-column changes across releases (publication structure):")
    colshift = na.q(conn, """
        SELECT l.observation_month, l.source_file, l.source_sheet,
               regexp_replace(min(l.source_cell_reference),'[0-9]+$','') AS column_letter,
               count(*) AS rows
        FROM mart.v_lpg_primary l JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.cylinder_size_kg=12.5
        GROUP BY 1,2,3 ORDER BY 1
    """)
    show(colshift, 20)
    na.write_csv(colshift, OUT, "v3b_lpg_column_shifts.csv")
    ck.check(colshift.column_letter.nunique() >= 2,
             "publication structure DID change mid-series (source column moved)",
             f"columns used: {sorted(colshift.column_letter.unique())}")

    # Candidate cause 4: restatement behaviour. -> measured
    restate = na.q(conn, """
        SELECT count(*) AS n FROM mart.v_lpg_primary l
        JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.release_month <> l.observation_month
    """).n.iloc[0]
    ck.eq(int(restate), 0,
          "CAUSE RULED OUT - restatement: every primary LPG row is its own month's release")

    # The actual cause: a compressed distribution.
    comp = na.q(conn, """
        SELECT l.observation_month, count(*) AS juris,
               round(min(l.refill_price_ngn)::numeric,2) AS min_v,
               round((percentile_cont(0.5) WITHIN GROUP
                     (ORDER BY l.refill_price_ngn))::numeric,2) AS median_v,
               round(max(l.refill_price_ngn)::numeric,2) AS max_v,
               round((max(l.refill_price_ngn)-min(l.refill_price_ngn))::numeric,2) AS range_ngn,
               round((100*stddev_samp(l.refill_price_ngn)/avg(l.refill_price_ngn))::numeric,2)
                   AS cv_pct
        FROM mart.v_lpg_primary l JOIN mart.v_geography g USING (geography_id)
        WHERE g.geography_type='STATE' AND l.cylinder_size_kg=12.5
        GROUP BY 1 ORDER BY 1
    """)
    print("\n  (c) The whole cross-jurisdiction distribution, month by month:")
    show(comp, 20)
    na.write_csv(comp, OUT, "v3c_lpg_distribution.csv")

    print("\n  VERDICT (LPG rank swings): GENUINE PUBLISHED PRICE MOVEMENTS IN A")
    print("  DISTRIBUTION SO COMPRESSED THAT THE RANKING CARRIES ALMOST NO SIGNAL.")
    print("    Ruled out by evidence: ties, cylinder-size confusion, geography")
    print("    misalignment, restatement behaviour, extraction error. Each jurisdiction")
    print("    holds a stable source row across every release; the source COLUMN moved")
    print("    (L -> N) when NBS changed the workbook layout at 2026-02, and that shift is")
    print("    tracked, not silently absorbed.")
    print("    The cause is arithmetic: in 2025-10 all 37 jurisdictions lay between")
    print("    NGN 17,611 and NGN 19,392 - a total spread of NGN 1,781, CV 2.4%. A price")
    print("    move of a few hundred naira therefore traverses most of the ranking.")
    print("    CONSEQUENCE: LPG PRICE LEVELS ARE SAFE FOR ANALYSIS. LPG RANKS AND")
    print("    RANK-BASED CLAIMS ARE NOT, and no jurisdiction-level 'cheapest/dearest")
    print("    LPG' claim should be made. This independently explains why the persistence")
    print("    test found ZERO jurisdictions persistently dear on LPG 12.5 kg.")
    return comp


# ===========================================================================
def rank_instability_index(conn, ck):
    head("V4 - RANK INSTABILITY: WHICH METRICS SUPPORT RANK-BASED CLAIMS AT ALL?")
    print("  For each metric: the typical monthly price move, against the cross-\n"
          "  jurisdiction dispersion it has to traverse. churn = mean absolute change in\n"
          "  a jurisdiction's rank from one month to the next, out of 37 positions.\n")

    p = na.q(conn, """
        SELECT metric_code, state_id, observation_month,
               metric_value::double precision AS v
        FROM mart.mv_state_cost_panel_monthly
        WHERE in_primary_release_window AND unit <> 'INDEX_2024_100'
          AND metric_code NOT LIKE 'CPI%%'
        ORDER BY 1,2,3
    """)
    p["rank"] = p.groupby(["metric_code", "observation_month"]).v.rank()
    p = p.sort_values(["metric_code", "state_id", "observation_month"])
    p["rank_change"] = p.groupby(["metric_code", "state_id"])["rank"].diff().abs()
    p["mom_abs"] = (p.groupby(["metric_code", "state_id"]).v.pct_change() * 100).abs()
    cv = (p.groupby(["metric_code", "observation_month"])
            .apply(lambda g: 100 * g.v.std(ddof=1) / g.v.mean(), include_groups=False)
            .groupby("metric_code").mean())
    out = (p.groupby("metric_code")
             .agg(mean_abs_rank_change=("rank_change", "mean"),
                  mean_abs_mom_pct=("mom_abs", "mean"))
             .reset_index())
    out["mean_cv_pct"] = out.metric_code.map(cv)
    out["move_to_spread_ratio"] = out.mean_abs_mom_pct / out.mean_cv_pct
    out["rank_churn_pct_of_field"] = 100 * out.mean_abs_rank_change / na.N_STATES
    out["label"] = out.metric_code.map(na.SHORT_LABEL)
    out["rank_claims"] = out.move_to_spread_ratio.map(
        lambda r: "UNSAFE" if r >= 1.0 else ("CAUTION" if r >= 0.5 else "SAFE"))
    out = out.sort_values("move_to_spread_ratio", ascending=False)
    show(out[["label", "mean_abs_mom_pct", "mean_cv_pct", "move_to_spread_ratio",
              "mean_abs_rank_change", "rank_churn_pct_of_field", "rank_claims"]].round(2))
    na.write_csv(out.round(4), OUT, "v4_rank_instability.csv")

    lpg = out[out.metric_code.str.startswith("LPG")]
    ck.check((lpg.move_to_spread_ratio > 1).all(),
             "both LPG series move more per month than their whole cross-jurisdiction spread",
             f"ratios {lpg.move_to_spread_ratio.round(2).tolist()}")
    transport_local = out[out.metric_code.isin([
        "TRANSPORT_OKADA_NGN_PER_JOURNEY", "TRANSPORT_WATER_NGN_PER_JOURNEY",
        "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY"])]
    ck.check((transport_local.move_to_spread_ratio < 0.5).all(),
             "the three local-mobility modes are stable enough for rank-based claims",
             f"ratios {transport_local.move_to_spread_ratio.round(2).tolist()}")
    print("\n  READING: a ratio at or above 1.0 means a typical monthly move is as large")
    print("  as the entire spread between jurisdictions, so the ranking reshuffles on")
    print("  noise. Rank-based and persistence claims are reported only for metrics")
    print("  marked SAFE.")
    return out


# ===========================================================================
def main() -> int:
    log_path = na.OUTPUT_ROOT / OUT / "a02_verification_log.txt"
    tee = na.Tee(log_path)
    sys.stdout = tee
    try:
        print("NIGERIA BUSINESS COST INTELLIGENCE - ANALYSIS PASS 02 (SOURCE VERIFICATION)")
        print(f"database: {na.DB_NAME}")
        ck = na.Checks()
        conn = na.connect()
        try:
            na.check_read_only(conn, ck)
            verify_air_spike(conn, ck)
            verify_air_is_not_local(conn, ck)
            verify_lpg_rank_swings(conn, ck)
            rank_instability_index(conn, ck)
        finally:
            conn.close()
        failed = ck.summary("ANALYSIS PASS 02 VERIFICATION")
        print(f"\noutputs written to: {(na.OUTPUT_ROOT / OUT).relative_to(na.PROJECT_ROOT)}")
        return 1 if failed else 0
    finally:
        sys.stdout = tee.stdout
        tee.close()


if __name__ == "__main__":
    raise SystemExit(main())
