"""Generate the PBIR report definition: seven pages, decision-first.

FORMAT NOTES (these are the ones that bite)
-------------------------------------------
* Every PBIR file's `$schema` is a `const` in the JSON schema and every file sets
  `additionalProperties: false`. A wrong URL or one stray property is a BLOCKING error,
  not a warning.
* Page and visual folder names must be word characters or hyphens only. A name containing
  a space is SILENTLY DROPPED - the page or visual simply never appears.
* Visual discovery is a folder scan of `pages/<page>/visuals/*/visual.json`. `page.json`
  has no visuals list. On-canvas stacking is `position.z`, not folder order.
* In query projections `SourceRef` uses `Entity`; inside a filter `Where` it uses `Source`
  (the alias declared in the filter's `From`). They are not interchangeable.
* `objects` holds visual-specific formatting, `visualContainerObjects` holds container
  chrome (title, background, border). Both live INSIDE `visual`. `filterConfig` is a
  SIBLING of `visual`, at the file root.
* A textbox's `paragraphs` is a bare JSON array - the one place in `objects` where the
  `{"expr":{"Literal":...}}` wrapper is wrong.
* Files are UTF-8 without BOM. A BOM breaks parsing.

PAGE STRUCTURE - every page carries the same four-part band
-----------------------------------------------------------
    Signal          what the data shows
    What it means   the business implication in plain English
    What to review  the operating area that deserves attention
    Boundary        what this data cannot tell us

The text comes from `pbi_narrative.py`, which is also the source of the `ref_page_narrative`
model table - one source, two representations, so the page and the model cannot drift.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PBI = ROOT / "powerbi"
NAME = "NBCI_Cost_Dashboard"
RPT = PBI / f"{NAME}.Report"
DEF = RPT / "definition"

S = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
SCHEMA_REPORT = f"{S}/report/3.3.0/schema.json"
SCHEMA_VERSION = f"{S}/versionMetadata/1.0.0/schema.json"
SCHEMA_PAGES = f"{S}/pagesMetadata/1.1.0/schema.json"
SCHEMA_PAGE = f"{S}/page/2.1.0/schema.json"
SCHEMA_VISUAL = f"{S}/visualContainer/2.9.0/schema.json"

PAGE_W, PAGE_H = 1280, 1000

INK = "#1B1B1B"
MUTED = "#5B5B5B"
ACCENT = "#0E5A8A"
WARN = "#8A4B0E"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def vid(*parts: str) -> str:
    """Deterministic 20-char lowercase hex name, matching Desktop's own convention.

    Deterministic rather than random so rebuilding the report does not churn every
    folder name and produce a meaningless diff.
    """
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]


def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def s_lit(text: str) -> dict:
    return lit("'" + text.replace("'", "''") + "'")


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


# QueryAggregateFunction: 0=Sum 1=Average 2=DistinctCount 3=Min 4=Max 5=Count 6=Median
def agg(entity: str, prop: str, func: int = 0) -> dict:
    """A numeric COLUMN used in a chart's value role must be wrapped in an explicit
    aggregation.

    A bare `Column` projection in the Y role validates against the schema and renders an
    EMPTY PLOT - the visual appears, titled and framed, with no bars. Measures do not need
    this; columns do. Caught by looking at the rendered report, not by schema validation.
    """
    return {"Aggregation": {
        "Expression": {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                                  "Property": prop}},
        "Function": func}}


# Raw snake_case column names are what a reader sees on an axis title, a legend and every
# table header. "median_gap_pp" and "share_fare_above_cpi" are not English. Anything shown
# in a visual gets a display name here.
FRIENDLY = {
    "metric": "Cost", "label": "Cost", "metric_code": "Cost code",
    "month_label": "Month", "observation_month": "Month",
    "state_name": "Jurisdiction", "zone_name": "Zone", "jurisdiction": "Jurisdiction",
    "cost_family": "Cost family",
    "pct_change": "Change over the window, %",
    "spread_ngn": "Spread, NGN", "dearest_over_cheapest": "Dearest / cheapest",
    "rank_stable": "Order persists?", "cheapest_ngn": "Cheapest, NGN",
    "dearest_ngn": "Dearest, NGN",
    "modes_dear": "Modes dear", "modes_cheap": "Modes cheap", "modes": "Which modes",
    "observations": "Observations", "jurisdictions": "Jurisdictions",
    "median_abs_pct": "Typical monthly move, %",
    "p75_abs_pct": "Upper quartile move, %",
    "elevated_p90_abs_pct": "ELEVATED level (p90), %",
    "extreme_p95_abs_pct": "EXTREME level (p95), %",
    "worst_rise_pct": "Worst rise, %", "worst_fall_pct": "Worst fall, %",
    "share_fare_rose_pct": "Fare rose although petrol fell, %",
    "median_fare_yoy": "Fare change YoY, %", "median_cpi_yoy": "CPI change YoY, %",
    "median_gap_pp": "Gap, percentage points",
    "share_fare_above_cpi": "Share where fare beat CPI",
    "mean_premium_pct_vs_national": "Premium vs national, %",
    "median_premium_pct": "Median premium, %",
    "north_premium_pct": "North minus South premium, %",
    "multiple_of_reference_tariff": "Multiple of the July 2025 tariff",
    "genset_kwh_per_litre": "Generator efficiency, kWh/litre",
    "total_cost_impact_pp_per_1pp_share": "Impact, pp per 1pp of cost share",
    "item": "Item", "value": "Value", "note": "Note",
    "rule_id": "Rule", "rule": "What the rule says", "why": "Why",
    "missing_month": "Missing month", "states_missing": "Jurisdictions affected",
    "dataset": "Dataset", "first_month": "First month", "last_month": "Last month",
    "months": "Months", "rows": "Rows",
    "jurisdictions_flagged_extreme": "Jurisdictions flagged EXTREME",
    "archetype": "Archetype",
    "section": "Question", "body": "Answer from this dataset",
    "part": "What decides whether a location suits a business",
    "examples": "Examples", "in_nbci": "Is it in NBCI?",
    "headline": "Finding", "question": "Business question", "found": "What we found",
    "matters": "Why it matters", "who": "Who should pay attention",
    "costs": "Which NBCI costs matter", "signals": "What the data shows",
    "why": "Why that matters operationally", "needed": "Company data still needed",
}


def friendly(prop: str) -> str:
    return FRIENDLY.get(prop, prop.replace("_", " ").capitalize())


def proj(field: dict, entity: str, prop: str, active: bool | None = None) -> dict:
    p = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop,
         "displayName": friendly(prop)}
    if active is not None:
        p["active"] = active
    return p


def container(name: str, x: float, y: float, w: float, h: float, z: int,
              visual: dict, tab: int = 0) -> dict:
    return {
        "$schema": SCHEMA_VISUAL,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": tab},
        "visual": visual,
    }


def chrome(title: str | None = None, *, background: bool = False,
           border: bool = False) -> dict:
    """Container chrome. Titles are switched off unless explicitly wanted, because the
    page already carries its own typographic headings."""
    o: dict = {
        "title": [{"properties": {"show": lit("true" if title else "false")}}],
        "background": [{"properties": {"show": lit("true" if background else "false")}}],
        "border": [{"properties": {"show": lit("true" if border else "false")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
    }
    if title:
        o["title"] = [{"properties": {
            "show": lit("true"),
            "text": s_lit(title),
            "fontSize": lit("10D"),
            "fontColor": {"solid": {"color": s_lit(MUTED)}},
        }}]
    return o


def textbox(name: str, x, y, w, h, paragraphs: list, z: int = 1000) -> dict:
    return container(name, x, y, w, h, z, {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
        "visualContainerObjects": chrome(),
    })


def para(runs: list[tuple[str, dict]]) -> dict:
    return {"textRuns": [{"value": v, "textStyle": st} for v, st in runs]}


def style(size="9pt", weight="normal", color=INK, italic=False) -> dict:
    st = {"fontFamily": "Segoe UI", "fontSize": size, "fontWeight": weight, "color": color}
    if italic:
        st["fontStyle"] = "italic"
    return st


def card(name: str, x, y, w, h, entity: str, measure: str, label: str, z: int = 100,
         font: int = 20) -> dict:
    """A KPI card.

    Three formatting problems this fixes, all found by looking at the rendered report:
      * the measure NAME was printed inside the card as well as the container title, so
        every card carried its label twice;
      * the callout auto-abbreviated, turning 29,032 into "29K";
      * the default font is large enough that "158.16%" and
        "Not named - order unstable over time" were clipped to "158.16..." and "Not nam...".

    `objects` is a free-form map in the schema, so the two naming conventions are both
    emitted - `calloutValue`/`categoryLabel` for `cardVisual` and `labels`/`categoryLabels`
    for the classic card. Whichever the visual does not recognise is ignored.
    """
    return container(name, x, y, w, h, z, {
        # The CLASSIC `card` (role `Values`), not the newer `cardVisual` (role `Data`).
        # cardVisual ignored every formatting object tried against it - the callout stayed
        # at its default size and kept clipping "158.16%" to "158.16...", and its internal
        # label kept printing under the container title. The classic card's `labels` and
        # `categoryLabels` objects are long-established and do take effect.
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [
            proj(mea(entity, measure), entity, measure)]}}},
        "objects": {
            "labels": [{"properties": {
                "fontSize": lit(f"{font}D"),
                "labelDisplayUnits": lit("1D"),   # 1 = None. 0 is Auto, i.e. "29K".
                # No labelPrecision: forcing 2 decimals printed counts as "37.00" and
                # "110.00". Each measure's own formatString already sets its precision.
            }}],
            # The container title already names the card; the built-in category label
            # would print the same thing again underneath it.
            "categoryLabels": [{"properties": {"show": lit("false")}}],
            "wordWrap": [{"properties": {"show": lit("true")}}],
        },
        "visualContainerObjects": chrome(label, background=True, border=True),
        "drillFilterOtherVisuals": True,
    })


def multi_row_card(name: str, x, y, w, h, entity: str,
                   fields: list[tuple[str, str]], title: str, z: int = 100) -> dict:
    """Several labelled text fields for the selected row, with the text WRAPPED.

    `cardVisual` renders one value in callout type and clips it, which turned every
    archetype paragraph into a truncated headline ("Put a haulage..."). A multi-row card
    is the visual designed for "show these fields for the selected item" and wraps.
    fields are (column, displayName).
    """
    return container(name, x, y, w, h, z, {
        "visualType": "multiRowCard",
        "query": {"queryState": {"Values": {"projections": [
            {"field": col(entity, c), "queryRef": f"{entity}.{c}",
             "nativeQueryRef": c, "displayName": d} for c, d in fields]}}},
        "objects": {
            "card": [{"properties": {"outline": s_lit("None")}}],
            "dataLabels": [{"properties": {"fontSize": lit("9D")}}],
            "categoryLabels": [{"properties": {"fontSize": lit("9D")}}],
        },
        "visualContainerObjects": chrome(title, background=True, border=True),
        "drillFilterOtherVisuals": True,
    })


# ---------------------------------------------------------------------------
# Filters
#
# Inside a filter's `Where` the SourceRef uses **Source** - the alias declared in the
# filter's `From` array - not `Entity`. Using `Entity` here silently matches nothing.
# ---------------------------------------------------------------------------
def in_filter(entity: str, prop: str, values: list[str], alias: str = "f") -> dict:
    return {
        "Version": 2,
        "From": [{"Name": alias, "Entity": entity, "Type": 0}],
        "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {
                "Expression": {"SourceRef": {"Source": alias}}, "Property": prop}}],
            "Values": [[{"Literal": {"Value": "'" + v.replace("'", "''") + "'"}}]
                       for v in values],
        }}}],
    }


def page_filter(name: str, entity: str, prop: str, values: list[str],
                display: str | None = None) -> dict:
    """A page-level categorical filter, locked and hidden.

    WHY THESE PAGES ARE FILTERED RATHER THAN LEFT OPEN: with no metric restriction, a
    card showing [Latest Median Value] on the Fuel page computes a median across petrol,
    LPG, transport fares AND CPI percentages at once - different units in one number,
    which rules G1, G6 and G8 exist to prevent. The filter is locked so a reader cannot
    reintroduce the mix by accident.
    """
    return {
        "name": name,
        "field": col(entity, prop),
        "type": "Categorical",
        "filter": in_filter(entity, prop, values),
        "howCreated": "Auto",
        "isLockedInViewMode": True,
        "isHiddenInViewMode": True,
        "displayName": display or prop,
    }


def slicer_default(entity: str, prop: str, values: list[str]) -> dict:
    """A slicer's pre-selected value.

    This goes in `objects.general.properties.filter`, NOT in `filterConfig`:
    `filterConfig` filters the data FEEDING the slicer, whereas this is what is selected
    in it.
    """
    return {"filter": {"filter": in_filter(entity, prop, values, alias="s")}}


def y_field(entity: str, prop: str, is_measure: bool) -> tuple[dict, str, str, str]:
    """(field, queryRef, nativeQueryRef, displayName) for a value-role projection."""
    if is_measure:
        return mea(entity, prop), f"{entity}.{prop}", prop, prop
    return agg(entity, prop), f"Sum({entity}.{prop})", f"Sum of {prop}", friendly(prop)


def chart(name: str, vtype: str, x, y, w, h, *, category: tuple[str, str, bool] | None,
          ys: list[tuple[str, str, bool]], title: str,
          series: tuple[str, str] | None = None, z: int = 50,
          sort_dir: str | None = None) -> dict:
    """ys entries are (entity, property, is_measure). Sorting is by the first Y."""
    qs: dict = {}
    if category:
        e, p, is_m = category
        qs["Category"] = {"projections": [
            proj(mea(e, p) if is_m else col(e, p), e, p, active=True)]}

    y_projections = []
    first_y = None
    for e, p, is_m in ys:
        f, qref, nref, disp = y_field(e, p, is_m)
        if first_y is None:
            first_y = f
        y_projections.append({"field": f, "queryRef": qref, "nativeQueryRef": nref,
                              "displayName": disp})
    qs["Y"] = {"projections": y_projections}

    if series:
        e, p = series
        qs["Series"] = {"projections": [proj(col(e, p), e, p)]}

    v: dict = {
        "visualType": vtype,
        "query": {"queryState": qs},
        # Axis titles are switched off: they rendered the raw column name
        # ("pct_change", "month_label") under charts whose own title already says what
        # is plotted. One label, not two.
        "objects": {
            "categoryAxis": [{"properties": {"showAxisTitle": lit("false")}}],
            "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}],
        },
        "visualContainerObjects": chrome(title, background=True, border=True),
        "drillFilterOtherVisuals": True,
    }
    if sort_dir and first_y is not None:
        # Sort by the same expression that is plotted - a sort naming a bare column while
        # the chart plots its aggregate does not bind.
        v["query"]["sortDefinition"] = {
            "sort": [{"field": first_y, "direction": sort_dir}]}
    return container(name, x, y, w, h, z, v)


def table(name: str, x, y, w, h, fields: list[tuple[str, str, bool]], title: str,
          z: int = 50, sort: tuple[dict, str] | None = None,
          wrap: bool = False, widths: dict[str, int] | None = None) -> dict:
    q: dict = {"queryState": {"Values": {"projections": [
        proj(mea(e, p) if is_m else col(e, p), e, p) for e, p, is_m in fields]}}}
    if sort:
        field, direction = sort
        q["sortDefinition"] = {"sort": [{"field": field, "direction": direction}]}
    objects: dict = {}
    if wrap:
        # Word wrap must be turned on for BOTH the values and the column headers, or a
        # paragraph renders as one clipped line. This is the only Power BI visual that
        # will wrap long text bound to a slicer selection.
        objects["values"] = [{"properties": {
            "wordWrap": lit("true"), "fontSize": lit("9D")}}]
        objects["columnHeaders"] = [{"properties": {
            "wordWrap": lit("true"), "fontSize": lit("9D")}}]
    if widths:
        objects["columnWidth"] = [
            {"properties": {"value": lit(f"{px}D")},
             "selector": {"metadata": ref}}
            for ref, px in widths.items()
        ]
    vis: dict = {
        "visualType": "tableEx",
        "query": q,
        "visualContainerObjects": chrome(title, background=True, border=True),
        "drillFilterOtherVisuals": True,
    }
    if objects:
        vis["objects"] = objects
    return container(name, x, y, w, h, z, vis)


def slicer(name: str, x, y, w, h, entity: str, prop: str, title: str,
           horizontal: bool = False, z: int = 5000,
           default: list[str] | None = None) -> dict:
    v: dict = {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [
            proj(col(entity, prop), entity, prop, active=True)]}}},
        "visualContainerObjects": chrome(title, background=True, border=True),
    }
    props: dict = {}
    if horizontal:
        props["orientation"] = lit("1D")
    if default:
        props.update(slicer_default(entity, prop, default))
    if props:
        v["objects"] = {"general": [{"properties": props}]}
    return container(name, x, y, w, h, z, v)


# ---------------------------------------------------------------------------
# the four-part narrative band
# ---------------------------------------------------------------------------
BAND_LABELS = [
    ("Signal", "signal", "What does the data show?", ACCENT),
    ("What it means", "meaning", "The business implication", ACCENT),
    ("What to review", "review", "What deserves attention", ACCENT),
    ("Boundary", "boundary", "What this data cannot tell us", WARN),
]


def narrative_band(page_key: str, n: dict, y: int) -> list[dict]:
    """Four boxes across the page, generated from the same constants as the model table."""
    out = []
    w, gap = 302, 8
    for i, (heading, field, sub, colour) in enumerate(BAND_LABELS):
        x = 24 + i * (w + gap)
        out.append(textbox(
            vid(page_key, "band", field), x, y, w, 188,
            [
                para([(heading.upper(), style("9pt", "700", colour))]),
                para([(sub, style("8pt", "normal", MUTED, italic=True))]),
                para([("", style("6pt"))]),
                para([(n[field], style("9pt", "normal", INK))]),
            ],
            z=1000 + i,
        ))
    return out


def page_header(page_key: str, title: str, kicker: str) -> list[dict]:
    return [
        textbox(vid(page_key, "title"), 24, 16, 1232, 44,
                [para([(title, style("22pt", "600", INK))])], z=2000),
        textbox(vid(page_key, "kicker"), 24, 60, 1232, 30,
                [para([(kicker, style("9.5pt", "normal", MUTED))])], z=2001),
    ]


# ---------------------------------------------------------------------------
# page builders
# ---------------------------------------------------------------------------
def scope_strip(page_key: str, y: int, fnd) -> list[dict]:
    """What NBCI measures, and what it does NOT.

    This is the single most important thing on the report. Without it a reader draws the
    one conclusion the data cannot support - that a jurisdiction with a lower measured
    cost is a better place to do business.
    """
    return [
        textbox(vid(page_key, "scope_is"), 24, y, 610, 104, [
            para([("WHAT THIS MEASURES", style("9pt", "700", ACCENT))]),
            para([("", style("4pt"))]),
            para([(fnd.WHAT_THIS_IS, style("9pt", "normal", INK))]),
        ], z=1500),
        textbox(vid(page_key, "scope_not"), 646, y, 610, 104, [
            para([("WHAT IT DOES NOT MEASURE", style("9pt", "700", WARN))]),
            para([("", style("4pt"))]),
            para([(fnd.WHAT_THIS_IS_NOT, style("9pt", "normal", INK))]),
        ], z=1501),
    ]


def capability_strip(page_key: str, y: int, fnd) -> list[dict]:
    """What this project CAN and CANNOT do today, side by side.

    The scope strip says what is measured. This says what can be concluded from it. The
    two are different questions and a reader who gets the first right can still get the
    second wrong - the classic version being "so tell me which state to move to".
    """
    bullets = lambda items, colour: [
        para([(f"•  {s}", style("8.5pt", "normal", colour))]) for s in items]
    return [
        textbox(vid(page_key, "cap_can"), 24, y, 610, 184, [
            para([("WHAT THIS CAN TELL YOU TODAY", style("9pt", "700", ACCENT))]),
            para([("", style("4pt"))]),
            *bullets(fnd.CAN_DO, INK),
        ], z=1520),
        textbox(vid(page_key, "cap_cannot"), 646, y, 610, 184, [
            para([("WHAT IT CANNOT TELL YOU TODAY", style("9pt", "700", WARN))]),
            para([("", style("4pt"))]),
            *bullets(fnd.CANNOT_DO, INK),
        ], z=1521),
    ]


def boundary_strip(page_key: str, y: int, fnd, w: int = 1232) -> dict:
    return textbox(vid(page_key, "oneline"), 24, y, w, 112, [
        para([("BEFORE YOU ACT ON ANY OF THIS", style("9pt", "700", WARN))]),
        para([("", style("4pt"))]),
        para([(fnd.ONE_LINE, style("10pt", "600", INK))]),
        para([(fnd.WHY_NOT, style("8.5pt", "normal", MUTED))]),
    ], z=1600)


def build_pages(narr: dict, fnd) -> list[dict]:
    """Seven pages, each named for the business question it answers.

    The previous structure was organised by DATASET - Fuel, Transport, CPI - which is how
    an analyst thinks about the sources, not how an owner thinks about the business. The
    analytical detail still exists; it now sits behind a question.
    """
    pages: list[dict] = []

    # ================= 1. What is changing? ==============================
    # The explanation layer. No KPI cards and no chart: every number a reader needs is
    # stated inside the finding that uses it, and a chart here would be a second thing
    # to interpret rather than a first thing to read.
    k = "whatschanging"
    v: list[dict] = []
    v += [
        textbox(vid(k, "title"), 24, 16, 1232, 42,
                [para([("What is changing in the costs businesses pay?",
                        style("21pt", "600", INK))])], z=2000),
        textbox(vid(k, "sub"), 24, 58, 1232, 34,
                [para([(fnd.SIMPLE_DESCRIPTION, style("9.5pt", "normal", MUTED))])],
                z=2001),
    ]
    v += scope_strip(k, 98, fnd)
    v += capability_strip(k, 208, fnd)
    v.append(table(vid(k, "equation"), 24, 402, 1232, 148,
                   [("ref_scope", "part", False),
                    ("ref_scope", "examples", False),
                    ("ref_scope", "in_nbci", False)],
                   "Whether a place suits a business depends on all four of these. This "
                   "project covers part of one of them",
                   sort=(col("ref_scope", "part_order"), "Ascending"), wrap=True,
                   widths={"ref_scope.part": 260, "ref_scope.examples": 560,
                           "ref_scope.in_nbci": 380}))

    v.append(textbox(vid(k, "attn_h"), 24, 564, 1232, 32,
                     [para([("What should I pay attention to?",
                             style("15pt", "600", INK))])], z=2002))

    bw, bh, gap = 404, 132, 10
    for i, f in enumerate(fnd.FINDINGS):
        cx = 24 + (i % 3) * (bw + gap)
        cy = 602 + (i // 3) * (bh + gap)
        v.append(textbox(
            vid(k, "f", str(f["rank"])), cx, cy, bw, bh,
            [
                para([(f"{f['rank']}. {f['headline']}", style("9.5pt", "700", ACCENT))]),
                para([("", style("3pt"))]),
                para([(f["found"], style("8pt", "normal", INK))]),
            ], z=1000 + i))

    v.append(slicer(vid(k, "sl"), 24, 892, 1232, 84, "ref_finding", "headline",
                    "Open a finding to read why it matters, who should look, and what it "
                    "cannot prove", horizontal=True,
                    default=[fnd.FINDINGS[0]["headline"]]))
    v.append(table(vid(k, "detail"), 24, 986, 1232, 286,
                   [("ref_finding_section", "section", False),
                    ("ref_finding_section", "body", False)],
                   "The selected finding, in full",
                   sort=(col("ref_finding_section", "section_order"), "Ascending"),
                   wrap=True,
                   widths={"ref_finding_section.section": 250,
                           "ref_finding_section.body": 930}))
    v.append(boundary_strip(k, 1284, fnd))
    pages.append({"name": k, "displayName": "What is changing?", "height": 1408,
                  "visuals": v})

    # ================= 2. Fuel and energy ================================
    k = "fuelenergy"
    v = []
    v += page_header(k, "What am I paying for fuel and power?",
                     "Petrol, diesel and LPG, plus diesel self-generation against a fixed "
                     "July 2025 electricity benchmark. Cylinder sizes are separate series "
                     "and are never averaged (G8). LPG ends 2026-04.")
    v += [
        slicer(vid(k, "sl_metric"), 24, 100, 300, 128, "dim_metric", "metric",
               "Cost (one at a time - these have different units)",
               default=["Diesel (NGN/l)"]),
        card(vid(k, "c1"), 334, 100, 226, 104, "fact_cost", "Latest Median Value",
             "Latest median across 37 jurisdictions"),
        card(vid(k, "c2"), 570, 100, 226, 104, "ref_location_value", "Spread NGN (evidence)",
             "The gap between the cheapest and dearest place, April 2026"),
        card(vid(k, "c3"), 806, 100, 226, 104, "ref_location_value",
             "Dearest over Cheapest (evidence)",
             "How many times more the dearest place pays, April 2026"),
        card(vid(k, "c4"), 1042, 100, 214, 104, "ref_flag_level", "EXTREME Level %",
             "How big a monthly move has to be to count as EXTREME"),
    ]
    v += [
        chart(vid(k, "line"), "lineChart", 24, 244, 760, 266,
              category=("dim_date", "month_label", False),
              ys=[("fact_cost", "Median Value", True)],
              series=("dim_metric", "metric"),
              title="Every fuel cost here ended the period higher than it started. "
                    "Middle value across the 37 jurisdictions each month, each one "
                    "counted equally. This is not a national average"),
        table(vid(k, "tbl"), 794, 244, 462, 266,
              [("dim_metric", "metric", False),
               ("ref_location_value", "spread_ngn", False),
               ("ref_location_value", "dearest_over_cheapest", False),
               ("dim_metric", "rank_stable", False)],
              "Moving somewhere else barely changes what you pay for fuel. The gap "
              "between the dearest and cheapest jurisdiction, and whether that order "
              "holds from one month to the next"),
    ]
    v.append(chart(vid(k, "selfgen"), "lineChart", 24, 522, 1232, 254,
                   category=("dim_date", "month_label", False),
                   ys=[("ref_selfgen", "multiple_of_reference_tariff", False)],
                   series=("ref_selfgen", "genset_kwh_per_litre"),
                   title="Running a generator never came out cheaper than grid power. "
                         "Diesel self-generation shown as a multiple of the fixed July 2025 "
                         "Band A tariff of NGN 209.50/kWh, by generator efficiency. The line "
                         "never drops below 1.0, so the generator is cover for outages, not "
                         "a cheaper supply"))
    v += narrative_band(k, narr["Fuel and energy"], 792)
    pages.append({"name": k, "displayName": "Fuel and energy", "height": 1000, "visuals": v,
                  "filters": [page_filter("fuel_family", "dim_metric", "cost_family",
                                          ["Fuel", "LPG"], "Cost family")],
                  "interactions": [
                      {"source": vid(k, "sl_metric"), "target": vid(k, "tbl"),
                       "type": "NoFilter"},
                      {"source": vid(k, "sl_metric"), "target": vid(k, "selfgen"),
                       "type": "NoFilter"},
                  ]})

    # ================= 3. Moving people and goods ========================
    k = "mobility"
    v = []
    v += page_header(k, "What am I paying to move people and goods?",
                     "Passenger fares, not freight rates. Modes are never combined or "
                     "averaged (G6). Air and intercity bus are inter-regional services, "
                     "not local mobility (G7).")
    v += [
        slicer(vid(k, "sl_mode"), 24, 100, 300, 128, "dim_metric", "metric",
               "Mode (one at a time - no 'all modes' total exists, G6)",
               default=["Okada (NGN)"]),
        card(vid(k, "c1"), 334, 100, 300, 104, "fact_cost", "Latest Median Value",
             "Latest median fare across 37 jurisdictions"),
        card(vid(k, "c2"), 644, 100, 300, 104, "ref_fare_ratchet", "Share Fare Rose %",
             "Fare ROSE although petrol was cheaper year-on-year"),
        card(vid(k, "c3"), 954, 100, 302, 104, "ref_location_value",
             "Dearest over Cheapest (evidence)",
             "How many times more the dearest place pays, April 2026"),
    ]
    v += [
        chart(vid(k, "line"), "lineChart", 24, 244, 760, 266,
              category=("dim_date", "month_label", False),
              ys=[("fact_cost", "Median Value", True)],
              series=("dim_metric", "metric"),
              title="Fares went up and did not come back down. Middle fare across the "
                    "37 jurisdictions each month for the mode you pick. Modes are never "
                    "added together, because a journey by air and a journey by okada "
                    "are different things"),
        chart(vid(k, "ratchet"), "clusteredBarChart", 794, 244, 462, 266,
              category=("ref_fare_ratchet", "label", False),
              ys=[("ref_fare_ratchet", "share_fare_rose_pct", False)],
              title="Fares still went up even when petrol got cheaper, and this happened "
                    "for every mode. Share of observations where the fare rose although "
                    "petrol cost less than a year earlier",
              sort_dir="Descending"),
    ]
    v.append(table(vid(k, "vs_cpi"), 24, 522, 1232, 254,
                   [("ref_fare_vs_cpi", "label", False),
                    ("ref_fare_vs_cpi", "median_fare_yoy", False),
                    ("ref_fare_vs_cpi", "median_cpi_yoy", False),
                    ("ref_fare_vs_cpi", "median_gap_pp", False),
                    ("ref_fare_vs_cpi", "share_fare_above_cpi", False)],
                   "Fares rose far faster than the inflation rate in the news. Fare "
                   "growth against inflation, matched jurisdiction by jurisdiction and "
                   "month by month. A transport allowance raised by inflation alone would "
                   "have fallen behind by this gap. Only 4 months can be compared this "
                   "way; 2026-02 is missing at source and is left out, never filled in"))
    v += narrative_band(k, narr["Moving people and goods"], 792)
    pages.append({"name": k, "displayName": "Moving people and goods", "height": 1000,
                  "visuals": v,
                  "filters": [page_filter("transport_family", "dim_metric", "cost_family",
                                          ["Transport"], "Cost family")],
                  "interactions": [
                      {"source": vid(k, "sl_mode"), "target": vid(k, "ratchet"),
                       "type": "NoFilter"},
                      {"source": vid(k, "sl_mode"), "target": vid(k, "vs_cpi"),
                       "type": "NoFilter"},
                  ]})

    # ================= 4. Where costs differ =============================
    # The page most likely to be misread, so the reframing is the first thing on it.
    k = "wherecostsdiffer"
    v = []
    v += page_header(k, fnd.LOCATION_FRAMING["question"],
                     "This page does not answer '" + fnd.LOCATION_FRAMING["not_question"]
                     + "'. It compares prices and nothing else. A cheaper place is not a "
                     "better one, a dearer place is not a worse one, and a dearer place "
                     "does not mean a business loses money there.")
    v.append(textbox(vid(k, "framing"), 24, 100, 1232, 112, [
        para([("HOW TO READ EVERY COMPARISON ON THIS PAGE", style("9pt", "700", WARN))]),
        para([("", style("3pt"))]),
        para([(fnd.LOCATION_FRAMING["one_factor"], style("9pt", "600", INK))]),
        para([(fnd.LOCATION_FRAMING["rule"], style("8.5pt", "normal", INK))]),
        para([(fnd.LOCATION_FRAMING["stability"], style("8.5pt", "normal", MUTED))]),
    ], z=1500))
    v += [
        card(vid(k, "c1"), 24, 228, 300, 104, "ref_location_value",
             "Water Location Ratio",
             "Water fares: the dearest place costs this many times the cheapest (2026-04)"),
        card(vid(k, "c2"), 334, 228, 300, 104, "ref_location_value",
             "Petrol Location Ratio",
             "Petrol: the dearest place costs this many times the cheapest (2026-04)"),
        card(vid(k, "c3"), 644, 228, 300, 104, "fact_cost", "Dearest Water Jurisdiction",
             "Highest measured water fare. This order holds month to month, so it can "
             "be named", font=15),
        card(vid(k, "c4"), 954, 228, 302, 104, "fact_cost", "Dearest Petrol Jurisdiction",
             "Highest measured petrol price. This order keeps changing, so no name "
             "is given",
             font=11),
    ]
    v += [
        chart(vid(k, "spread"), "clusteredBarChart", 24, 372, 620, 300,
              category=("ref_location_value", "label", False),
              ys=[("ref_location_value", "dearest_over_cheapest", False)],
              title="Where you are matters a lot for some costs and hardly at all for "
                    "others. How many times more the dearest jurisdiction pays than the "
                    "cheapest, for each of the nine costs",
              sort_dir="Descending"),
        table(vid(k, "persist"), 654, 372, 602, 300,
              [("ref_mobility_dear", "state_name", False),
               ("ref_mobility_dear", "zone_name", False),
               ("ref_mobility_dear", "modes", False)],
              "These places consistently have the highest local fares. Always name the "
              "mode, not just the place. This is not a ranking of which place is "
              "better for business"),
    ]
    v += [
        chart(vid(k, "food"), "clusteredBarChart", 24, 686, 620, 254,
              category=("ref_food_zone", "zone_name", False),
              ys=[("ref_food_zone", "mean_premium_pct_vs_national", False)],
              title="Food costs more in some parts of the country than others. How much "
                    "each zone pays above or below the national figure, %. Six zones only, "
                    "because the source publishes no state-level food prices at all",
              sort_dir="Descending"),
        table(vid(k, "cheap"), 654, 686, 602, 254,
              [("ref_mobility_cheap", "state_name", False),
               ("ref_mobility_cheap", "zone_name", False),
               ("ref_mobility_cheap", "modes", False)],
              "These places consistently have the lowest local fares. A lower fare is "
              "not evidence that a place is better to do business in"),
    ]
    v += narrative_band(k, narr["Where costs differ"], 956)
    v.append(boundary_strip(k, 1152, fnd))
    pages.append({"name": k, "displayName": "Where costs differ", "height": 1280,
                  "visuals": v})

    # ================= 5. How unusual is this month? =====================
    k = "howunusual"
    v = []
    v += page_header(k, "Is this month's price move unusual?",
                     "Flags are DESCRIPTIVE, not action triggers (G13). They say how "
                     "unusual a month is against that series' own 518-observation history, "
                     "and nothing about whether it reaches your margin.")
    v += [
        card(vid(k, "c1"), 24, 100, 300, 104, "ref_flag_level",
             "Diesel ELEVATED Level %",
             "How big a monthly diesel move has to be to count as ELEVATED"),
        card(vid(k, "c2"), 334, 100, 300, 104, "ref_flag_level",
             "Diesel EXTREME Level %",
             "How big a monthly diesel move has to be to count as EXTREME"),
        card(vid(k, "c3"), 644, 100, 300, 104, "fact_extreme_flag",
             "Peak Jurisdictions Flagged EXTREME",
             "The worst single month: how many places were flagged at once"),
        card(vid(k, "c4"), 954, 100, 302, 104, "ref_selfgen",
             "Self-gen Multiple Latest",
             "What a generator cost in May 2026 against grid power, at 3 units per litre"),
    ]
    v += [
        table(vid(k, "levels"), 24, 244, 620, 310,
              [("ref_flag_level", "label", False),
               ("ref_flag_level", "median_abs_pct", False),
               ("ref_flag_level", "elevated_p90_abs_pct", False),
               ("ref_flag_level", "extreme_p95_abs_pct", False)],
              "How big a monthly move has to be before it counts as unusual, cost by "
              "cost. Each level is set from that cost's own past, from more than 500 "
              "readings"),
        chart(vid(k, "flags"), "clusteredBarChart", 654, 244, 602, 310,
              category=("dim_date", "month_label", False),
              ys=[("fact_extreme_flag", "Jurisdictions Flagged EXTREME", True)],
              series=("dim_metric", "metric"),
              title="Unusual months arrive in clusters, not evenly. How many jurisdictions "
                    "were flagged EXTREME each month. When most are flagged at once it is "
                    "a nationwide condition, not a local one"),
    ]
    v.append(chart(vid(k, "exposure"), "clusteredBarChart", 24, 568, 1232, 254,
                   category=("ref_exposure", "label", False),
                   ys=[("ref_exposure", "total_cost_impact_pp_per_1pp_share", False)],
                   title="How hard a price rise hits you depends on how much of that cost you "
                         "buy. This is the effect on total cost for every 1% of your own "
                         "spending that goes on it. Multiply it by your own share, because "
                         "this project holds no company figures",
                   sort_dir="Descending"))
    v += narrative_band(k, narr["How unusual is this month?"], 838)
    pages.append({"name": k, "displayName": "How unusual is this month?", "height": 1044,
                  "visuals": v})

    # ================= 6. Which businesses are exposed? ==================
    k = "whoisexposed"
    v = []
    v += page_header(k, "Which kinds of business does this matter more for?",
                     "Pick the closest kind of business. Each answers six questions, "
                     "ending with the company figures you would still need before any "
                     "real decision, because this project cannot supply them.")
    v.append(slicer(vid(k, "sl"), 24, 100, 1232, 76, "ref_archetype", "archetype",
                    "Kind of business (one at a time)", horizontal=True,
                    default=[fnd.ARCHETYPES[0]["archetype"]]))
    v.append(table(vid(k, "sections"), 24, 190, 1232, 410,
                   [("ref_archetype_section", "section", False),
                    ("ref_archetype_section", "body", False)],
                   "The six questions, answered for the kind of business you picked",
                   sort=(col("ref_archetype_section", "section_order"), "Ascending"),
                   wrap=True,
                   widths={"ref_archetype_section.section": 260,
                           "ref_archetype_section.body": 930}))
    v.append(chart(vid(k, "exposure"), "clusteredBarChart", 24, 614, 1232, 220,
                   category=("ref_exposure", "label", False),
                   ys=[("ref_exposure", "total_cost_impact_pp_per_1pp_share", False)],
                   title="The same price rise hurts different businesses by different amounts. "
                         "Effect on total cost for every 1% of spending that goes on each "
                         "cost. Apply your own shares",
                   sort_dir="Descending"))
    v += narrative_band(k, narr["Who this matters more for"], 850)
    pages.append({"name": k, "displayName": "Who this matters more for", "height": 1056,
                  "visuals": v,
                  "interactions": [
                      {"source": vid(k, "sl"), "target": vid(k, "exposure"),
                       "type": "NoFilter"},
                  ]})

    # ================= 7. Can I trust this? ==============================
    k = "canitrust"
    v = []
    v += page_header(k, "Can I trust this, and what are its limits?",
                     "Validation proves PIPELINE FIDELITY - that the numbers here match "
                     "what NBS, CBN and NERC published. It does NOT validate the sources "
                     "themselves. Published source defects are carried and flagged, never "
                     "silently corrected.")
    v += [
        card(vid(k, "c1"), 24, 100, 300, 104, "ref_methodology", "Validation Checks Passed",
             "Validation checks passed"),
        card(vid(k, "c2"), 334, 100, 300, 104, "ref_methodology", "Raw Files Verified",
             "Raw source files SHA-256 verified"),
        card(vid(k, "c3"), 644, 100, 300, 104, "ref_methodology", "Fact Rows in Database",
             "Fact rows in the database"),
        card(vid(k, "c4"), 954, 100, 302, 104, "ref_methodology", "Panel Grain Duplicates",
             "Panel grain duplicates"),
    ]
    v += [
        table(vid(k, "facts"), 24, 244, 620, 300,
              [("ref_methodology", "item", False),
               ("ref_methodology", "value", False),
               ("ref_methodology", "note", False)],
              "How this was built, and how it was checked"),
        table(vid(k, "rules"), 654, 244, 602, 300,
              [("ref_rule", "rule_id", False),
               ("ref_rule", "rule", False)],
              "The 15 rules every page on this report has to obey",
              sort=(col("ref_rule", "rule_no"), "Ascending")),
    ]
    v += [
        table(vid(k, "gaps"), 24, 556, 620, 220,
              [("ref_named_gaps", "metric_code", False),
               ("ref_named_gaps", "missing_month", False),
               ("ref_named_gaps", "states_missing", False)],
              "Months that are genuinely missing from the government sources. They are "
              "left empty, never filled in with a guess (G11)"),
        table(vid(k, "coverage"), 654, 556, 602, 220,
              [("ref_coverage", "dataset", False),
               ("ref_coverage", "first_month", False),
               ("ref_coverage", "last_month", False),
               ("ref_coverage", "rows", False)],
              "What period each dataset covers. They do not all end in the same month (G14)"),
    ]
    v.append(table(vid(k, "capability"), 24, 788, 1232, 300,
                   [("ref_capability", "direction", False),
                    ("ref_capability", "capability", False)],
                   "What this project can and cannot tell you today",
                   sort=(col("ref_capability", "capability_order"), "Ascending"),
                   wrap=True,
                   widths={"ref_capability.direction": 260,
                           "ref_capability.capability": 920}))
    v.append(textbox(vid(k, "future"), 24, 1100, 1232, 92, [
        para([("WHAT A LATER VERSION WOULD NEED", style("9pt", "700", MUTED))]),
        para([("", style("3pt"))]),
        para([(fnd.WHAT_IT_WOULD_TAKE, style("9pt", "normal", INK))]),
    ], z=1530))
    v += narrative_band(k, narr["Can I trust this?"], 1204)
    pages.append({"name": k, "displayName": "Can I trust this?", "height": 1412,
                  "visuals": v})

    return pages


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def write_report() -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pbi_findings
    import pbi_narrative

    narr = {n["page"]: n for n in pbi_narrative.PAGE_NARRATIVE}
    pages = build_pages(narr, pbi_findings)

    if DEF.exists():
        import shutil
        try:
            shutil.rmtree(DEF)
        except PermissionError as exc:
            raise SystemExit(
                "Cannot rewrite the report definition: Power BI Desktop has the project "
                "open and is holding a lock on\n"
                f"  {exc.filename}\n"
                "Close Power BI Desktop and re-run the build. (Desktop also caches the "
                "report in memory, so a rebuild underneath it would not be picked up "
                "anyway.)") from exc

    write_json(DEF / "version.json",
               {"$schema": SCHEMA_VERSION, "version": "2.0.0"})
    write_json(DEF / "report.json", {
        "$schema": SCHEMA_REPORT,
        "themeCollection": {"baseTheme": {
            "name": "CY24SU10",
            "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"},
            "type": "SharedResources",
        }},
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "useEnhancedTooltips": True,
        },
    })
    write_json(DEF / "pages" / "pages.json", {
        "$schema": SCHEMA_PAGES,
        "pageOrder": [p["name"] for p in pages],
        "activePageName": pages[0]["name"],
    })

    n_visuals = 0
    for p in pages:
        page_json = {
            "$schema": SCHEMA_PAGE,
            "name": p["name"],
            "displayName": p["displayName"],
            "displayOption": "FitToPage",
            "width": PAGE_W,
            "height": p["height"],
        }
        if p.get("filters"):
            page_json["filterConfig"] = {"filters": p["filters"]}
        if p.get("interactions"):
            page_json["visualInteractions"] = p["interactions"]
        write_json(DEF / "pages" / p["name"] / "page.json", page_json)
        for vis in p["visuals"]:
            write_json(DEF / "pages" / p["name"] / "visuals" / vis["name"] / "visual.json", vis)
            n_visuals += 1

    return {"pages": len(pages), "visuals": n_visuals,
            "detail": [(p["displayName"], len(p["visuals"])) for p in pages]}


if __name__ == "__main__":
    r = write_report()
    for nm, cnt in r["detail"]:
        print(f"  {nm:32s} {cnt:>3} visuals")
    print(f"\n{r['pages']} pages, {r['visuals']} visuals -> {DEF}")
