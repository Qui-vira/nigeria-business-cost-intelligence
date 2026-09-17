# Dashboard Specification

**Phase:** Dashboard specification (pass 04), now also the build record for the two tools that exist
**Builds on:** `e299a68` business decision frameworks · `23cc35a` discovery · `1eaff93` database
**Validation carried forward:** **110 / 110** (a01 64/64 · a02 19/19 · a03 27/27)
**Tools in scope:** Microsoft Excel · Power BI · Tableau · IBM Cognos Analytics
**Status:** Excel **built and validated** (105/105 structural + 25/25 Microsoft Excel compatibility).
Power BI **built and validated** (89/89, all pages inspected rendered). Tableau and Cognos are
specified here but **not built**.

This document contains the six required outputs:

| Part | Output |
|---|---|
| 1 | Dashboard Specification — purpose, audience, global rules, data source |
| 2 | Page-by-page structure — eight themes, eleven defined elements each |
| 3 | KPI dictionary |
| 4 | Visual-to-data mapping |
| 5 | Tool-specific implementation plan |
| 6 | Build order |

---

# Part 1 — Dashboard Specification

## 1.1 What these dashboards are for

They answer one question, from a validated evidence base:

> **How are key external business cost pressures changing across Nigeria, how do they differ by
> location where the data supports it, which types of businesses are they likely to matter more
> for, and what should managers monitor or investigate in response?**

The plain-English version, for anything public-facing:

> NBCI shows how important external business costs are changing across Nigeria, which types of
> businesses those costs are likely to matter more for, and what managers should investigate to
> protect their margins.

They are **not** a general Nigeria economics dashboard, not a forecasting tool, and not a
cost-of-doing-business index. Everything shown traces to a committed, validated calculation.

### 1.1.1 The capability boundary — binding, and machine-checked

What these dashboards deliver today is **external cost intelligence, business exposure and guidance
on what to investigate.** They do not deliver company financial data, market data, scenario modelling
or company-specific profitability decisions. That distinction is carried as DATA in the model table
`ref_capability`, shown on two pages of each tool, and asserted by `pbi_validate.ps1` checks D14–D17
and `validate_excel_dashboard.py` layer D. It cannot shrink without a build failure.

| Can, today | Cannot, today |
|---|---|
| Track selected external business cost pressures | Determine whether a specific company is profitable |
| Show how those pressures change over time | Predict whether a company will lose money |
| Compare locations where the source data supports geographic comparison | Identify the universally best jurisdiction to operate in |
| Identify which types of business a particular cost pressure is likely to matter more for | Claim that a cheaper jurisdiction is a better business location |
| Explain why a cost movement may matter to day-to-day operations | Calculate the effect of a cost change on a specific company's margin |
| Show what management should monitor, measure, compare or investigate | Prescribe company-specific actions without financial and market data from that company |
| Provide evidence for further business analysis | |

**The earlier framing asked how the cost of doing business was changing and what businesses should DO
about it.** It was dropped because it overstated all three of its parts: this measures nine bought-in
costs rather than a whole cost base, not every source supports a location comparison, and prescribing
an action for one company would need that company's own margins and market position.

## 1.2 Audience

| Audience | Needs | Served by |
|---|---|---|
| Business owner / operations manager | "What changed, does it affect me, what do I watch" | Pages 1, 6, 7 |
| Analyst / finance | The numbers behind the headline, with grain and window | Pages 2–5 |
| Reviewer / recruiter / data governance | Can this be trusted, what are its limits | Page 8 |

### 1.2.1 The clarity test — binding on every page, chart and finding

**Every major page and finding must be understandable to someone with no knowledge of
economics, statistics, dashboards or data analysis.** Avoid jargon where plain English
works. When a technical term is necessary, explain it immediately. A user should never have
to interpret a chart before understanding its main message.

This is not a request to weaken the analysis. It is a request to build **two layers**:

| Layer | Who it is for | What it holds |
|---|---|---|
| **1. Anyone can understand it** | A business owner with no background | Plain English, a clear conclusion, a simple chart, obvious meaning |
| **2. Analysts can inspect the evidence** | Analyst, finance, reviewer | Exact figures, methodology, calculations, filters, definitions, limits, validation |

Separating communication from technical depth is stronger than simplifying the analysis,
because nothing is lost: the methodology page still carries the full technical explanation.

**A chart title states the conclusion, not the fields.** Not *"Diesel Median Price by
Month"* but *"Diesel became much more expensive over this period"*, with the chart proving
it, then **Why this matters** and **What to check in your business** underneath.

**Worked examples of the standard:**

| Do not write | Write |
|---|---|
| "Geographic dispersion is greater for local mobility metrics" | "Transport costs can differ a lot depending on where you operate" |
| "Rank instability prevents persistent jurisdiction naming" | "The cheapest place changes too often for us to name one as the cheapest over time" |

## 1.3 Geography terminology — binding on every label

The dataset covers **36 states + the Federal Capital Territory = 37 jurisdictions**. The FCT
(`Abuja`) is an administrative territory, not a state. Axis titles, tooltips and card subtitles say
**"37 jurisdictions"** or **"36 states and the FCT"**. They never say "37 states".

## 1.4 Global rules — every page inherits these

These are not stylistic preferences. Each one encodes a finding from the validated analysis, and a
dashboard that breaks one is wrong regardless of how it looks.

| # | Rule | Why |
|---|---|---|
| **G1** | **Never mix geography grains in one visual.** STATE, ZONE and NATIONAL are separate. No aggregate spans them | Fuel facts contain all three; summing them double-counts |
| **G2** | **Never compare CPI index levels between jurisdictions.** Only `CHANGE_MOM_PCT` and `CHANGE_YOY_PCT` are comparable | NBS prints the prohibition in the source; `comparability_warning` is on all 6,512 CPI rows |
| **G3** | **Food is ZONE grain only** — six zones, never 37 jurisdictions | Hard source ceiling; no state-level food prices exist |
| **G4** | **NERC tariffs are DisCo grain and a single July 2025 cross-section.** Never mapped to a jurisdiction, never plotted as a time series | `state_mapping = NOT_MAPPED` on all 525 rows |
| **G5** | **FX is NATIONAL context only.** Never a jurisdiction metric, never on a map | Single national series |
| **G6** | **Transport modes are never combined or averaged.** A mode filter is single-select; there is no "all modes" total | A journey by air and by okada are different products with different units of service |
| **G7** | **Air and intercity bus are inter-regional, not local mobility.** "Local mobility" = okada + intracity bus + water only | a02 V2: 82.6% of air's month-to-month variation is a common national movement |
| **G8** | **LPG cylinder sizes are separate series.** 5 kg and 12.5 kg are never averaged | Different products |
| **G9** | **Rank-stability gate.** For the five metrics whose order is unstable (air, diesel, LPG 5 kg, LPG 12.5 kg, petrol), **spread may be shown but no jurisdiction may be named** as persistently dearest or cheapest. Maps and rank tables are restricted to the four stable metrics | a02 V4. Each monthly rank is a valid snapshot; the order does not persist |
| **G10** | **Primary publications only.** `_latest_restatement` views are out of scope for this build | Mixing publication semantics in one aggregate answers two questions at once |
| **G11** | **Never interpolate across a known gap.** CPI YoY has **no 2026-02 rows**; every YoY line must break, not bridge | Feb 2026 year-ago column is mislabelled; 148 cells excluded upstream |
| **G12** | **No composite cost index.** No weighting, normalising or summing of one cost against another | Normalisation, weighting and component treatment have not been defined or approved |
| **G13** | **Movement flags are descriptive, not action triggers.** ELEVATED / EXTREME describe how unusual a month is against this series' own history | Whether a move matters needs company cost exposure, margin and pass-through — none of which is in this dataset |
| **G14** | **Series end on different months.** LPG ends 2026-04; petrol, diesel and transport end 2026-05; CPI ends 2026-07; FX ends 2026-09. Any cross-cost visual states its window | Ragged coverage is real and must be visible |
| **G15** | **Cross-jurisdiction median ≠ national statistic.** Label it "median of 37 jurisdictions", equally weighted, never "Nigeria average" | NBS publishes its own national figures separately |

**Every page carries a visible limitation line.** Not a tooltip, not a footnote — on the page.

## 1.5 Data source and the extract layer

The PostgreSQL `mart` layer (30 objects) is the source of truth. The four tools have different
connectivity, so all four consume **one identical extract set** rather than each querying the
database its own way. This is what guarantees "one validated story".

> **The extracts do not exist yet.** They are specified here and built in Build Order step 0.

| Extract | Source object | Grain | Expected rows |
|---|---|---|---:|
| `ext_state_cost_panel` | `mart.mv_state_cost_panel_monthly` | jurisdiction × month × metric | 9,435 |
| `ext_geography` | `mart.v_geography` | geography | 44 |
| `ext_analysis_windows` | `mart.v_analysis_windows` | window | 2 |
| `ext_coverage_matrix` | `mart.v_coverage_matrix` | dataset × month | 241 |
| `ext_food_zone_vs_national` | `mart.v_food_zone_vs_national` | zone × item × month | 4,284 |
| `ext_tariff_band` | `mart.v_tariff_band_cross_section` | DisCo × class × band | 525 |
| `ext_fx_monthly` | `mart.v_fx_monthly_summary` | month | 21 |
| `ext_anomaly_register` | `mart.v_anomaly_register` | flagged fact row | 2,676 |

**Static reference tables** — the committed evidence files are used directly, not recomputed:
`d1_movement_flags` · `d2_extreme_flags_by_month` · `d3_selfgen_vs_reference_tariff` ·
`d4_selfgen_breakeven` · `d6_fare_vs_cpi_summary` · `d7_exposure_sensitivity` ·
`d8_location_value_by_cost` · `d9`–`d12` local mobility · `f01` · `f05` · `f15` · `f22` · `f25` ·
`f26` · `f29` · `f31` · `f33` · `f35` · `f39` · `f40_rank_stability` · `f41` ·
`v2a` · `v3c` · `v4_rank_stability`.

**Extract rules.** Read-only. One dated snapshot folder per refresh. Row counts asserted on write —
an extract whose count does not match this table fails the refresh. No transformation in the extract
step beyond column selection: all business logic stays in `mart` or in the tool's measures.

**Refresh cadence — DECIDED: manual / on-demand.** For this portfolio build the extracts are
regenerated deliberately, not on a schedule. Consequences, stated so nothing implies otherwise:

- Every dashboard carries an **"extract generated" date stamp** sourced from the snapshot folder, so
  a reader always knows how current the figures are.
- **No dashboard claims to be live.** No auto-refresh, no gateway, no scheduled dataset refresh.
- Cognos scheduling and bursting are specified as **design** (§5.4), not demonstrated as running
  infrastructure.
- A refresh is a deliberate act: regenerate extracts → assert row counts → reconcile KPIs across
  tools (Build Order step 6).

## 1.6 Map boundaries

**DECIDED: geoBoundaries `gbOpen`, Nigeria, `ADM1`.**

| Item | Value |
|---|---|
| Source | geoBoundaries — `gbOpen` release, open licence |
| Country / level | Nigeria (`NGA`) · `ADM1` — first-level administrative units |
| Expected units | **37** — 36 states + the Federal Capital Territory |
| Storage | `data/reference/geo/` alongside the other reference tables |
| Provenance to record at download | source URL · geoBoundaries **release version** · download timestamp (UTC) · **SHA-256 of the downloaded file** |

**Boundary validation is a build gate, not a formality.** Before any map is drawn, every `ADM1`
unit must reconcile against `core.dim_geography`:

1. Count check — the boundary file contains exactly **37** ADM1 units.
2. **Name reconciliation** — each boundary name maps 1:1 to a `dim_geography.geography_name` where
   `geography_type = 'STATE'`. Zero unmatched on either side.
3. Known naming risks to resolve explicitly, not silently: the **FCT** (our label is `Abuja`,
   geoBoundaries may use *Federal Capital Territory*), and **Nasarawa** (the corpus carries a
   `STATE_LABEL_NASSARAWA_DOUBLE_S` anomaly on 60 CPI rows, so the double-s spelling exists
   upstream).
4. The mapping is written to `data/reference/geo/geo_boundary_crosswalk.csv` — boundary name,
   `state_id`, `geography_name` — and committed, so the join is auditable rather than implicit.
5. Provenance recorded in the same folder: source, version, timestamp, SHA-256.

**If any unit fails to reconcile, the map is not built** until the crosswalk is resolved. A
silently dropped or mismatched jurisdiction is worse than no map.

> The boundary file has **not** been downloaded — this specification does not fetch it. That is
> Build Order step 0b.

---

# Part 2 — Page-by-page structure

Each page defines the eleven required elements. Where an element is deliberately empty, it says so.

---

## Page 1 — Executive Overview

| Element | Definition |
|---|---|
| **Business question** | Which external costs have moved most, and who is exposed to them? |
| **Intended user** | Owner / manager, first 60 seconds. No prior context assumed |
| **KPI cards** | K01 diesel change trough→latest · K02 petrol change trough→latest · K03 latest median diesel · K04 jurisdictions covered · K05 costs tracked · K06 validation checks passed |
| **Charts / visuals** | V1 small-multiple sparklines, one per price metric, median of 37 jurisdictions (**not** a combined line — G6, G8) · V2 horizontal bar, % change over the primary window, one bar per cost · V3 annotated single line for diesel with the 2025-09 trough and 2026-03 inflection marked |
| **Filters / slicers** | **None.** Deliberately fixed so the headline cannot be misread by a stray filter |
| **Exact metric behind each visual** | V1/V2/V3: `ext_state_cost_panel.metric_value`, median across `state_id`, grouped by `metric_code, observation_month`. V2 endpoints from `f01_trend_primary_window.csv`. K01/K02 from `f31_shock_trough_to_latest.csv` |
| **Geography grain** | STATE, aggregated to a cross-jurisdiction median (G15) |
| **Time window** | V1/V3 dataset-specific full primary history. V2 primary common window **2025-02 → 2026-04** |
| **Publication rule** | Primary publications only (G10) |
| **Business interpretation** | Energy costs are V-shaped and accelerating at the end of the series; transport fares rise steadily and do not fall back |
| **Important limitation** | **This is not the total cost of doing business.** No rent, wages, land, water, taxes or levies. Nine bought-in costs plus inflation rates. It measures cost pressure, never profitability |

---

## Page 2 — Fuel Costs

| Element | Definition |
|---|---|
| **Business question** | How have petrol, diesel and LPG moved, and how much does location change what I pay? |
| **Intended user** | Operations / fleet / procurement |
| **KPI cards** | K07 latest median diesel · K08 latest median petrol · K09 latest median LPG 12.5 kg · K10 diesel spread ₦ · K11 petrol spread ₦ · K12 diesel dearest ÷ cheapest |
| **Charts / visuals** | V4 median line per fuel, one line per metric, separate panels · V5 monthly distribution (box or p10/median/p90 band) across 37 jurisdictions · V6 spread-over-time line (max − min per month) · V7 North/South median gap, petrol and diesel |
| **Filters / slicers** | Fuel metric (single-select) · cylinder size for LPG (G8) · month range |
| **Exact metric behind each visual** | V4/V5/V6: `ext_state_cost_panel` filtered to the 4 fuel metric codes. V6 = `max(metric_value) − min(metric_value)` per month. V7 = `f26_north_south_fuel_gap.csv`, membership from `f33_north_south_membership.csv`. K10–K12 from `d8_location_value_by_cost.csv` |
| **Geography grain** | STATE |
| **Time window** | Petrol/diesel 2025-01 → 2026-05; **LPG 2025-01 → 2026-04** — shown on the page (G14) |
| **Publication rule** | Primary publications only |
| **Business interpretation** | Fuel is close to a national price. The whole spread is ₦638.66/l for diesel and ₦195.16/l for petrol; the North–South premium has closed |
| **Important limitation** | **For all four fuel metrics the order of jurisdictions keeps changing (G9): no jurisdiction may be named as the cheapest or the dearest OVER TIME.** Each single month's ranking is still a valid snapshot. The spread is shown; the lasting name is withheld |

---

## Page 3 — Transport Costs

| Element | Definition |
|---|---|
| **Business question** | How have fares moved by mode, and did they follow fuel down when fuel fell? |
| **Intended user** | Logistics, delivery, HR (commute allowances) |
| **KPI cards** | K13 latest median okada · K14 latest median intracity bus · K15 latest median intercity bus · K16 fare-stickiness observation count · K17 share of observations where okada rose while petrol fell |
| **Charts / visuals** | V8 median fare line **per mode, never combined** (G6) · V9 fare YoY vs petrol YoY, dual line, per mode · V10 stickiness summary bar: share of observations where the fare rose while petrol fell, one bar per mode · V11 air-fare series with the 2025-12 spike annotated and its source verification referenced |
| **Filters / slicers** | Mode (**single-select, mandatory, no "All"**) · jurisdiction · month range |
| **Exact metric behind each visual** | V8: `ext_state_cost_panel`, 5 transport metric codes. V9/V10: `d6_fare_vs_cpi_summary.csv` and `f29_fare_ratchet_summary.csv`. V11: `ext_state_cost_panel` air + `v1a_air_provenance.csv`, `v1c_national_air_corroboration.csv` |
| **Geography grain** | STATE. Air and intercity bus labelled **inter-regional** (G7) |
| **Time window** | 2025-01 → 2026-05. YoY panels 2026-01 → 2026-05 |
| **Publication rule** | Primary publications only |
| **Business interpretation** | In 81 jurisdiction-month pairs where petrol was cheaper year-on-year, okada, water and air fares still rose in 100% of observations; intracity bus 98.8%; intercity 84.0% |
| **Important limitation** | These are **passenger fares, not freight rates.** No causal claim: petrol is one observed input among many, and the observations fall in only 4 months so are not independent |

---

## Page 4 — Geographic Cost Differences

| Element | Definition |
|---|---|
| **Business question** | Where does location actually change what I pay — and where does it not? |
| **Intended user** | Anyone considering siting, sourcing or a standing supplier preference |
| **KPI cards** | K18 water dearest ÷ cheapest · K19 okada ratio · K20 intracity ratio · K21 petrol ratio (shown precisely because it is nearly 1) |
| **Charts / visuals** | V12 **choropleth map, restricted to the four rank-stable metrics** (water, okada, intracity bus, intercity bus) · V13 spread bar chart for **all nine** costs, ₦ and ratio, no jurisdiction names on the five unstable ones · V14 persistent position table — jurisdictions persistently dear/cheap on local mobility · V15 food zone premium, **six zones only** (G3) |
| **Filters / slicers** | Metric — **the map's metric list contains only the four stable metrics**; the bar chart's list contains all nine · month |
| **Exact metric behind each visual** | V12: `ext_state_cost_panel` joined to `ext_geography`, gated on `f40_rank_stability.stable_for_persistent_ranking = true`. V13: `d8_location_value_by_cost.csv`. V14: `d10_local_mobility_dear.csv`, `d11_local_mobility_cheap.csv`, `d12_split_positions.csv`. V15: `f22_food_zone_premium.csv` |
| **Geography grain** | STATE for V12–V14; **ZONE for V15, on its own visual, never merged** |
| **Time window** | Latest primary common month **2026-04** for the map; full window for V14 |
| **Publication rule** | Primary publications only |
| **Business interpretation** | Location is worth ₦5,796.57 on water transport and ₦960.67 on okada; it is worth ₦195.16 on petrol. Ondo and Lagos are persistently dear on all three local modes |
| **Important limitation** | **The map is deliberately incomplete** (G9). Five costs have no map because their order does not persist. Three jurisdictions hold split positions — dear on one local mode, cheap on another — so "expensive" must name the mode |

---

## Page 5 — Cost Trends Over Time

| Element | Definition |
|---|---|
| **Business question** | What is the shape of the change, and when did it turn? |
| **Intended user** | Analyst, planner |
| **KPI cards** | K22 trough month · K23 inflection month · K24 months in the primary common window · K25 CPI all-items YoY latest |
| **Charts / visuals** | V16 median line per metric with the primary window shaded · V17 month-over-month heatmap, metric × month · V18 YoY lines **with a visible break at 2026-02** (G11) · V19 CPI change rates, all-items and food, MoM and YoY |
| **Filters / slicers** | Metric · window toggle (primary common ↔ dataset-specific, with the row count changing visibly) |
| **Exact metric behind each visual** | V16/V17: `ext_state_cost_panel`, median and `pct_change` by `(state_id, metric_code)` ordered by month. V18: YoY computed only where a value exists 12 months earlier. V19: the four CPI rate metric codes — **index codes excluded at the model level** (G2) |
| **Geography grain** | STATE aggregated to median |
| **Time window** | Both, explicitly toggled: available 2025-01 → 2026-04; primary common 2025-02 → 2026-04; dataset-specific to each series' own end |
| **Publication rule** | Primary publications only |
| **Business interpretation** | Energy fell to a 2025-09 trough then rose sharply from 2026-03. Headline inflation decelerated over the same period that energy costs accelerated |
| **Important limitation** | 15-month common window; YoY computable for only 4–5 months. **CPI YoY has a genuine hole at 2026-02** and the line must break there. No seasonal decomposition is defensible |

---

## Page 6 — Business Decision Signals

| Element | Definition |
|---|---|
| **Business question** | How unusual is the latest month, by this series' own historical standard? |
| **Intended user** | Manager scanning for what deserves a look |
| **KPI cards** | K26 metrics flagged EXTREME in the latest month · K27 jurisdictions flagged, latest month · K28 diesel EXTREME level · K29 self-generation multiple of the reference tariff |
| **Charts / visuals** | V20 flag matrix — metric × month, cell = count of jurisdictions flagged EXTREME · V21 flag-level reference table (median, p75, ELEVATED p90, EXTREME p95, worst rise, worst fall) · V22 self-generation ₦/kWh vs the fixed July 2025 Band A reference, across the efficiency range · V23 exposure sensitivity — impact per 1 pp of cost share |
| **Filters / slicers** | Metric · month · generator efficiency (2.5 / 3.0 / 3.5 / 4.0 kWh per litre) |
| **Exact metric behind each visual** | V20: `d2_extreme_flags_by_month.csv`. V21: `d1_movement_flags.csv`. V22: `d3_selfgen_vs_reference_tariff.csv` + `d4_selfgen_breakeven.csv`. V23: `d7_exposure_sensitivity.csv` |
| **Geography grain** | STATE for the flag counts; V22 compares a cross-jurisdiction median against a **DisCo-grain national benchmark** and says so |
| **Time window** | Flags built on the primary common window, 518 observations per cost (37 × 14 month-pairs) |
| **Publication rule** | Primary publications only |
| **Business interpretation** | EXTREME months cluster rather than arriving evenly — air 2025-12 in 26 of 37 jurisdictions, diesel 2026-04 in 25 |
| **Important limitation** | **Flags are descriptive, not action triggers (G13).** Turning one into a decision needs your own cost exposure, margin and pass-through ability. V22 is a **fixed July 2025 reference tariff**, not a live price: if the tariff has risen, the true multiples are smaller |

---

## Page 7 — Business Archetypes

One page with a six-way archetype selector. Every archetype shows its **relevant costs only** and its
**boundary panel** — the boundary is not optional chrome, it is half the deliverable.

| Element | Definition |
|---|---|
| **Business question** | Which of these costs matter for my kind of business, and what can this data not tell me? |
| **Intended user** | Owner or manager identifying with an archetype |
| **KPI cards** | Per archetype, drawn only from its relevant metrics — e.g. logistics shows diesel and intercity bus; food service shows LPG 12.5 kg, diesel and the food zone premium |
| **Charts / visuals** | V24 relevant-cost lines for the selected archetype · V25 exposure sensitivity bar for that archetype's costs · V26 **boundary panel** listing what is unavailable · V27 "additional data needed" list |
| **Filters / slicers** | Archetype (single-select, six options) · jurisdiction where the archetype's costs are jurisdiction-grain |
| **Exact metric behind each visual** | V24: `ext_state_cost_panel` filtered to the archetype's metric list. V25: `d7_exposure_sensitivity.csv`. V26/V27: static text from the Business Decision Analysis Report §B |
| **Geography grain** | STATE, except food service which shows **ZONE food** on a separate visual (G3) |
| **Time window** | Primary common window, with dataset-specific extensions labelled |
| **Publication rule** | Primary publications only |
| **Business interpretation** | Cost pressure is archetype-specific. Logistics is dominated by a cost it cannot relocate away from; service businesses face the opposite — their location-sensitive cost is the one where siting genuinely matters |
| **Important limitation** | **Every archetype is missing rent and labour** — for most Nigerian small businesses the two largest line items. **Pharmacy in particular: profitability cannot be calculated or inferred.** No acquisition prices, no consumption, no margins |

**The six archetypes and their metric sets**

| Archetype | Metrics shown | Boundary headline |
|---|---|---|
| Logistics / delivery | Diesel, petrol, bus intercity | Passenger fares are not freight rates |
| Pharmacy / healthcare retail | Diesel, petrol, intracity bus, okada, CPI rates, FX (national), NERC band (DisCo) | Cannot compute profitability; band must be read off the bill |
| Restaurant / food service | LPG 5 kg, LPG 12.5 kg, diesel, intracity bus, **food ZONE premium** | Food has no jurisdiction grain |
| Retail (non-food) | Diesel, bus intercity, intracity bus, okada, CPI rates | Nothing on what a retailer buys |
| Manufacturing / light production | Diesel, LPG, NERC band, FX | No industrial consumption or tariff history |
| Service businesses | Okada, intracity bus, diesel, CPI rates | Salaries and rent both absent |

---

## Page 8 — Data Quality and Methodology

| Element | Definition |
|---|---|
| **Business question** | Can I trust this, and what exactly are its limits? |
| **Intended user** | Reviewer, governance, recruiter |
| **KPI cards** | K30 validation checks passed (110/110) · K31 fact rows · K32 raw files SHA-256 verified · K33 panel grain duplicates (0) |
| **Charts / visuals** | V28 coverage matrix heatmap, dataset × month · V29 anomaly register by dataset and flag · V30 named-gaps table (2026-02 CPI YoY, 2025-04 CPI INDEX) · V31 source-verification summary — the December 2025 air spike and the LPG rank swings, with verdicts |
| **Filters / slicers** | Dataset · flag code |
| **Exact metric behind each visual** | V28: `ext_coverage_matrix`. V29: `ext_anomaly_register`. V30: static, from Discovery Report §4. V31: `v1a`, `v1c`, `v1d`, `v3a`, `v3c`, `v2a`, `v4_rank_stability` |
| **Geography grain** | Mixed by design — this page is *about* grain, and labels each row's grain explicitly |
| **Time window** | Full corpus |
| **Publication rule** | This page shows **both** primary and restatement counts, because its subject is publication behaviour itself. It is the only page where they appear together, and it says so |
| **Business interpretation** | Published source defects are carried and flagged, never silently corrected. Two suspicious patterns were traced to source and resolved |
| **Important limitation** | Validation proves the pipeline is faithful to the sources. It does **not** validate the sources themselves |

**DECIDED: this page appears in all four tools, adapted to each.** It is the page that makes the
work reviewable, so no tool ships without it. The content is the same; the form follows the tool.

| Tool | Form | Scope |
|---|---|---|
| **Power BI** | **Full methodology page** | All four visuals V28–V31, interactive, with the dataset and flag slicers |
| **Tableau** | **Methodology story section** — a closing story point | V28 and V31 as the narrative's evidentiary close: coverage, then the two source verifications and their verdicts |
| **Excel** | **README / Methodology sheet** | Static: validation totals, the named-gaps table (V30), coverage summary (V28), rerun instructions, and the extract date stamp |
| **Cognos** | **Governed report-information section** | Report header/footer metadata plus a governed appendix: validation totals, grain rules, publication rule, extract provenance and boundary-file SHA-256 |

Whatever the form, four things appear in every tool: **validation totals (110/110)**, the **named
gaps** (2026-02 CPI YoY, 2025-04 CPI INDEX), the **extract generated date**, and the statement that
validation proves pipeline fidelity, not source correctness.

---

# Part 3 — KPI dictionary

Every KPI names the validated evidence behind it. `panel` = `ext_state_cost_panel`.

| ID | KPI | Definition | Unit | Grain | Window | Evidence |
|---|---|---|---|---|---|---|
| K01 | Diesel change, trough→latest | Median of per-jurisdiction % change | % | 37 juris | 2025-09→2026-05 | `f31` (+158.16%) |
| K02 | Petrol change, trough→latest | Median of per-jurisdiction % change | % | 37 juris | 2025-09→2026-05 | `f31` (+65.35%) |
| K03 | Latest median diesel | Median across jurisdictions | ₦/litre | 37 juris | 2026-05 | panel |
| K04 | Jurisdictions covered | Distinct `state_id` | count | — | — | panel (37) |
| K05 | Costs tracked | Distinct `metric_code` | count | — | — | panel (15: 9 price + 6 CPI) |
| K06 | Validation checks passed | Sum of all three passes | count | — | — | a01+a02+a03 (110/110) |
| K07 | Latest median diesel | as K03 | ₦/litre | 37 juris | latest | panel |
| K08 | Latest median petrol | Median across jurisdictions | ₦/litre | 37 juris | latest | panel |
| K09 | Latest median LPG 12.5 kg | Median across jurisdictions | ₦/refill | 37 juris | **2026-04** | panel |
| K10 | Diesel spread | max − min across jurisdictions | ₦/litre | 37 juris | 2026-04 | `d8` (₦638.66) |
| K11 | Petrol spread | max − min across jurisdictions | ₦/litre | 37 juris | 2026-04 | `d8` (₦195.16) |
| K12 | Diesel dearest ÷ cheapest | max ÷ min | ratio | 37 juris | 2026-04 | `d8` (1.29×) |
| K13 | Latest median okada | Median across jurisdictions | ₦/journey | 37 juris | latest | panel |
| K14 | Latest median intracity bus | Median across jurisdictions | ₦/journey | 37 juris | latest | panel |
| K15 | Latest median intercity bus | Median across jurisdictions | ₦/journey | 37 juris | latest | panel |
| K16 | Fare-stickiness observations | Jurisdiction-months where petrol fell YoY | count | 35 juris, 4 months | 2026-01→04 | `f29` (81 pairs) |
| K17 | Okada rose while petrol fell | Share of those observations | % | as K16 | as K16 | `f29` (100.0%) |
| K18 | Water dearest ÷ cheapest | max ÷ min | ratio | 37 juris | 2026-04 | `d8` (6.91×) |
| K19 | Okada dearest ÷ cheapest | max ÷ min | ratio | 37 juris | 2026-04 | `d8` (2.32×) |
| K20 | Intracity dearest ÷ cheapest | max ÷ min | ratio | 37 juris | 2026-04 | `d8` (2.12×) |
| K21 | Petrol dearest ÷ cheapest | max ÷ min | ratio | 37 juris | 2026-04 | `d8` (1.14×) |
| K22 | Series trough month | Month of minimum median diesel | month | 37 juris | full | `f01` (2025-09) |
| K23 | Inflection month | First month of sustained rise | month | 37 juris | full | `f01`, `f31` (2026-03) |
| K24 | Primary common window length | Month count | count | — | — | `v_analysis_windows` (15) |
| K25 | CPI all-items YoY, latest | Median across jurisdictions | % | 37 juris | latest available | panel, rates only (G2) |
| K26 | Metrics EXTREME this month | Metrics with ≥1 jurisdiction above p95 | count | 37 juris | latest | `d2` |
| K27 | Jurisdictions flagged, latest | Count above p95, any metric | count | 37 juris | latest | `d2` |
| K28 | Diesel EXTREME level | p95 of \|MoM %\|, 518 obs | % | 37 juris | primary window | `d1` (52.04%) |
| K29 | Self-gen multiple of reference | Diesel ₦/kWh ÷ ₦209.50 | ratio | national benchmark | at selected month | `d3` (5.17× at 2026-05, 3.0 kWh/l) |
| K30 | Validation checks passed | as K06 | count | — | — | three logs |
| K31 | Fact rows in core | Sum across 12 fact tables | count | — | — | database milestone (29,032) |
| K32 | Raw files hash-verified | SHA-256 verified | count | — | — | acquisition (342) |
| K33 | Panel grain duplicates | Duplicate `(state, month, metric)` | count | — | — | a01 §0 (0) |

**Cards that must carry a qualifier on their face:** K09 *(series ends 2026-04)* · K25 *(change rate,
not index)* · K28 *(descriptive flag, not a trigger)* · K29 *(fixed July 2025 reference tariff)* ·
K10–K12, K21 *(spread only — no jurisdiction named, G9)*.

---

# Part 4 — Visual-to-data mapping

| Visual | Page | Type | Source | Metric / field | Grain | Gate |
|---|---|---|---|---|---|---|
| V1 | 1 | Sparkline ×9 | panel | median `metric_value` | STATE→median | G6, G8 |
| V2 | 1 | Bar | `f01` | `pct_change` | STATE→median | G14 |
| V3 | 1 | Annotated line | panel | median diesel | STATE→median | — |
| V4 | 2 | Line, panelled | panel | median by fuel | STATE→median | G8 |
| V5 | 2 | Distribution | panel | p10/median/p90 | STATE | — |
| V6 | 2 | Line | panel | max − min per month | STATE | G9 (no names) |
| V7 | 2 | Line | `f26`, `f33` | `north_premium_pct` | STATE→halves | G15 |
| V8 | 3 | Line per mode | panel | median by mode | STATE | **G6 single-select** |
| V9 | 3 | Dual line | `d5`, `d6` | `fare_yoy_pct`, `cpi_yoy_pct` | STATE | G11 |
| V10 | 3 | Bar | `f29` | `share_fare_rose_pct` | STATE | — |
| V11 | 3 | Annotated line | panel, `v1a`, `v1c` | median air | STATE | G7 label |
| V12 | 4 | **Choropleth** | panel + `ext_geography` | `metric_value` | STATE | **G9 — 4 metrics only** |
| V13 | 4 | Bar | `d8` | `spread_ngn`, ratio | STATE | G9 (names suppressed on 5) |
| V14 | 4 | Table | `d10`, `d11`, `d12` | persistence counts | STATE | G9 |
| V15 | 4 | Bar | `f22` | `mean_premium_pct` | **ZONE** | **G3 — separate visual** |
| V16 | 5 | Line + shading | panel, `ext_analysis_windows` | median | STATE→median | G14 |
| V17 | 5 | Heatmap | panel | MoM % | STATE→median | — |
| V18 | 5 | Line | panel | YoY % | STATE→median | **G11 — must break** |
| V19 | 5 | Line | panel | CPI rate codes only | STATE→median | **G2 — index excluded** |
| V20 | 6 | Matrix | `d2` | `jurisdictions_flagged_extreme` | STATE | G13 |
| V21 | 6 | Table | `d1` | p90 / p95 levels | STATE | G13 |
| V22 | 6 | Line / table | `d3`, `d4` | `multiple_of_reference_tariff` | national benchmark | **G4 — fixed July 2025** |
| V23 | 6 | Bar | `d7` | impact per 1 pp share | STATE→median | G12 |
| V24 | 7 | Line | panel | archetype metric list | STATE | G6 |
| V25 | 7 | Bar | `d7` | impact per 1 pp share | STATE→median | G12 |
| V26 | 7 | Text panel | static | boundaries | — | mandatory |
| V27 | 7 | Text panel | static | data needed | — | mandatory |
| V28 | 8 | Heatmap | `ext_coverage_matrix` | `row_count` | dataset × month | — |
| V29 | 8 | Bar | `ext_anomaly_register` | flag counts | mixed, labelled | — |
| V30 | 8 | Table | static | named gaps | — | G11 |
| V31 | 8 | Table | `v1a`,`v1c`,`v1d`,`v3a`,`v3c`,`v2a`,`v4` | verdicts | mixed, labelled | — |

**Not built, deliberately:** any map of petrol, diesel, LPG or air (G9) · any "total cost" or index
visual (G12) · any food visual at jurisdiction grain (G3) · any NERC time series or NERC map (G4) ·
any combined all-modes transport figure (G6) · any CPI index-level comparison (G2).

---

# Part 5 — Tool-specific implementation plan

The four tools tell **the same validated story** and are **not visual copies**. Each is chosen to
demonstrate what that tool is genuinely for.

## 5.1 Power BI — the interactive decision model

**Demonstrates:** dimensional modelling, DAX, drill-through, governed interactivity.

- **Model:** star schema — `fact_state_cost_panel` with `dim_geography`, `dim_metric`, `dim_date`.
  `dim_metric` carries `unit`, `cost_family`, `is_local_mobility` and
  `stable_for_persistent_ranking`, so G7 and G9 are enforced **in the model**, not per visual.
- **Measures:** median across jurisdictions, MoM, YoY (returning BLANK where no 12-month-prior row
  exists, so G11 holds automatically), spread, dearest ÷ cheapest.
- **Pages:** all eight, including the **full methodology page** (Page 8). Drill-through from
  Executive → the cost's detail page.
- **Interactivity:** bookmarks for the window toggle; tooltips carrying grain, window and limitation.
- **Guardrail:** the map visual's metric field is bound to a filtered `dim_metric` so unstable
  metrics are **not selectable** on the map. The map's boundary layer uses the validated
  geoBoundaries crosswalk (§1.6), not Power BI's built-in name matching — auto-matching is exactly
  where a jurisdiction gets silently dropped.

## 5.2 Tableau — the analytical narrative

**Demonstrates:** visual analytics, LOD expressions, story structure.

- **Story points, in order:** the V-shape → fuel and fares diverge → North–South converges →
  who is persistently dear → what is unusual now.
- **LOD expressions** for the persistence and quartile logic; parameter for the generator efficiency
  on V22.
- **Focus pages:** 1, 3, 4, 5, **plus a closing methodology story section** (Page 8, adapted).
- **Guardrail:** map sheets use a data-source filter on the four stable metrics, joined on the
  validated geoBoundaries crosswalk (§1.6).

## 5.3 Excel — the analyst's working surface

**Demonstrates:** Power Pivot modelling, PivotTables, clean spreadsheet engineering. **No macros.**

- **Model:** the same extracts loaded to the Data Model with relationships.
- **Content:** PivotTables with slicers for pages 2, 3, 5; conditional formatting for the flag matrix;
  sparklines for Page 1; and a **README / Methodology sheet** (Page 8, adapted) as the first tab.
- **The distinctive piece — the exposure calculator.** The user enters *their own* cost shares; the
  sheet applies the `d7` multipliers and returns the percentage-point impact on total cost. This is
  exactly the D4 design: the multiplier is published, the share is supplied by the reader, and
  nothing is aggregated into an index. It is the one thing Excel does better than the other three.
- **Guardrail:** unstable metrics are present for spread but the jurisdiction-name columns are
  removed from those PivotTables at the model level.

## 5.4 IBM Cognos Analytics — the governed enterprise report

> **STATUS: environment access UNCONFIRMED. The design stays fully in scope; implementation waits.**
>
> The Cognos design below is specified in the same detail as the other three tools and is **not**
> reduced or hedged. What is gated is only the act of building it. If an instance becomes available,
> §5.4 is built as written at Build Order step 5. If it does not, **the deliverable for this tool is
> the design itself** — data-module specification, report layouts, prompt and burst definitions —
> which is a legitimate portfolio artefact in its own right and is explicitly labelled as a design
> rather than a screenshot of something running.
>
> **No other tool depends on Cognos**, so an unavailable instance cannot block steps 0–4 or 6–7.

**Demonstrates:** governed metadata, enterprise distribution, rules enforced centrally.

- **Data module** carrying the business rules as governed metadata: grain rules (G1, G3, G4, G5),
  the CPI index quarantine (G2), the rank-stability flag (G9) and the publication rule (G10),
  so every downstream author inherits them.
- **Reports:** Executive summary plus a **governed report-information section** (Page 8, adapted) —
  report metadata with a governed appendix carrying validation totals, grain and publication rules,
  extract provenance and the boundary-file SHA-256.
- **Distribution:** scheduled, burstable PDF — specified as design, since the refresh cadence is
  manual (§1.5) and no live schedule is claimed.
- **Prompts** for metric, jurisdiction and window.
- **Guardrail:** this is the tool where the rules live as metadata rather than convention. Cognos is
  in scope *because* it is the natural home for the guardrails.

## 5.5 What must be identical across all four

Metric definitions · KPI values · grain labels · window labels · the limitation text on each page ·
the rank-stability gate. **A number that differs between tools is a defect, not a design choice.**

---

# Part 6 — Build order

| Step | Work | Gate before moving on |
|---|---|---|
| **0a** | Build the extract layer (§1.5). Row counts asserted on write | Every extract matches its expected count |
| **0b** | **Acquire and validate map boundaries** (§1.6) — download geoBoundaries `gbOpen` NGA ADM1, record source, version, timestamp and SHA-256, build and commit the crosswalk | **37 ADM1 units, zero unmatched against `dim_geography` in either direction.** FCT and Nasarawa resolved explicitly. **Map not built until this passes** |
| **1** | Freeze the KPI dictionary (Part 3) as the single definition source | Each KPI traces to a committed evidence file |
| **2** | **Power BI** — model first, then measures, then pages 1–8 including the full methodology page | Every KPI matches Part 3 exactly; map offers only the 4 stable metrics and joins on the validated crosswalk |
| **3** | **Tableau** — story points, pages 1, 3, 4, 5 + methodology story section | Shared KPIs equal the Power BI values to the last decimal |
| **4** | **Excel** — Power Pivot model, pivots, exposure calculator, README/Methodology sheet | Calculator reproduces the `d7` worked example (diesel 15% share → +23.7 pp) |
| **5** | **Cognos** — data module with the rules as metadata, Executive report, governed report-information section | **Gated on environment access.** If unavailable, deliver the design (§5.4) and record why. G1–G15 enforced in the module, not per report |
| **6** | Cross-tool reconciliation | Every shared KPI identical across all four (or all built tools, if step 5 is deferred) |
| **7** | Limitation and provenance audit | Every page shows its limitation line; every tool shows validation totals, named gaps and the extract date stamp; no visual violates G1–G15 |

**Why Power BI first:** it forces the full dimensional model, which surfaces grain and window
problems before three other tools inherit them. **Unchanged by the decisions above.**

**Step 5 cannot block the build.** Steps 0–4 and 6–7 have no Cognos dependency. If access never
arrives, the phase still completes with three built tools and one documented design.

**Definition of done for the build phase** — not part of this specification:
all eight pages exist in at least one tool; Power BI, Tableau and Excel built to their §5 scope with
Cognos built or documented; every KPI reconciled; every tool carrying validation totals, named gaps
and its extract date stamp; and no visual breaching G1–G15.

---

## Decisions taken at review

The four questions raised in the draft are now settled. Recorded here so the reasoning survives.

| # | Question | Decision | Where it lands |
|---|---|---|---|
| 1 | Extract refresh cadence | **Manual / on-demand** for the portfolio build | §1.5 — every dashboard carries an extract date stamp; nothing claims to be live; Cognos scheduling is design, not running infrastructure |
| 2 | Cognos availability | **Unconfirmed — design stays in scope, implementation waits for environment access** | §5.4 gated; Build Order step 5 gated; no other step depends on it |
| 3 | Map boundaries | **geoBoundaries `gbOpen`, Nigeria, ADM1**, validated against `dim_geography` with source, version and SHA-256 recorded | New §1.6; new Build Order step 0b; map blocked until 37/37 reconcile |
| 4 | Page 8 placement | **All four tools, adapted to each** — full page / story section / README sheet / governed report-information section | Page 8 tool table; each tool's §5 scope updated |

**Build order unchanged:** Power BI first, then Tableau, Excel, Cognos.

---

*Specification only. No tool has been opened; no dashboard, extract or artefact has been built.
Stop point: review.*
