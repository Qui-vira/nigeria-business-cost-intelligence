"""Static narrative tables for the Power BI model, held as DATA rather than visual text.

WHY THESE ARE TABLES AND NOT TEXT BOXES
---------------------------------------
Methodology statements, archetype boundaries and the decision messages are part of the
deliverable, not decoration. Holding them as model tables means they version with the
model, can be validated by row count, and cannot drift between pages the way duplicated
textbox copy does.

EVERY STRING HERE IS SOURCED FROM COMMITTED EVIDENCE - `docs/analysis/
business_decision_analysis_report.md`, `docs/analysis/analysis_discovery_report.md` and
`docs/dashboards/dashboard_specification.md`. Nothing is invented, and no figure is
restated here that is not already published in those documents.

THE FINDINGS, ARCHETYPES AND SCOPE FRAMING LIVE IN `pbi_findings.py`. This module keeps
the per-page band, the 15 binding rules and the methodology facts.

LANGUAGE RULE (binding): the dataset holds no company-level cost shares, margins or
pass-through ability, so nothing here instructs a business to act. Every "what to review"
string uses review / investigate / compare / reassess / put on the agenda. A string that
tells a company to raise prices or relocate would be unsupported by the evidence.
"""
from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# The 15 global rules, carried as data so a visual can display the rule it obeys.
# ---------------------------------------------------------------------------
RULES = [
    ("G1", "Never mix geography grains in one visual", "STATE, ZONE and NATIONAL are separate; summing them double-counts"),
    ("G2", "Never compare CPI index levels between jurisdictions", "NBS prints the prohibition in the source; only change rates are comparable"),
    ("G3", "Food is ZONE grain only - six zones, never 37 jurisdictions", "Hard source ceiling; no state-level food prices exist"),
    ("G4", "NERC tariffs are DisCo grain and a single July 2025 cross-section", "Never mapped to a jurisdiction, never plotted as a time series"),
    ("G5", "FX is NATIONAL context only", "Single national series; never a jurisdiction metric"),
    ("G6", "Transport modes are never combined or averaged", "A journey by air and by okada are different products"),
    ("G7", "Air and intercity bus are inter-regional, not local mobility", "83% of air's monthly variation is a common national movement"),
    ("G8", "LPG cylinder sizes are separate series", "5 kg and 12.5 kg are different products"),
    ("G9", "Where the order keeps changing, show the gap but name no jurisdiction as cheapest or dearest over time", "Each single month's ranking is a valid snapshot; the order does not hold from month to month"),
    ("G10", "Primary publications only", "Mixing publication semantics answers two questions at once"),
    ("G11", "Never interpolate across a known gap", "CPI YoY has no 2026-02 rows; every YoY line must break"),
    ("G12", "No composite cost index", "Normalisation and weighting have not been defined or approved"),
    ("G13", "Movement flags are descriptive, not action triggers", "Whether a move matters needs cost exposure, margin and pass-through"),
    ("G14", "Series end on different months", "LPG ends 2026-04; fuels and transport 2026-05; CPI 2026-07"),
    ("G15", "Cross-jurisdiction median is not a national statistic", "Equally weighted median of 37 jurisdictions, never 'Nigeria average'"),
]


# ---------------------------------------------------------------------------
# Page narrative - the four-part decision-first structure, one row per page.
# ---------------------------------------------------------------------------
PAGE_NARRATIVE = [
    dict(
        page_order=1, page="What is changing?",
        signal="Diesel rose a median +158.2% from its 2025-09 low point to 2026-05 and rose in all 37 jurisdictions. Petrol rose +65.4%. Transport fares rose steadily and did NOT fall back when fuel fell. The inflation rate in the news went the other way: CPI all items fell from a median +22.34% in 2025-02 to +15.36% in 2026-04.",
        meaning="Diesel and transport fares climbed while the inflation rate people read in the news was falling. Anyone planning from the headline inflation rate alone would have missed both. This is about the nine costs measured here, not about a business's whole cost base.",
        review="Put your input costs on the management agenda: which of these nine you actually buy, and in what proportion. Work out what share of your spending each one takes before assuming any of this reaches your margin.",
        boundary="This measures PART OF OPERATING COST ONLY - nine traded inputs plus inflation rates. It is not total cost, not business attractiveness and not profitability. No rent, no wages, no land, no taxes, no demand and no revenue.",
    ),
    dict(
        page_order=2, page="Fuel and energy",
        signal="Fuel is close to a national price. The entire diesel spread across 37 jurisdictions is NGN 638.66/l (1.29x) and petrol NGN 195.16/l (1.14x). Self-generation ran 3.9-5.2x the fixed July 2025 Band A reference tariff and was never cheaper than grid.",
        meaning="Fuel changes a lot over TIME and very little by PLACE: the movement month to month is large, the movement across the map is small. And a generator running beyond the hours the power is actually out is a decision that costs money, not a neutral one.",
        review="Investigate pricing and surcharge terms rather than siting. Measure your own litres per month and diesel as a share of total cost. Read your service band off the bill and re-run the self-generation comparison against the tariff you actually pay.",
        boundary="For all four fuel costs the order of jurisdictions keeps changing, so no jurisdiction is named as the cheapest or the dearest OVER TIME. Each single month's ranking is still valid. The NERC tariff is a FIXED July 2025 cross-section about ten months older than the diesel series, and DisCo territories are not jurisdictions. LPG ends 2026-04.",
    ),
    dict(
        page_order=3, page="Moving people and goods",
        signal="In 81 jurisdiction-month pairs where petrol was cheaper year-on-year, okada, water and air fares still rose in 100% of observations, intracity bus in 98.8% and intercity bus in 84.0%. Okada fares rose +50.7% against CPI +16.2%.",
        meaning="Fares that rise with fuel do not fall with it. A business buying movement - last-mile delivery, staff commuting, customer access - should not expect a fall in the pump price to arrive as a fare reduction.",
        review="Compare what you actually paid for delivery and staff transport against the pump price over the same months. Examine whether allowances indexed to CPI alone have kept pace with observed fares.",
        boundary="PASSENGER FARES, not freight rates - using intercity bus as a haulage proxy is an assumption. No causal claim: petrol is one observed input among many, and the year-on-year observations fall in only four months, so they are not independent.",
    ),
    dict(
        page_order=4, page="Where costs differ",
        signal="Water transport varies 6.91x between the lowest and highest measured value across the 37 jurisdictions and okada 2.32x. Petrol varies 1.14x. Only four of the nine costs have a ranking that persists month to month.",
        meaning="Location changes some measured costs a great deal and others barely at all. A location comparison built on fuel is built on a difference close to noise; one built on local mobility is acting on a real and persistent difference.",
        review="Identify which cost families you actually buy in volume and compare candidate locations on those, naming the specific metric. Examine whether any siting assumption in your plan rests on a cost that barely varies.",
        boundary="A LOWER MEASURED COST IS NOT A BETTER BUSINESS LOCATION. This page compares input prices only. Demand, purchasing power, supplier access, infrastructure and competition are absent and routinely outweigh an input-cost difference. Food is ZONE grain only.",
    ),
    dict(
        page_order=5, page="How unusual is this month?",
        signal="EXTREME months cluster rather than arriving evenly: air was flagged in 26 of 37 jurisdictions in 2025-12 and diesel in 25 of 37 in 2026-04. Each flag level is set from that series' own 518-observation history.",
        meaning="When a flag lands in most jurisdictions at once it describes a portfolio-wide condition rather than a local one. It describes how unusual the month is - not whether it reaches your margin.",
        review="Put a cost review on the agenda when a cost you actually buy is flagged, and work out what share of your spending goes on it before acting on the flag.",
        boundary="Flags are DESCRIPTIVE, not action triggers. They rest on 14 month-pairs, are not control limits, and say nothing about your exposure, your margin or your ability to pass a cost on.",
    ),
    dict(
        page_order=6, page="Who this matters more for",
        signal="Which costs bite depends on the kind of business. Logistics is dominated by diesel, the cost that does most to a total bill and one of the least variable from place to place. Service businesses are the opposite: the cost that moves most for them is the one where the choice of location genuinely matters.",
        meaning="There is no single answer to 'have my costs gone up'. Which of these nine costs you buy, and in what proportion, decides whether a headline movement matters to you or barely touches you.",
        review="Find the closest kind of business, review the costs listed for it, and compare them against what you actually spend. Treat the 'company data needed' list as the gap to close before drawing any conclusion about your own company.",
        boundary="Every archetype is missing rent and labour. Pharmacy in particular: profitability, margin and viability CANNOT be calculated or inferred - there are no acquisition prices, no consumption, no margins and no revenue.",
    ),
    dict(
        page_order=7, page="Can I trust this?",
        signal="110 of 110 validation checks pass across three analysis passes. 342 raw source files are SHA-256 verified, 29,032 fact rows are loaded, and the panel has 0 duplicate rows at its (jurisdiction, month, metric) grain.",
        meaning="The pipeline is faithful to what the government agencies published. Published source defects are carried and flagged, never silently corrected, so a reader can see exactly where the sources disagree with themselves.",
        review="Review the named gaps and the anomaly register before quoting any single figure, and check the grain and window stated on each page against the question being asked.",
        boundary="Validation proves PIPELINE FIDELITY, not source correctness. It does not validate NBS, CBN or NERC's own figures. Two named gaps remain open by design: CPI year-on-year has no 2026-02 rows, and CPI index has no 2025-04 rows.",
    ),
]

# ---------------------------------------------------------------------------
# Methodology facts.
# ---------------------------------------------------------------------------
METHODOLOGY = [
    ("Validation checks passed", "110 of 110", "Three analysis passes: discovery 64/64, source verification 19/19, decision inputs 27/27"),
    ("Raw source files verified", "342", "SHA-256 verified unchanged; no raw government file is ever modified or committed"),
    ("Fact rows in the database", "29,032", "Across 12 core fact tables, PostgreSQL 18.3"),
    ("Panel rows in this model", "8,177", "From 9,435, less 1,258 CPI INDEX rows excluded under rule G2"),
    ("Panel grain duplicates", "0", "Grain is (jurisdiction, observation month, metric code)"),
    ("Jurisdictions", "37", "36 states and the Federal Capital Territory - never '37 states'"),
    ("Costs tracked", "13 in this model", "9 price metrics plus 4 CPI change rates; 2 CPI index codes excluded (G2)"),
    ("Independent database audit", "245 of 245", "Re-parses all 17 source CSVs itself - 644,578 field comparisons"),
    ("Restatement simulation", "15 of 15", "Rolled back; proves a future republication would be detected, not silently absorbed"),
    ("Source datasets", "8", "NBS petrol, diesel, LPG, transport, food, CPI; CBN NFEM FX; NERC MYTO tariffs"),
    ("Primary common window", "2025-02 to 2026-04", "15 months; the window in which all primary series overlap"),
    ("Named gap - CPI year-on-year", "2026-02 has no rows", "The year-ago column is mislabelled at source; 148 cells excluded rather than imputed"),
    ("Named gap - CPI index", "2025-04 has no rows", "67 of 74 values assigned to the wrong state at source; flagged, not corrected"),
    ("Publication rule", "Primary publications only", "First publication of each month; restatement views are out of scope for this build"),
    ("What validation proves", "Pipeline fidelity", "It does NOT validate the sources themselves. Published source defects are carried and flagged, never silently corrected"),
    ("Map status", "No map is built", "geoBoundaries ADM1 boundary validation is an unmet build gate - see the Methodology page note"),
]


def build() -> dict[str, pd.DataFrame]:
    """Rules, per-page band and methodology facts.

    The findings, archetypes and scope framing live in `pbi_findings.py`; the two are
    merged by the caller so one import gives the whole explanation layer.
    """
    return {
        # rule_no exists so the table sorts G1..G15 instead of the alphabetical
        # G1, G10, G11, G12, G13, G14, G15, G2, G3 ... that a text key gives.
        "ref_rule": pd.DataFrame(
            [(int(r[0][1:]), *r) for r in RULES],
            columns=["rule_no", "rule_id", "rule", "why"]),
        "ref_page_narrative": pd.DataFrame(PAGE_NARRATIVE),
        "ref_methodology": pd.DataFrame(METHODOLOGY, columns=["item", "value", "note"]),
    }
