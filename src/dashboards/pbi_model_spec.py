"""Semantic model specification: tables, columns, relationships and DAX measures.

This module emits a JSON description of the model. `pbi_build_model.ps1` reads that JSON,
constructs real Tabular Object Model (TOM) objects and serialises them with Microsoft's own
`TmdlSerializer`. Nothing here hand-writes TMDL text, so the on-disk format is whatever the
installed Power BI Desktop build itself produces rather than a guess at the format.

HOW THE ANALYSIS RULES ARE ENFORCED STRUCTURALLY
------------------------------------------------
G2  `[Median Value]` returns BLANK whenever a metric marked
    `comparable_across_jurisdictions = FALSE` is in filter context, so a CPI index level
    cannot be compared across jurisdictions even if such rows were reintroduced.
G3  `ref_food_zone` is given NO relationship to `dim_jurisdiction`. Food is zone grain, and
    the join that would let someone break the rule does not exist.
G4  `ref_nerc_band` is given NO relationship to `dim_jurisdiction` for the same reason -
    DisCo territories are not jurisdictions.
G9  `[Dearest Jurisdiction]` / `[Cheapest Jurisdiction]` return
    "Not named - order unstable over time" unless `dim_metric[rank_stable]` is TRUE.
G11 `[Value YoY %]` returns BLANK when no row exists 12 months earlier, so a CPI year-on-year
    line breaks at 2026-02 instead of bridging the gap.
G15 Every median measure is named and described as a median of 37 jurisdictions, never a
    national average.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PBI = ROOT / "powerbi"
DATA = PBI / "data"

MODEL_NAME = "NBCI_Cost_Dashboard"

# Verified against the running workspace engine (17.0.83.18): its own blank model is 1606,
# and SupportedCompatibilityLevels has no 1610. See build_spec() for the full note.
COMPATIBILITY_LEVEL = 1606

# ---------------------------------------------------------------------------
# pandas dtype -> TOM DataType
# ---------------------------------------------------------------------------
DATE_COLUMNS = {"date", "observation_month", "month", "missing_month",
                "first_month", "last_month", "trough_month", "peak_month",
                "from_month", "to_month", "series_start", "series_end"}


def tom_type(series: pd.Series, col: str) -> str:
    if col in DATE_COLUMNS:
        return "DateTime"
    if pd.api.types.is_bool_dtype(series):
        return "Boolean"
    if pd.api.types.is_integer_dtype(series):
        return "Int64"
    if pd.api.types.is_float_dtype(series):
        return "Double"
    return "String"


def m_type(tom: str) -> str:
    return {"DateTime": "type date", "Boolean": "type logical",
            "Int64": "Int64.Type", "Double": "type number"}.get(tom, "type text")


def m_expression(table: str, cols: list[dict]) -> str:
    """Power Query that reads one CSV from the DataFolder parameter.

    The culture is pinned to "en-GB" on TransformColumnTypes rather than left to the
    model's sourceQueryCulture, which Power BI Desktop sets from the machine locale. A
    model whose numbers parse differently on another machine is not reproducible.
    """
    casts = ", ".join(f'{{"{c["name"]}", {m_type(c["dataType"])}}}' for c in cols)
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), '
        "[Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n"
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n"
        f'    Typed = Table.TransformColumnTypes(Promoted, {{{casts}}}, "en-GB")\n'
        "in\n"
        "    Typed"
    )


# ---------------------------------------------------------------------------
# Column presentation: format strings, hidden columns, descriptions.
# ---------------------------------------------------------------------------
FORMAT_BY_NAME = {
    "value": "#,0.00", "median_value": "#,0.00", "min_value": "#,0.00",
    "max_value": "#,0.00", "spread": "#,0.00", "spread_ngn": "#,0.00",
    "cheapest_ngn": "#,0.00", "dearest_ngn": "#,0.00",
    "dearest_over_cheapest": "0.00\\x", "pct_change": "#,0.00\\%",
    "median_pct": "#,0.00\\%", "min_pct": "#,0.00\\%", "max_pct": "#,0.00\\%",
    "trough_to_last_pct": "#,0.00\\%", "share_fare_rose_pct": "#,0.0\\%",
    "north_premium_pct": "#,0.00\\%", "mean_premium_pct_vs_national": "#,0.00\\%",
    "median_premium_pct": "#,0.00\\%", "elevated_p90_abs_pct": "#,0.00\\%",
    "extreme_p95_abs_pct": "#,0.00\\%", "median_abs_pct": "#,0.00\\%",
    "p75_abs_pct": "#,0.00\\%", "worst_rise_pct": "#,0.00\\%",
    "worst_fall_pct": "#,0.00\\%", "multiple_of_reference_tariff": "0.00\\x",
    "self_gen_ngn_per_kwh": "#,0.00", "band_a_reference_ngn_per_kwh": "#,0.00",
    "breakeven_diesel_ngn_per_litre_at_3kwh": "#,0.00",
    "total_cost_impact_pp_per_1pp_share": "0.0000",
    "median_tariff": "#,0.00", "tariff_ngn_per_kwh": "#,0.00",
    "date": "yyyy-mm-dd", "observation_month": "yyyy-mm-dd",
}

# Numeric columns that are categories, not measures: generator efficiency is a legend
# with four discrete values (2.5 / 3.0 / 3.5 / 4.0 kWh per litre), not something to sum.
NO_SUMMARIZE = {"genset_kwh_per_litre", "year", "month_number", "month_index"}

# Columns hidden from the report field list: surrogate/technical only.
HIDDEN_COLUMNS = {
    ("fact_cost", "value"),          # forced through [Median Value] so G2 cannot be bypassed
    ("dim_date", "month_index"),
    ("dim_date", "month_number"),
}

COLUMN_DESCRIPTIONS = {
    ("fact_cost", "value"): (
        "HIDDEN DELIBERATELY. Read this through [Median Value] or [Latest Median Value]. "
        "Exposing the raw column would allow a CPI index level to be averaged across "
        "jurisdictions, which rule G2 forbids."),
    ("dim_metric", "rank_stable"): (
        "TRUE only for water, okada, intracity bus and intercity bus. For the other five "
        "price metrics each single month's ranking is a valid snapshot, but the order does "
        "not hold from month to month, so no jurisdiction may be named as the dearest or the "
        "cheapest OVER TIME (G9)."),
    ("dim_metric", "comparable_across_jurisdictions"): (
        "FALSE for CPI index levels. NBS prints the prohibition in the source (G2)."),
    ("dim_metric", "is_local_mobility"): (
        "Okada, intracity bus and water only. Air and intercity bus are inter-regional "
        "services and are never folded into a local-mobility claim (G7)."),
    ("dim_jurisdiction", "jurisdiction"): (
        "36 states and the Federal Capital Territory = 37 jurisdictions. Never '37 states'."),
}

TABLE_DESCRIPTIONS = {
    "fact_cost": "Jurisdiction x month x metric panel, 8,177 rows. Primary publications only (G10).",
    "dim_jurisdiction": "37 jurisdictions - 36 states and the FCT.",
    "dim_metric": "The rule carrier. Holds unit, cost family, local-mobility flag, rank stability and cross-jurisdiction comparability, so G2, G7 and G9 are enforced in the model rather than per visual.",
    "dim_date": "Month grain. Marked as the model's date table.",
    "ref_food_zone": "ZONE GRAIN - six zones. DELIBERATELY HAS NO RELATIONSHIP to dim_jurisdiction: food has no state-level prices at all (G3).",
    "ref_nerc_band": "DISCO GRAIN, single July 2025 cross-section. DELIBERATELY HAS NO RELATIONSHIP to dim_jurisdiction: DisCo territories are not jurisdictions (G4).",
    "ref_selfgen": "Diesel self-generation cost against a FIXED July 2025 Band A reference tariff of NGN 209.50/kWh. The reference is a cross-section, not a tariff history.",
    "ref_mode_variance": "Variance decomposition by transport mode. Mode grain, not metric_code - no relationship by design.",
    "ref_page_narrative": "Signal / what it means / what to review / boundary, one row per page.",
    "ref_attention": "The decision messages behind 'What should I pay attention to?'.",
    "ref_archetype": "Six business archetypes with their visible exposures, signals, review points, boundaries and the data still needed.",
    "ref_archetype_section": "The archetype text in LONG form, one row per (archetype, section). Reshaped this way because a table is the only Power BI visual that wraps a paragraph.",
    "ref_finding": "The six headline findings, each stated as a business question with what was found, why it matters, who should pay attention, what to review and what it cannot prove.",
    "ref_finding_section": "The findings in LONG form, one row per (finding, section) - the shape a wrapping table needs.",
    "ref_scope": "WHAT NBCI MEASURES AND WHAT IT DOES NOT. Business attractiveness depends on revenue opportunity, operating costs and location advantages; this dataset covers part of the middle term only. Deliberately has NO relationship to anything - it is the framing, not data to slice.",
    "ref_capability": "WHAT THIS PROJECT CAN AND CANNOT DO TODAY, in two halves. What it delivers now is external cost intelligence, business exposure and guidance on what to investigate. Company financial data, market data, scenario modelling and company-specific profitability decisions are NOT in it. Deliberately has NO relationship to anything - it is the boundary, not data to slice.",
    "ref_methodology": "Methodology and validation facts held as data so they version with the model.",
    "ref_rule": "The 15 binding analysis rules, so a visual can display the rule it obeys.",
}


# ---------------------------------------------------------------------------
# Relationships. (fromTable, fromColumn, toTable, toColumn)
# Every one is many-to-one, single direction.
#
# ABSENT BY DESIGN - do not "fix" these:
#   ref_food_zone   -> dim_jurisdiction   (G3, zone grain)
#   ref_nerc_band   -> dim_jurisdiction   (G4, DisCo grain)
#   ref_mode_variance -> dim_metric       (mode grain, not metric_code)
#   ref_breakeven   -> anything           (service-band grain, national benchmark)
# ---------------------------------------------------------------------------
RELATIONSHIPS = [
    ("fact_cost", "jurisdiction", "dim_jurisdiction", "jurisdiction"),
    ("fact_cost", "date", "dim_date", "date"),
    ("fact_cost", "metric_code", "dim_metric", "metric_code"),
    ("fact_extreme_flag", "metric_code", "dim_metric", "metric_code"),
    ("fact_extreme_flag", "observation_month", "dim_date", "date"),
    ("ref_trend_window", "metric_code", "dim_metric", "metric_code"),
    ("ref_dispersion", "metric_code", "dim_metric", "metric_code"),
    ("ref_shock", "metric_code", "dim_metric", "metric_code"),
    ("ref_rank_stability", "metric_code", "dim_metric", "metric_code"),
    ("ref_rank_verdict", "metric_code", "dim_metric", "metric_code"),
    ("ref_flag_level", "metric_code", "dim_metric", "metric_code"),
    ("ref_location_value", "metric_code", "dim_metric", "metric_code"),
    ("ref_exposure", "metric_code", "dim_metric", "metric_code"),
    ("ref_fare_ratchet", "metric_code", "dim_metric", "metric_code"),
    ("ref_fare_vs_cpi", "metric_code", "dim_metric", "metric_code"),
    ("ref_north_south_gap", "metric_code", "dim_metric", "metric_code"),
    ("ref_north_south_gap", "observation_month", "dim_date", "date"),
    ("ref_north_south_member", "state_name", "dim_jurisdiction", "jurisdiction"),
    ("ref_mobility_dear", "state_name", "dim_jurisdiction", "jurisdiction"),
    ("ref_mobility_cheap", "state_name", "dim_jurisdiction", "jurisdiction"),
    ("ref_selfgen", "observation_month", "dim_date", "date"),
    ("ref_named_gaps", "metric_code", "dim_metric", "metric_code"),
    # Let a slicer selection drive the matching long-form section table.
    ("ref_archetype_section", "archetype", "ref_archetype", "archetype"),
    ("ref_finding_section", "headline", "ref_finding", "headline"),
]

RELATIONSHIPS_ABSENT_BY_DESIGN = [
    ("ref_food_zone", "dim_jurisdiction", "G3 - food is ZONE grain; no state-level food prices exist"),
    ("ref_nerc_band", "dim_jurisdiction", "G4 - DisCo territories are not jurisdictions"),
    ("ref_mode_variance", "dim_metric", "mode grain, not metric_code"),
    ("ref_breakeven", "dim_metric", "service-band grain against a national benchmark"),
    ("ref_mobility_split", "dim_jurisdiction", "single-column list, joined visually not relationally"),
    ("ref_scope", "anything", "the scope framing - what NBCI measures and what it does not. Not data"),
    ("ref_capability", "anything", "the capability boundary - what this project can and cannot do today. Not data"),
]


# ---------------------------------------------------------------------------
# DAX measures. (table, name, expression, formatString, displayFolder, description)
# ---------------------------------------------------------------------------
MEASURES = [
    # ---- core aggregation -------------------------------------------------
    ("fact_cost", "Median Value",
     "VAR NotComparable =\n"
     "    CALCULATE ( COUNTROWS ( dim_metric ), dim_metric[comparable_across_jurisdictions] = FALSE )\n"
     "RETURN\n"
     "    IF (\n"
     "        NotComparable > 0,\n"
     "        BLANK (),\n"
     "        MEDIANX ( VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ) )\n"
     "    )",
     "#,0.00", "1 Core",
     "Median across the 37 jurisdictions, equally weighted. NOT a national average (G15). "
     "Returns BLANK if a metric that may not be compared across jurisdictions is in context (G2)."),

    ("fact_cost", "Latest Month",
     "CALCULATE ( MAX ( fact_cost[date] ) )",
     "yyyy-mm-dd", "1 Core",
     "Latest month for which the metric in context actually has rows. Series end on different months (G14)."),

    ("fact_cost", "Latest Median Value",
     "VAR L = [Latest Month]\n"
     "RETURN CALCULATE ( [Median Value], dim_date[date] = L )",
     "#,0.00", "1 Core",
     "Median across jurisdictions in that metric's own latest month."),

    ("fact_cost", "Observation Count",
     "COUNTROWS ( fact_cost )", "#,0", "1 Core",
     "Rows in filter context at the (jurisdiction, month, metric) grain."),

    ("fact_cost", "Jurisdiction Count",
     "DISTINCTCOUNT ( fact_cost[jurisdiction] )", "#,0", "1 Core",
     "Distinct jurisdictions with an observation in context. 37 = 36 states and the FCT."),

    ("fact_cost", "Metric Count",
     "DISTINCTCOUNT ( fact_cost[metric_code] )", "#,0", "1 Core", ""),

    # ---- change over time -------------------------------------------------
    ("fact_cost", "Value MoM %",
     "VAR Cur = [Median Value]\n"
     "VAR PrevMonth = CALCULATE ( MAX ( dim_date[date] ), dim_date[date] < MIN ( dim_date[date] ), ALL ( dim_date ) )\n"
     "VAR Prev = CALCULATE ( [Median Value], dim_date[date] = PrevMonth, ALL ( dim_date ) )\n"
     "RETURN IF ( ISBLANK ( Prev ) || Prev = 0, BLANK (), DIVIDE ( Cur - Prev, Prev ) * 100 )",
     "#,0.00\\%", "2 Change",
     "Month-over-month change in the cross-jurisdiction median. BLANK where the previous month has no rows."),

    ("fact_cost", "Value YoY %",
     "VAR CurMonth = MIN ( dim_date[date] )\n"
     "VAR PriorMonth = EDATE ( CurMonth, -12 )\n"
     "VAR Cur = [Median Value]\n"
     "VAR Prior = CALCULATE ( [Median Value], dim_date[date] = PriorMonth, ALL ( dim_date ) )\n"
     "RETURN IF ( ISBLANK ( Prior ) || Prior = 0, BLANK (), DIVIDE ( Cur - Prior, Prior ) * 100 )",
     "#,0.00\\%", "2 Change",
     "RULE G11. Returns BLANK when no row exists exactly 12 months earlier, so the line BREAKS "
     "rather than bridging a known gap. CPI year-on-year has a genuine hole at 2026-02."),

    # ---- dispersion -------------------------------------------------------
    ("fact_cost", "Spread NGN",
     "VAR Hi = MAXX ( VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ) )\n"
     "VAR Lo = MINX ( VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ) )\n"
     "RETURN IF ( ISBLANK ( Hi ) || ISBLANK ( Lo ), BLANK (), Hi - Lo )",
     "#,0.00", "3 Dispersion",
     "Dearest minus cheapest across the 37 jurisdictions. Showing spread is always allowed; "
     "NAMING the jurisdiction is not, unless the metric is rank-stable (G9)."),

    ("fact_cost", "Dearest over Cheapest",
     "VAR Hi = MAXX ( VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ) )\n"
     "VAR Lo = MINX ( VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ) )\n"
     "RETURN IF ( ISBLANK ( Lo ) || Lo = 0, BLANK (), DIVIDE ( Hi, Lo ) )",
     "0.00\\x", "3 Dispersion", ""),

    ("fact_cost", "Dearest Jurisdiction",
     "VAR Stable = SELECTEDVALUE ( dim_metric[rank_stable], FALSE )\n"
     "VAR Hi =\n"
     "    TOPN ( 1, VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ), DESC )\n"
     "RETURN\n"
     "    IF (\n"
     "        NOT Stable,\n"
     '        "Not named - order unstable over time",\n'
     "        CONCATENATEX ( Hi, dim_jurisdiction[jurisdiction], \", \" )\n"
     "    )",
     None, "3 Dispersion",
     "RULE G9. Names a jurisdiction only for water, okada, intracity bus and intercity bus. "
     "For air, diesel, LPG and petrol the monthly order does not persist, so naming one would "
     "imply a durability the evidence does not support."),

    ("fact_cost", "Cheapest Jurisdiction",
     "VAR Stable = SELECTEDVALUE ( dim_metric[rank_stable], FALSE )\n"
     "VAR Lo =\n"
     "    TOPN ( 1, VALUES ( dim_jurisdiction[jurisdiction] ), CALCULATE ( AVERAGE ( fact_cost[value] ) ), ASC )\n"
     "RETURN\n"
     "    IF (\n"
     "        NOT Stable,\n"
     '        "Not named - order unstable over time",\n'
     "        CONCATENATEX ( Lo, dim_jurisdiction[jurisdiction], \", \" )\n"
     "    )",
     None, "3 Dispersion", "RULE G9 - see [Dearest Jurisdiction]."),

    # ---- headline KPIs, read from committed evidence ----------------------
    ("ref_shock", "Diesel Trough to Latest %",
     "CALCULATE ( SUM ( ref_shock[median_pct] ), "
     "ref_shock[metric_code] = \"DIESEL_PRICE_NGN_PER_LITRE\", ALL ( ref_shock ) )",
     "#,0.00\\%", "4 Headline",
     "K01. Median per-jurisdiction change 2025-09 to 2026-05. Evidence: f31_shock_trough_to_latest.csv."),

    ("ref_shock", "Petrol Trough to Latest %",
     "CALCULATE ( SUM ( ref_shock[median_pct] ), "
     "ref_shock[metric_code] = \"PETROL_PRICE_NGN_PER_LITRE\", ALL ( ref_shock ) )",
     "#,0.00\\%", "4 Headline", "K02. Evidence: f31_shock_trough_to_latest.csv."),

    ("ref_shock", "Jurisdictions Rising",
     "SUM ( ref_shock[states_up] )", "#,0", "4 Headline",
     "Jurisdictions in which the metric rose over the trough-to-latest stretch."),

    ("ref_location_value", "Spread NGN (evidence)",
     "SUM ( ref_location_value[spread_ngn] )", "#,0.00", "4 Headline",
     "K10/K11. Dearest minus cheapest at 2026-04. Evidence: d8_location_value_by_cost.csv."),

    ("ref_location_value", "Dearest over Cheapest (evidence)",
     "SUM ( ref_location_value[dearest_over_cheapest] )", "0.00\\x", "4 Headline",
     "K12/K18-K21. Evidence: d8_location_value_by_cost.csv."),

    ("ref_flag_level", "ELEVATED Level %",
     "SUM ( ref_flag_level[elevated_p90_abs_pct] )", "#,0.00\\%", "5 Signals",
     "p90 of absolute month-over-month change, 518 observations. DESCRIPTIVE, not an action trigger (G13)."),

    ("ref_flag_level", "EXTREME Level %",
     "SUM ( ref_flag_level[extreme_p95_abs_pct] )", "#,0.00\\%", "5 Signals",
     "K28. p95 of absolute month-over-month change, 518 observations. DESCRIPTIVE, not an action trigger (G13)."),

    ("fact_extreme_flag", "Jurisdictions Flagged EXTREME",
     "SUM ( fact_extreme_flag[jurisdictions_flagged_extreme] )", "#,0", "5 Signals",
     "K27. Count of jurisdictions above p95 in that month. Evidence: d2_extreme_flags_by_month.csv."),

    ("ref_selfgen", "Self-gen Multiple of Reference",
     "AVERAGE ( ref_selfgen[multiple_of_reference_tariff] )", "0.00\\x", "5 Signals",
     "K29. Diesel NGN/kWh divided by the FIXED July 2025 Band A reference of NGN 209.50/kWh. "
     "The reference is a cross-section roughly 10 months older than the diesel series: if the "
     "tariff has since risen, the true multiple is smaller (G4)."),

    ("ref_exposure", "Impact pp per 1pp Share",
     "SUM ( ref_exposure[total_cost_impact_pp_per_1pp_share] )", "0.0000", "5 Signals",
     "Percentage points of total cost per 1 pp of cost share. Apply your OWN cost share - "
     "the dataset holds no company cost structure (G12, G13)."),

    ("ref_fare_ratchet", "Share Fare Rose %",
     "SUM ( ref_fare_ratchet[share_fare_rose_pct] )", "#,0.0\\%", "5 Signals",
     "K17. Share of jurisdiction-months where the fare rose although petrol was cheaper "
     "year-on-year. Passenger fares, not freight rates. No causal claim."),

    # ---- metric-scoped headline cards -------------------------------------
    #
    # WHY THESE EXIST. A card bound to a per-metric evidence column with no metric in
    # filter context aggregates across ALL NINE costs. That printed "spread = 68.40K"
    # (naira-per-litre added to naira-per-journey) and "ELEVATED = 183.35%" (the sum of
    # nine separate p90 levels) - numbers that mean nothing and that rules G1, G6 and G8
    # exist to prevent. Each card below is pinned to ONE metric, so it carries one unit.
    ("ref_location_value", "Water Location Ratio",
     'CALCULATE ( SUM ( ref_location_value[dearest_over_cheapest] ), '
     'ref_location_value[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY" )',
     "0.00\\x", "4 Headline",
     "K18. Water transport, dearest over cheapest at 2026-04. Evidence: d8."),

    ("ref_location_value", "Petrol Location Ratio",
     'CALCULATE ( SUM ( ref_location_value[dearest_over_cheapest] ), '
     'ref_location_value[metric_code] = "PETROL_PRICE_NGN_PER_LITRE" )',
     "0.00\\x", "4 Headline",
     "K21. Petrol, dearest over cheapest at 2026-04. Shown precisely because it is nearly 1. Evidence: d8."),

    ("ref_location_value", "Water Spread NGN",
     'CALCULATE ( SUM ( ref_location_value[spread_ngn] ), '
     'ref_location_value[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY" )',
     "#,0.00", "4 Headline", "Water transport spread at 2026-04. Evidence: d8."),

    ("fact_cost", "Dearest Water Jurisdiction",
     'CALCULATE ( [Dearest Jurisdiction], '
     'dim_metric[metric_code] = "TRANSPORT_WATER_NGN_PER_JOURNEY", '
     "dim_date[date] = DATE ( 2026, 4, 1 ) )",
     None, "4 Headline",
     "Water is rank-stable, so a jurisdiction MAY be named (G9)."),

    ("fact_cost", "Dearest Petrol Jurisdiction",
     'CALCULATE ( [Dearest Jurisdiction], '
     'dim_metric[metric_code] = "PETROL_PRICE_NGN_PER_LITRE", '
     "dim_date[date] = DATE ( 2026, 4, 1 ) )",
     None, "4 Headline",
     "Petrol is rank-UNSTABLE, so this deliberately refuses to name one (G9). Paired with "
     "[Dearest Water Jurisdiction] it shows the rule working in both directions."),

    ("ref_flag_level", "Diesel ELEVATED Level %",
     'CALCULATE ( SUM ( ref_flag_level[elevated_p90_abs_pct] ), '
     'ref_flag_level[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE" )',
     "#,0.00\\%", "5 Signals",
     "Diesel p90 of absolute month-over-month change, 518 observations. Descriptive (G13)."),

    ("ref_flag_level", "Diesel EXTREME Level %",
     'CALCULATE ( SUM ( ref_flag_level[extreme_p95_abs_pct] ), '
     'ref_flag_level[metric_code] = "DIESEL_PRICE_NGN_PER_LITRE" )',
     "#,0.00\\%", "5 Signals", "K28. Diesel p95. Descriptive, not a trigger (G13)."),

    ("fact_extreme_flag", "Peak Jurisdictions Flagged EXTREME",
     "MAX ( fact_extreme_flag[jurisdictions_flagged_extreme] )", "#,0", "5 Signals",
     "The worst SINGLE metric-month: how synchronised a flag can get. Summing the column "
     "across metrics and months instead would answer a question nobody asked."),

    ("ref_selfgen", "Self-gen Multiple Latest",
     "CALCULATE ( SUM ( ref_selfgen[multiple_of_reference_tariff] ), "
     "ref_selfgen[observation_month] = DATE ( 2026, 5, 1 ), "
     "ref_selfgen[genset_kwh_per_litre] = 3.0 )",
     "0.00\\x", "5 Signals",
     "K29. At 2026-05 diesel and 3.0 kWh per litre, against the FIXED July 2025 reference "
     "of NGN 209.50/kWh. Evidence: d3."),

    # ---- methodology ------------------------------------------------------
    ("ref_methodology", "Validation Checks Passed",
     "110", "#,0", "6 Methodology",
     "K06/K30. discovery 64/64 + source verification 19/19 + decision inputs 27/27."),

    ("ref_methodology", "Raw Files Verified",
     "342", "#,0", "6 Methodology", "K32. SHA-256 verified unchanged."),

    ("ref_methodology", "Fact Rows in Database",
     "29032", "#,0", "6 Methodology", "K31. Across 12 core fact tables."),

    ("ref_methodology", "Panel Grain Duplicates",
     "0", "#,0", "6 Methodology", "K33. Grain is (jurisdiction, observation month, metric code)."),

    # ---- the explanation layer --------------------------------------------
    ("ref_finding", "Findings Published",
     "COUNTROWS ( ref_finding )", "#,0", "7 Narrative",
     "How many headline findings the first page carries. Kept small on purpose."),

    ("ref_finding", "Finding Question",
     "SELECTEDVALUE ( ref_finding[question], \"Select a finding.\" )",
     None, "7 Narrative", "The business question the selected finding answers."),

    ("ref_finding", "Finding Evidence",
     "SELECTEDVALUE ( ref_finding[evidence], \"\" )",
     None, "7 Narrative", "The committed evidence file behind the selected finding."),

    ("ref_archetype", "Archetype Costs",
     "SELECTEDVALUE ( ref_archetype[costs] )", None, "7 Narrative",
     "Which NBCI costs matter to the selected archetype."),

    ("ref_archetype", "Archetype Data Needed",
     "SELECTEDVALUE ( ref_archetype[needed] )", None, "7 Narrative",
     "The company-specific data required before any actual business decision."),

    # ---- narrative --------------------------------------------------------
    ("ref_page_narrative", "Page Signal",
     "SELECTEDVALUE ( ref_page_narrative[signal] )", None, "7 Narrative",
     "What the data shows on the selected page."),
    ("ref_page_narrative", "Page What It Means",
     "SELECTEDVALUE ( ref_page_narrative[meaning] )", None, "7 Narrative",
     "The business implication in plain English."),
    ("ref_page_narrative", "Page What To Review",
     "SELECTEDVALUE ( ref_page_narrative[review] )", None, "7 Narrative",
     "The operating area that deserves attention. Review language only - the dataset cannot "
     "tell a company to reprice or relocate."),
    ("ref_page_narrative", "Page Boundary",
     "SELECTEDVALUE ( ref_page_narrative[boundary] )", None, "7 Narrative",
     "What this data cannot tell you."),


    ("dim_metric", "Selected Metric Note",
     "SELECTEDVALUE ( dim_metric[usage_note], \"Select a single cost to see its usage rule.\" )",
     None, "7 Narrative",
     "The rule that governs how the selected cost may be used."),

    ("dim_metric", "Rank Stability Note",
     "VAR Stable = SELECTEDVALUE ( dim_metric[rank_stable], BLANK () )\n"
     "RETURN\n"
     "    SWITCH (\n"
     "        TRUE (),\n"
     '        ISBLANK ( Stable ), "Select a single cost.",\n'
     '        Stable, "The order holds month to month - a jurisdiction may be named.",\n'
     '        "The order keeps changing - the gap may be shown, but no jurisdiction may be named as cheapest or dearest OVER TIME. Each single month\'s ranking is still valid (G9)."\n'
     "    )",
     None, "7 Narrative", "RULE G9, surfaced on the page so the restriction is visible, not implicit."),
]


# ---------------------------------------------------------------------------
# Build the spec
# ---------------------------------------------------------------------------
def build_spec() -> dict:
    tables = []
    for csv_path in sorted(DATA.glob("*.csv")):
        name = csv_path.stem
        df = pd.read_csv(csv_path)
        cols = []
        for c in df.columns:
            t = tom_type(df[c], c)
            col = {
                "name": c,
                "dataType": t,
                "sourceColumn": c,
                "isHidden": (name, c) in HIDDEN_COLUMNS,
            }
            if c in FORMAT_BY_NAME:
                col["formatString"] = FORMAT_BY_NAME[c]
            if (name, c) in COLUMN_DESCRIPTIONS:
                col["description"] = COLUMN_DESCRIPTIONS[(name, c)]
            # Numeric columns used as a grouping/legend rather than a value must not
            # default to Sum, or the legend collapses into a single aggregated point.
            if t in ("Double", "Int64") and (c.endswith(("_id", "_order", "rank"))
                                             or c in NO_SUMMARIZE):
                col["summarizeBy"] = "None"
            cols.append(col)

        table = {
            "name": name,
            "columns": cols,
            "partitionExpression": m_expression(name, cols),
            "measures": [],
        }
        if name in TABLE_DESCRIPTIONS:
            table["description"] = TABLE_DESCRIPTIONS[name]
        if name == "dim_date":
            table["dataCategory"] = "Time"
            for col in table["columns"]:
                if col["name"] == "date":
                    col["isKey"] = True
                # Without this the axis sorts "Apr 2025, Apr 2026, Aug 2025, Dec 2025"
                # alphabetically. month_label is text, so it needs an explicit sort key.
                if col["name"] == "month_label":
                    col["sortByColumn"] = "month_index"
        if name == "dim_metric":
            for col in table["columns"]:
                if col["name"] == "metric":
                    col["sortByColumn"] = "cost_family"
        if name == "ref_finding":
            for col in table["columns"]:
                if col["name"] == "headline":
                    col["sortByColumn"] = "rank"
        if name == "ref_finding_section":
            for col in table["columns"]:
                if col["name"] == "section":
                    col["sortByColumn"] = "section_order"
                if col["name"] in ("section_order", "rank"):
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        if name == "ref_scope":
            for col in table["columns"]:
                if col["name"] == "part":
                    col["sortByColumn"] = "part_order"
                if col["name"] == "part_order":
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        if name == "ref_capability":
            for col in table["columns"]:
                if col["name"] == "capability":
                    col["sortByColumn"] = "capability_order"
                if col["name"] == "capability_order":
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        if name == "ref_archetype":
            for col in table["columns"]:
                if col["name"] == "archetype":
                    col["sortByColumn"] = "order"
                if col["name"] == "order":
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        if name == "ref_archetype_section":
            for col in table["columns"]:
                if col["name"] == "section":
                    col["sortByColumn"] = "section_order"
                if col["name"] == "section_order":
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        if name == "ref_rule":
            for col in table["columns"]:
                if col["name"] == "rule_id":
                    col["sortByColumn"] = "rule_no"
                if col["name"] == "rule_no":
                    col["isHidden"] = True
                    col["summarizeBy"] = "None"
        tables.append(table)

    by_name = {t["name"]: t for t in tables}

    for tbl, mname, expr, fmt, folder, desc in MEASURES:
        if tbl not in by_name:
            raise SystemExit(f"measure '{mname}' targets missing table '{tbl}'")
        m = {"name": mname, "expression": expr}
        if fmt:
            m["formatString"] = fmt
        if folder:
            m["displayFolder"] = folder
        if desc:
            m["description"] = desc
        by_name[tbl]["measures"].append(m)

    # A measure may not share a name with a column in the same table, and Tabular compares
    # names CASE-INSENSITIVELY. Desktop refuses the whole project with "The 'X' measure
    # cannot be created because a column with the same name already exists", so catch it
    # here rather than after a 90-second Desktop launch.
    for t in tables:
        col_names = {c["name"].casefold() for c in t["columns"]}
        for m in t["measures"]:
            if m["name"].casefold() in col_names:
                raise SystemExit(
                    f"name collision in '{t['name']}': measure '{m['name']}' clashes with a "
                    f"column of the same name (Tabular names are case-insensitive)")

    rels = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        for t, c in ((ft, fc), (tt, tc)):
            if t not in by_name:
                raise SystemExit(f"relationship references missing table '{t}'")
            if c not in {x["name"] for x in by_name[t]["columns"]}:
                raise SystemExit(f"relationship references missing column {t}[{c}]")
        rels.append({
            "name": f"{ft}_{fc}__{tt}_{tc}",
            "fromTable": ft, "fromColumn": fc,
            "toTable": tt, "toColumn": tc,
        })

    return {
        "name": MODEL_NAME,
        # 1606 is what THIS Desktop build's own engine writes for a new model, read from
        # the live workspace instance rather than inferred.
        #
        # Do not raise this speculatively. The TOM API happily ACCEPTS 1610 - the setter
        # does not validate - but the engine's SupportedCompatibilityLevels runs
        # ...1607, 1608, 1609, 1700... with no 1610 in it, and Desktop refuses the project
        # with "Unsupported db compat level detected". An API that accepts a value is not
        # evidence that the engine supports it.
        "compatibilityLevel": COMPATIBILITY_LEVEL,
        "culture": "en-GB",
        # Raw path. json.dumps escapes the backslashes for JSON; Power Query M treats
        # a backslash literally, so the value must NOT be pre-doubled here.
        "dataFolderDefault": str(DATA),
        "tables": tables,
        "relationships": rels,
        "relationshipsAbsentByDesign": [
            {"table": a, "wouldJoin": b, "why": c}
            for a, b, c in RELATIONSHIPS_ABSENT_BY_DESIGN
        ],
    }


if __name__ == "__main__":
    spec = build_spec()
    out = PBI / "build"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "model_spec.json"
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    n_cols = sum(len(t["columns"]) for t in spec["tables"])
    n_meas = sum(len(t["measures"]) for t in spec["tables"])
    print(f"tables       {len(spec['tables'])}")
    print(f"columns      {n_cols}")
    print(f"measures     {n_meas}")
    print(f"relationships {len(spec['relationships'])} "
          f"(+{len(spec['relationshipsAbsentByDesign'])} absent by design)")
    print(f"-> {path}")
