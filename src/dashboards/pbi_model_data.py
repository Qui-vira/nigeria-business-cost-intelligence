"""Build the Power BI star-schema data layer from the committed extract and evidence.

WHY THIS READS CSVs AND NOT PostgreSQL
--------------------------------------
The dashboard specification (§1.5) requires that all four tools consume ONE identical
extract set, so that "one validated story" is a structural guarantee rather than a
promise. This module therefore reads `outputs/dashboards/extracts/ext_state_cost_panel.csv`
- the same extract the Excel workbook was built from - plus the committed evidence files
under `outputs/analysis/`. Nothing is recomputed from the database here, so a Power BI
figure cannot silently diverge from the published Excel figure.

CONSEQUENCE, STATED PLAINLY: the extract excludes the 1,258 CPI INDEX rows (9,435 panel
rows become 8,177). Rule G2 forbids comparing CPI index LEVELS between jurisdictions, and
the extract enforces that by omission. This module additionally carries
`comparable_across_jurisdictions` on `dim_metric` and the DAX measures honour it, so G2
stays enforced in the model even if index rows are ever reintroduced.

Outputs are written to `powerbi/data/` as UTF-8 CSV with LF endings. They are the only
thing the semantic model reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from analysis import nbci_analysis as na  # noqa: E402

EXTRACTS = ROOT / "outputs" / "dashboards" / "extracts"
EVID = ROOT / "outputs" / "analysis"
DATA = ROOT / "powerbi" / "data"

NORTH_ZONES = ("North West", "North East", "North Central")
LOCAL_MOBILITY = set(na.LOCAL_MOBILITY_METRICS)
INTERREGIONAL = set(na.INTERREGIONAL_TRANSPORT_METRICS)

# Expected shapes. A mismatch fails the build rather than producing a quiet wrong answer.
EXPECT_PANEL_ROWS = 8177
EXPECT_JURISDICTIONS = 37
EXPECT_METRICS = 13


# ---------------------------------------------------------------------------
# Dimensions and fact
# ---------------------------------------------------------------------------
def _panel() -> pd.DataFrame:
    p = pd.read_csv(EXTRACTS / "ext_state_cost_panel.csv")
    if len(p) != EXPECT_PANEL_ROWS:
        raise SystemExit(f"extract row count changed: {len(p)} != {EXPECT_PANEL_ROWS}")
    p["observation_month"] = pd.to_datetime(p.observation_month)
    return p


def build_tables() -> dict[str, pd.DataFrame]:
    panel = _panel()
    t: dict[str, pd.DataFrame] = {}

    # --- dim_jurisdiction -------------------------------------------------
    dim_j = (panel[["jurisdiction", "zone"]].drop_duplicates()
             .sort_values("jurisdiction").reset_index(drop=True))
    dim_j["country_half"] = dim_j.zone.map(
        lambda z: "North" if z in NORTH_ZONES else "South")
    dim_j["jurisdiction_type"] = dim_j.jurisdiction.map(
        lambda j: "Federal Capital Territory" if j == "Abuja" else "State")
    if len(dim_j) != EXPECT_JURISDICTIONS:
        raise SystemExit(f"jurisdictions: {len(dim_j)} != {EXPECT_JURISDICTIONS}")
    t["dim_jurisdiction"] = dim_j

    # --- dim_metric: the rule carrier ------------------------------------
    stable = set(pd.read_csv(EVID / "discovery" / "f40_rank_stability.csv")
                 .query("stable_for_persistent_ranking")["metric_code"])
    rows = []
    for m in sorted(panel.metric_code.unique()):
        sub = panel[panel.metric_code == m]
        is_index = m.endswith("_INDEX")
        is_price = m in na.PRICE_METRICS
        if is_index:
            note = ("INDEX LEVELS MUST NOT BE COMPARED BETWEEN JURISDICTIONS (G2). "
                    "Change rates are comparable.")
        elif m in INTERREGIONAL:
            note = "Inter-regional service - NOT local mobility (G7)."
        elif is_price and m not in stable:
            note = ("Order is unstable month to month - spread may be shown but no "
                    "jurisdiction may be named for a persistent decision (G9).")
        elif is_price:
            note = "Order persists - safe for rank-based comparison over time."
        else:
            note = "Change rate. Comparable across jurisdictions."
        rows.append({
            "metric_code": m,
            "metric": na.SHORT_LABEL.get(m, m),
            "cost_family": sub.family.iloc[0],
            "unit": sub.unit.iloc[0],
            "source_dataset": sub.source_dataset.iloc[0],
            "is_local_mobility": bool(sub.local_mobility.iloc[0]),
            "is_interregional": m in INTERREGIONAL,
            "rank_stable": m in stable,
            "comparable_across_jurisdictions": not is_index,
            "is_price_level": is_price,
            "series_start": sub.observation_month.min().strftime("%Y-%m-%d"),
            "series_end": sub.observation_month.max().strftime("%Y-%m-%d"),
            "usage_note": note,
        })
    dim_m = pd.DataFrame(rows)
    if len(dim_m) != EXPECT_METRICS:
        raise SystemExit(f"metrics: {len(dim_m)} != {EXPECT_METRICS}")
    t["dim_metric"] = dim_m

    # --- dim_date (month grain) ------------------------------------------
    months = pd.DataFrame({"date": sorted(panel.observation_month.unique())})
    months["year"] = months.date.dt.year
    months["month_number"] = months.date.dt.month
    months["month_label"] = months.date.dt.strftime("%b %Y")
    months["year_month"] = months.date.dt.strftime("%Y-%m")
    months["month_index"] = months.year * 12 + months.month_number
    pw = panel[panel.in_primary_release_window.astype(str).str.lower() == "true"]
    months["in_primary_window"] = months.date.between(
        pw.observation_month.min(), pw.observation_month.max())
    months["date"] = months.date.dt.strftime("%Y-%m-%d")
    t["dim_date"] = months

    # --- fact_cost --------------------------------------------------------
    fact = panel[["observation_month", "jurisdiction", "metric_code", "value",
                  "in_primary_release_window"]].copy()
    fact.columns = ["date", "jurisdiction", "metric_code", "value", "in_primary_window"]
    fact["date"] = fact.date.dt.strftime("%Y-%m-%d")
    fact["in_primary_window"] = fact.in_primary_window.astype(str).str.lower() == "true"
    t["fact_cost"] = fact

    return t


# ---------------------------------------------------------------------------
# Evidence reference tables - copied verbatim from committed evidence.
#
# GRAIN DISCIPLINE: ref_food_zone (ZONE, G3) and ref_nerc_band (DisCo, G4) are
# deliberately given NO relationship to dim_jurisdiction in the semantic model.
# The rule is enforced by the absence of a join, not by a convention someone must
# remember when building a visual.
# ---------------------------------------------------------------------------
REF_SOURCES = {
    "ref_trend_window":        "discovery/f01_trend_primary_window.csv",
    "ref_dispersion":          "discovery/f05_dispersion_summary.csv",
    "ref_food_zone":           "discovery/f22_food_zone_premium.csv",
    "ref_nerc_band":           "discovery/f25_nerc_band_cross_section.csv",
    "ref_north_south_gap":     "discovery/f26_north_south_fuel_gap.csv",
    "ref_north_south_member":  "discovery/f33_north_south_membership.csv",
    "ref_fare_ratchet":        "discovery/f29_fare_ratchet_summary.csv",
    "ref_shock":               "discovery/f31_shock_trough_to_latest.csv",
    "ref_rank_stability":      "discovery/f40_rank_stability.csv",
    "ref_named_gaps":          "discovery/v02_named_gaps.csv",
    "ref_coverage":            "discovery/s02_dataset_coverage.csv",
    "ref_mode_variance":       "verification/v2a_mode_variance_decomposition.csv",
    "ref_rank_verdict":        "verification/v4_rank_stability.csv",
    "ref_flag_level":          "decisions/d1_movement_flags.csv",
    "fact_extreme_flag":       "decisions/d2_extreme_flags_by_month.csv",
    "ref_selfgen":             "decisions/d3_selfgen_vs_reference_tariff.csv",
    "ref_breakeven":           "decisions/d4_selfgen_breakeven.csv",
    "ref_fare_vs_cpi":         "decisions/d6_fare_vs_cpi_summary.csv",
    "ref_exposure":            "decisions/d7_exposure_sensitivity.csv",
    "ref_location_value":      "decisions/d8_location_value_by_cost.csv",
    "ref_mobility_dear":       "decisions/d10_local_mobility_dear.csv",
    "ref_mobility_cheap":      "decisions/d11_local_mobility_cheap.csv",
    "ref_mobility_split":      "decisions/d12_split_positions.csv",
}


def build_reference() -> dict[str, pd.DataFrame]:
    out = {}
    for name, rel in REF_SOURCES.items():
        path = EVID / rel
        if not path.exists():
            raise SystemExit(f"missing evidence file: {path}")
        out[name] = pd.read_csv(path)
    return out


def write_all(tables: dict[str, pd.DataFrame]) -> list[tuple[str, int]]:
    DATA.mkdir(parents=True, exist_ok=True)
    written = []
    for name, df in tables.items():
        path = DATA / f"{name}.csv"
        df.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")
        written.append((name, len(df)))
    return written


def build_everything() -> dict[str, pd.DataFrame]:
    """The model's tables: star schema, committed evidence, and the explanation layer.

    `pbi_findings` carries the business-question content (findings, archetypes, scope
    framing); `pbi_narrative` carries the per-page band, the 15 rules and the methodology
    facts. Both feed BOTH dashboards, so Excel and Power BI cannot say different things.
    """
    import pbi_findings
    import pbi_narrative
    return {**build_tables(), **build_reference(),
            **pbi_narrative.build(), **pbi_findings.build()}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    all_tables = build_everything()
    for nm, n in write_all(all_tables):
        print(f"  {nm:26s} {n:>6,} rows")
    print(f"\n{len(all_tables)} tables written to {DATA}")
