# Business Decision Analysis Report

**Phase:** Business decision analysis (pass 03)
**Builds on:** Analysis Discovery `23cc35a` · PostgreSQL layer `1eaff93`
**New code:** [`a03_decision_inputs.py`](../../src/analysis/a03_decision_inputs.py)
**Validation:** **27 of 27** new checks pass · **110 of 110** across all three passes
**Status:** decision support for review. No dashboards. No composite index.

## How to read this

Each archetype is structured as **Signal → Decision implication → Decision rule → Evidence →
Boundary → Additional data needed.**

Two things this report deliberately does **not** do. It does not combine costs into a single score —
the discovery pass showed the components capture different dimensions, and no normalisation or
weighting has been approved. And it does not tell anyone what their costs are: it publishes
*multipliers and thresholds* that a business applies to its own cost shares, because cost shares are
company data we do not hold.

**Terminology:** 36 states + the Federal Capital Territory = **37 jurisdictions**.

---

## A. Four cross-cutting findings that apply to every archetype

### A1. Historical movement flags — how large a month is by past standards *(new, D1)*

> **These are descriptive flags, not business action thresholds.** **ELEVATED** = above the p90 of
> historical absolute monthly moves; **EXTREME** = above the p95. A flag says a move is large
> relative to this series' own past. It does **not** say a business should act, reprice or
> renegotiate. Whether a move matters depends on that company's **cost exposure, margin and
> ability to pass cost through** — none of which is in this dataset. Turning a flag into an
> action trigger requires those three inputs first.

Built from each jurisdiction's own month-over-month change, pooled across 37 jurisdictions ×
14 month-pairs = **518 observations per cost**.

| Cost | Median \|MoM\| | **ELEVATED** (p90) | **EXTREME** (p95) | Worst rise | Worst fall |
|---|---:|---:|---:|---:|---:|
| Air | 0.40% | 39.46% | 60.70% | +148.34% | −53.65% |
| **Diesel** | **6.72%** | **26.03%** | **52.04%** | +60.53% | −29.10% |
| LPG 5 kg | 7.24% | 29.43% | 32.21% | +38.19% | −38.61% |
| LPG 12.5 kg | 7.81% | 26.70% | 29.55% | +35.47% | −34.63% |
| Petrol | 3.66% | 21.86% | 24.63% | +34.36% | −37.81% |
| Bus intracity | 1.97% | 11.23% | 16.39% | +43.05% | −22.98% |
| Bus intercity | 0.90% | 10.19% | 16.37% | +35.48% | −17.78% |
| Okada | 2.58% | 11.20% | 16.02% | +79.51% | −18.68% |
| Water transport | 1.58% | 7.25% | 9.59% | +36.00% | −12.99% |

**EXTREME months cluster; they do not arrive evenly.** The months where the EXTREME flag was raised
in the most jurisdictions: air **2025-12 (26 of 37)**, diesel **2026-04 (25)**, bus intercity
**2026-03 (21)**, LPG 5 kg **2025-11 (20)**, bus intracity 2026-03 (14), LPG 12.5 kg 2025-11 (13).

Flags are computed on **signed as well as absolute** moves — a cost falling hard is equally
notable, so an absolute-only view would hide half the events.

### A2. Diesel self-generation against a fixed July 2025 reference tariff *(new, D2)*

> **This is a reference-benchmark comparison, not a comparison of two current prices.** The two
> series do not cover the same period: **diesel runs monthly to 2026-05**, while the **NERC tariff
> is a single July 2025 cross-section held fixed throughout**.
>
> **Tariff benchmark used:** NERC **Band A = ₦209.50/kWh**, from the July 2025 order. Band A is
> the reference precisely because it is the one band with **zero spread across all 11 DisCos**, so
> no geographic assignment is needed. **If the tariff has risen since July 2025, the true multiples
> are smaller than those shown — this corpus cannot say whether it has.**
>
> **Assumption 1 — generator efficiency (assumed, not measured):** 3.0–3.5 kWh per litre at load,
> with the wider range 2.5–4.0 carried through so the result can be read at any efficiency.
> **Assumption 2 — reference tariff (fixed benchmark):** held constant at its July 2025 value across
> every month shown.
>
> Neither side includes the generator itself, servicing, oil or downtime, nor grid connection and
> fixed charges or outage losses.

| Month | Diesel (median) | Self-gen at 3.0 kWh/l | × the ₦209.50 reference |
|---|---:|---:|---:|
| 2025-09 (series trough) | ₦1,266.33/l | ₦422.11/kWh | **2.01×** |
| 2026-04 | ₦2,472.04/l | ₦824.01/kWh | **3.93×** |
| 2026-05 | ₦3,249.96/l | ₦1,083.32/kWh | **5.17×** |

Even at the most generous efficiency tested (4.0 kWh/l) and the cheapest diesel in the series,
self-generation is **1.51×** the reference tariff. The break-even diesel price against the
reference at 3.0 kWh/l is **₦628.50/litre** — the cheapest diesel ever observed is **₦1,266.33**.
**Against this fixed July 2025 benchmark, self-generation is never the cheaper option at any band
or month in the series.**

> **Grain warning:** diesel is jurisdiction-grain, NERC tariffs are DisCo-grain, and DisCos are not
> jurisdictions. This is **not** a geographic join. It compares a cross-jurisdiction median diesel
> cost against a national band benchmark; Band A needs no geographic assignment because it is
> uniform across all 11 DisCos. A business must substitute its own measured generator burn, and
> read its own band off its bill, before using any of this.

### A3. Location is worth money for local mobility, and almost nothing for fuel *(new, D5)*

Dearest ÷ cheapest jurisdiction, 2026-04, with the money value of the gap:

| Cost | Spread | Ratio | Cheapest → dearest |
|---|---:|---:|---|
| Water transport | ₦5,796.57 | **6.91×** | Borno → Rivers |
| Bus intercity | ₦3,098.79 | 1.39× | Kwara → Abia |
| Okada | ₦960.67 | **2.32×** | Adamawa → Kaduna |
| Bus intracity | ₦952.13 | **2.12×** | Abia → Zamfara |
| Air | ₦48,184.46 | 1.36× | *not named — order unstable over time* |
| LPG 12.5 kg | ₦6,032.35 | 1.31× | *not named — order unstable over time* |
| LPG 5 kg | ₦2,540.34 | 1.35× | *not named — order unstable over time* |
| Diesel | ₦638.66 | 1.29× | *not named — order unstable over time* |
| Petrol | ₦195.16 | 1.14× | *not named — order unstable over time* |

> **The rank-stability heuristic is enforced in code.** Every month's ranking is a **valid snapshot**
> of that month — the values are correctly extracted and correctly ordered, and nothing here
> questions them. But for the five metrics whose order reshuffles on ordinary monthly movement,
> the spread is reported and **no jurisdiction is named**: not because the value is doubtful, but
> because the name would not survive to the next month and so cannot anchor a **persistent**
> location decision. A one-month "cheapest diesel" reading is real; a standing one is not.
>
> **This cut is a project decision-use heuristic** adopted for consistency — a move-to-spread ratio
> of 1.0 — not a statistical standard and not a data-quality verdict.

### A4. Exposure sensitivity — apply your own cost share *(new, D4)*

A cost that is **X%** of your cost base and rose **P%** adds **X × (P/100)** percentage points to
total cost. Median change across 37 jurisdictions:

| Cost | Primary window 2025-02→2026-04 | Trough→latest 2025-09→2026-05 |
|---|---:|---:|
| **Diesel** | +65.96% | **+158.16%** |
| Petrol | +33.25% | +65.35% |
| Okada | +65.12% | +42.51% |
| Bus intracity | +49.32% | +36.97% |
| Water transport | +42.86% | +26.30% |
| Bus intercity | +29.90% | +22.05% |
| LPG 12.5 kg | +27.38% | *series ends 2026-04* |
| LPG 5 kg | +24.35% | *series ends 2026-04* |
| Air | +21.80% | +18.69% |

*Illustration only, the share is not a finding:* diesel at 15% of a cost base, +158.2%, adds
**+23.7 percentage points** to total cost. At 30%, **+47.4 pp**.

---

## B. Archetype analyses

### B1. Logistics / delivery

**Signal.** Diesel rose a median **+158.2%** between 2025-09 and 2026-05 and rose in **all 37
jurisdictions** (slowest +115.1%). It is simultaneously the cost with the **highest exposure
multiplier** and one of the **least geographically variable** (1.29× dearest to cheapest, and
order unstable over time). Fares did not follow: in 81 jurisdiction-month pairs where petrol was cheaper
year-on-year, intercity bus fares still rose in 84.0% of observations.

**Decision implication.** Two distinct decisions, with opposite answers. *Pricing* is where the
exposure is — a diesel-heavy operation cannot absorb a 158% input move. *Location* is not: there is
no depot siting decision that meaningfully changes what you pay for diesel.

**Decision rule.**
- Trigger a **haulage pricing review** when diesel in your jurisdiction moves **≥ 26.0%** in a month
  (**ELEVATED**), and treat **≥ 52.04%** (**EXTREME**) as a prompt to re-examine surcharge terms.
  Both are historical flags; the review decision itself needs your own exposure and margin.
- 2026-04 raised the EXTREME flag in **25 of 37 jurisdictions** simultaneously — a synchronised flag
  is a portfolio-wide signal rather than a route-by-route one.
- **Do not choose depot or route location on fuel price.** The entire national spread is ₦638.66/l
  for diesel and ₦195.16/l for petrol, and the ranking is not stable enough to name a cheap state.

**Evidence.** `f31_shock_trough_to_latest.csv` (F1) · `d1_movement_flags.csv` (new) ·
`d2_extreme_flags_by_month.csv` (new) · `d8_location_value_by_cost.csv` (new) ·
`f29_fare_ratchet_summary.csv` (F3) · `f05_dispersion_summary.csv` (F2).

**Boundary.** NBS publishes **passenger fares, not freight rates** — every use of intercity bus as a
haulage proxy is an assumption, not a measurement. No driver wages, tyres, spares, insurance, tolls,
security levies or vehicle finance. No fuel-burn or route data. The diesel series ends 2026-05.

**Additional data needed.** Litres per kilometre by vehicle class; fuel as a share of total cost;
existing contract repricing and surcharge clauses; route mix and empty-running rate; maintenance and
tyre cost per km; driver pay structure.

---

### B2. Pharmacy / healthcare retail

**Signal.** Cold chain and lighting make this an electricity-intensive business with an unavoidable
backup requirement. **Self-generation costs 3.9–5.2× the Band A tariff** at 2026-04/05 diesel prices,
and has never been cheaper than grid at any band or any month in the series. Meanwhile consumer
conditions vary enormously: CPI food year-on-year ranged **+1.67% to +32.67%** across jurisdictions
in 2026-04.

**Decision implication.** The power decision is not "generator or grid" — it is **how many generator
hours are genuinely unavoidable**, and whether the premises is on the band it should be. Separately,
demand-side pressure on discretionary health spend differs so much by jurisdiction that a single
national pricing or stocking posture is hard to defend.

**Decision rule.**
- **Read the service band off the bill and get the current tariff** — ours is a July 2025 benchmark.
  Against that ₦209.50 reference, every kWh self-generated cost **3.9–5.2× more** at 2026 diesel
  prices. Cap the generator to measured outage hours and treat discretionary running as a priced
  decision.
- Re-run the comparison with the **current** tariff whenever diesel is flagged **ELEVATED** (≥ 26.0%).
  Against the fixed benchmark the multiple moved from 2.01× to 5.17× in eight months.
- Before an inverter/battery or solar investment, compute payback against the **grid tariff you
  actually pay**, not against diesel — using diesel flatters the investment case by 4–5×.

**Evidence.** `d3_selfgen_vs_reference_tariff.csv` (new) · `d4_selfgen_breakeven.csv` (new) ·
`f25_nerc_band_cross_section.csv` (F8) · `d1_movement_flags.csv` (new) ·
`f31_shock_trough_to_latest.csv` (F1) · CPI rate spread in `a01_discovery_log.txt` (F10).

**Boundary.** **This cannot calculate a pharmacy's profitability, margin or viability** — it
describes the external operating-cost environment only. We hold no medicine or product **acquisition
prices**, no rent, no wages, no **pharmacy-specific electricity consumption**, no inventory turnover,
no supplier terms, and no revenue. DisCo territories are **not** jurisdictions, so no premises can be
assigned a band from this data — the band must be read off the bill. NERC is a single **July 2025
cross-section**, so tariffs may since have changed.

**Additional data needed.** Monthly kWh and the band letter from the bill; genset fuel burn per hour
and load factor; measured outage hours; cold-chain load and its share of consumption; product
acquisition prices and supplier credit terms; inventory turnover; revenue and gross margin by
category.

---

### B3. Restaurant / food service

**Signal.** LPG is the **most volatile cost in the dataset** on a typical month — median absolute
monthly move **7.2–7.8%**, upper-quartile **19–22%** — and its jurisdiction ranking is **unusable**:
monthly moves are ~2.1× the entire cross-jurisdiction spread, so "cheapest LPG state" reshuffles on
noise. Food input costs carry a **24-percentage-point North–South gradient** (South East **+12.49%**
above national, North West **−11.30%** below) that persisted while fuel costs converged.

**Decision implication.** Menu repricing cadence should be driven by LPG and diesel movement, not by
headline inflation. Procurement geography matters for **food**, and only at zone level. It does not
matter for LPG.

**Decision rule.**
- Put a **menu cost-card review** on the agenda when LPG 12.5 kg is flagged **ELEVATED** (≥ 26.70%)
  or **EXTREME** (≥ 29.55%). LPG was flagged EXTREME in **20 of 37 jurisdictions** in 2025-11.
- **Do not set a standing supplier or site preference on LPG price ranking.** Any given month's
  ranking is a valid snapshot, but the order does not persist. Negotiate on volume and contract
  terms instead, where the lever is real.
- For food inputs, treat **zone** as the sourcing unit. A South East operation carries a structural
  ~12% premium to national and a ~24-point gap to the North West.

**Evidence.** `d1_movement_flags.csv` (new) · `v4_rank_stability.csv` (a02) ·
`v3c_lpg_distribution.csv` (a02) · `f22_food_zone_premium.csv` (F7) ·
`f01_trend_primary_window.csv` (F5).

**Boundary.** **Food has no jurisdiction-level prices at all** — six zones only, so a Lagos
restaurant inherits "South West" pricing averaged over six states. No rent, wages, water, waste or
packaging. LPG cylinder sizes are separate series and must never be averaged. The LPG series ends
**2026-04**, one month earlier than the fuels.

**Additional data needed.** LPG kilograms per month and cylinder mix; actual supplier prices at your
own location (the only way past the zone ceiling); menu cost cards with ingredient weights; covers
per day and seasonality; rent and wage bill; waste rate.

---

### B4. Retail (non-food, shop-based)

**Signal.** Our data speaks mostly to the **demand side and overheads**, not to cost of goods.
Consumer price pressure differs sharply by jurisdiction — all-items YoY ranged **+5.91% to +25.74%**
and food YoY **+1.67% to +32.67%** in 2026-04, against a cross-jurisdiction median of 15.36% and
17.37%. Inbound movement costs rose (**bus intercity +29.90%** over the window) and local mobility,
which governs both staff commute and customer footfall, is the most geographically variable cost
family.

**Decision implication.** A single national pricing, promotion and assortment posture is weak when
the customer squeeze varies by a factor of five across jurisdictions. Store siting has a real,
measurable cost consequence — through **local mobility**, not through fuel.

**Decision rule.**
- Compare your jurisdiction's **CPI food YoY** against the cross-jurisdiction median (17.37% at
  2026-04). Above roughly **1.5× the median**, plan for real demand compression in discretionary
  lines rather than treating a sales dip as execution failure.
- Revisit inbound freight terms when bus intercity is flagged **ELEVATED** (≥ 10.19%) — 2026-03 was
  flagged **EXTREME** in **21 of 37 jurisdictions**.
- Use CPI **change rates only**. Index levels may never be compared between jurisdictions.

**Evidence.** CPI rate series in `a01_discovery_log.txt` (F10) · `d1_movement_flags.csv` (new)
· `d8_location_value_by_cost.csv` (new) · `f01_trend_primary_window.csv` (F5).

**Boundary.** We hold **nothing on what a retailer buys** — no wholesale prices, no rent, no wages,
no shrinkage, no payment costs. CPI describes the **customer's** cost pressure, not the retailer's
cost base; using it as a proxy for either goods cost or wage settlements is unsupported. Intercity
bus fare is a passenger fare, not a freight rate.

**Additional data needed.** Rent and service charge by site; wholesale invoices and category
margins; footfall and conversion by location; basket composition; staff cost by site; actual inbound
freight rates.

---

### B5. Manufacturing / light production

**Signal.** Two findings point the same way. Measured against the **fixed July 2025 Band A reference
tariff of ₦209.50/kWh**, diesel self-generation is never cheaper at any band or month, and the
multiple widened from 2.01× to 5.17× in eight months. And the **naira appreciated 11.9%**
(₦1,535.95 → ₦1,352.97) over the same period in which diesel rose 158% — so the energy cost surge is
**not** FX-driven. Diesel and LPG growth are essentially unrelated across jurisdictions
(ρ = **−0.22**).

**Decision implication.** Energy strategy should treat the generator as **outage insurance, not
baseload**. FX hedging will not protect an energy budget, because the two moved in opposite
directions. And because diesel and LPG do not co-move, a business using both is exposed to two
independent risks and cannot use one to offset the other.

**Decision rule.**
- Treat generator hours above measured outage hours as a **priced decision at 3.9–5.2× the July 2025
  reference tariff**, and make band verification — against the *current* tariff — and grid-reliability
  investment the first lever, ahead of buying generating capacity.
- **Do not hedge energy cost with FX exposure.** Over 2025-01→2026-08 the naira strengthened 11.9%
  while diesel rose 158%; an FX hedge would have compounded the loss rather than offset it.
- Budget diesel and LPG as **separate risks** — ρ = −0.22 means neither offsets the other.

**Evidence.** `d3_selfgen_vs_reference_tariff.csv` (new) · `d4_selfgen_breakeven.csv` (new) ·
`f25_nerc_band_cross_section.csv` (F8) · `f15_growth_correlation.csv` (F6) ·
`f31_shock_trough_to_latest.csv` (F1) · FX series in `a01_discovery_log.txt` (F9).

**Boundary.** No industrial tariff schedule, no consumption data, no load profile. NERC is a **July
2025 cross-section**, not a tariff history, and cannot be assigned to a jurisdiction. No raw
materials, plant, labour, land or import duty. The FX–diesel relationship is a comparison of two
national series over 21 months and establishes **no causal claim**.

**Additional data needed.** Monthly kWh and load profile; the band letter and the tariff actually
paid; genset fuel burn and maintenance cost; raw material invoices and import share; energy as a
share of cost of production; measured outage hours and cost of an unplanned stop.

---

### B6. Service businesses (office-based)

**Signal.** The sharpest finding for this archetype is an indexation gap between two published growth
rates. Matched by jurisdiction and month over the four usable year-on-year months, **okada fares
rose a median +50.66% against CPI all-items +16.23% — a gap of +35.64 percentage points**, with
fares above CPI in **98.6%** of 148 observations. Intracity bus: **+39.37% vs +16.23%, a +21.68 pp
gap**, in 91.2% of observations.
Separately, local mobility is the **only** cost family where jurisdiction choice is both large and
persistent — and **Ondo and Lagos are persistently dear on all three local modes**.

**Decision implication.** A transport allowance indexed **only to CPI** would have **lagged observed
transport-fare growth**, reducing the commuting purchasing power that allowance provides. That is a
statement about the allowance against fares, **not** about total real pay — which depends on salary,
other allowances and actual commuting patterns this dataset does not contain. Separately, for a
business whose main location-sensitive cost is people moving locally, siting is a genuine, measurable
lever — unlike for the fuel-intensive archetypes.

**Decision rule.**
- **Consider observed local fares, not CPI alone, when uprating transport allowances.** Over the
  measured period a CPI-only uprate would have lagged fare growth by **21.7 pp** (bus) to **35.6 pp**
  (okada) per year, reducing commuting purchasing power.
- Revisit allowances when intracity bus (≥ 11.23%) or okada (≥ 11.20%) is flagged **ELEVATED**.
- For siting, use the persistent positions, not a single month. **Persistently dear on all three
  local modes: Ondo, Lagos.** Dear on two: Rivers, Ogun. **Persistently cheap on two: Abia, Adamawa,
  Anambra, Sokoto.**
- **Name the mode, not just the place.** Three jurisdictions hold split positions — Rivers is dear on
  okada and water but **cheap** on intracity bus; Edo is dear on water but cheap on okada; Taraba is
  dear on intracity bus but cheap on water. A blanket "expensive state" judgement would be wrong in
  each case.

**Evidence.** `d6_fare_vs_cpi_summary.csv` (new) · `d5_fare_vs_cpi_detail.csv` (new) ·
`d10_local_mobility_dear.csv` / `d11_local_mobility_cheap.csv` (new) ·
`d12_split_positions.csv` (new) · `f35_quartile_stickiness.csv` (F6b) ·
`d8_location_value_by_cost.csv` (new).

**Boundary.** No salaries, rent, internet or software — the two largest costs of a service business
are both absent, so nothing here is a statement about total cost. Published fares are **averages for
a journey**, not any individual's commute, and we hold no distances or trip counts. The fare-vs-CPI
comparison rests on only **4 usable months**: **2026-02 is excluded** because CPI year-on-year has a
genuine hole that month, and it is excluded rather than imputed.

**Additional data needed.** Headcount by location; home-to-work distances and modes actually used;
current allowance policy and uprating mechanism; salary bands and their local-market pressure; rent
and lease terms by site; remote/hybrid split.

---

## C. Where each archetype's advice is strongest and weakest

| Archetype | Strongest available claim | Weakest link |
|---|---|---|
| Logistics / delivery | Diesel exposure and repricing triggers — direct, complete, jurisdiction-grain | Freight rates absent; fares are a declared proxy |
| Pharmacy / healthcare | Self-generation vs the July 2025 reference tariff, robust across the whole efficiency range | Cannot touch profitability; no acquisition prices; tariff benchmark is 10 months older than the diesel series |
| Restaurant / food service | LPG volatility triggers; zone food gradient | Food has no jurisdiction grain; LPG ranks unusable |
| Manufacturing | Energy sourcing against a fixed reference tariff, and the FX-is-not-a-hedge result | No industrial consumption, no tariff history, no materials |
| Retail (non-food) | Demand-side dispersion by jurisdiction | Almost nothing on what a retailer actually buys |
| Service businesses | Fare-vs-CPI indexation gap and persistent siting positions | Salaries and rent — the two biggest costs — both absent |

---

## D. What is new here versus reused

**Reused unchanged from the committed discovery evidence (no recalculation):** F1 diesel
acceleration, F2 dispersion, F3 fare stickiness, F5 trend and trough, F6 correlations, F6b
persistence and the rank-stability heuristic, F6c air exclusion, F7 food zone premium, F8 NERC bands, F9 FX,
F10 CPI rates, and the a02 source verifications.

**New in this pass — six calculations, each because a decision rule needed a threshold or crossover
that discovery never computed:**

| # | Calculation | Decision it serves |
|---|---|---|
| D1 | Historical movement flags (p90 ELEVATED / p95 EXTREME) + clustering — **descriptive, not action thresholds** | Framing how unusual a month is |
| D2 | Diesel self-generation ₦/kWh against a **fixed July 2025 reference tariff**, across an efficiency range, with break-even | Pharmacy, restaurant, manufacturing, retail power strategy |
| D3 | Fare growth vs CPI growth, matched by jurisdiction and month | Commute-allowance indexation |
| D4 | Exposure sensitivity per 1 pp of cost share, two windows | Sizing any cost move against a business's own structure |
| D5 | Jurisdiction spread in naira, rank-**stability** heuristic enforced in code | Whether location is worth acting on, per cost |
| D6 | Persistent local-mobility positions, named | Office siting, rider pay, delivery-fee setting |

**Not done, deliberately:** no composite index, no weighting of one cost against another, no
dashboards, and no **persistent** jurisdiction ranking on the five metrics whose order is unstable
month to month.

---

## E. Validation summary

| Pass | Checks | Result |
|---|---|---|
| `a01_discovery.py` | 64 | **64 / 64 pass** |
| `a02_source_verification.py` | 19 | **19 / 19 pass** |
| `a03_decision_inputs.py` (new) | 27 | **27 / 27 pass** |
| **Total** | **110** | **110 / 110 pass** |

**What the 27 new checks cover.** Read-only enforcement proved by attempting a write and confirming
SQLSTATE 25006; window agreement with the database; panel unchanged at 9,435 rows and 37
jurisdictions; the month-over-month grid complete at 9 × 37 × 14 = 4,662; ELEVATED never above EXTREME for
any cost; all flag levels built on the same 518 observations; EXTREME-flag months never exceeding
the 14 available month-pairs; all six NERC bands present; Band A confirmed at zero spread so the
reference comparison needs no geography; self-generation never below the July 2025 reference tariff
at any band or month;
the 2026-02 CPI hole excluded explicitly rather than silently; the fare-vs-CPI grid complete at
2 × 37 × 4 = 296; fare growth above CPI in both modes and in the large majority of observations;
every sensitivity figure using all 37 jurisdictions; LPG correctly absent from the window it does not
cover; the rank-stable list loaded from the a01 evidence; exactly four metrics naming a
jurisdiction and no rank-unstable metric naming one; the local-mobility grid complete at 3 × 37 × 15;
and no jurisdiction persistently dear and cheap on the same mode.

**One assertion failed on first run and was corrected — the assertion, not the data.** It asserted
that no jurisdiction could be both persistently dear and persistently cheap. Three are: Edo, Rivers
and Taraba, each dear on one local mode and cheap on another. That is not a contradiction; it is the
"name the cost" point one level finer, and it became finding B6's fourth decision rule. The check now
asserts the real invariant — that no jurisdiction is both on the *same* mode — and the split
positions are reported.

---

## F. Files

**New code (1)** — `src/analysis/a03_decision_inputs.py`, 6 sections, 27 checks.

**New outputs (13)** under `outputs/analysis/decisions/`:
`a03_decision_log.txt` · `d1_movement_flags.csv` · `d2_extreme_flags_by_month.csv` ·
`d3_selfgen_vs_reference_tariff.csv` · `d4_selfgen_breakeven.csv` · `d5_fare_vs_cpi_detail.csv` ·
`d6_fare_vs_cpi_summary.csv` · `d7_exposure_sensitivity.csv` · `d8_location_value_by_cost.csv` ·
`d9_local_mobility_persistence.csv` · `d10_local_mobility_dear.csv` ·
`d11_local_mobility_cheap.csv` · `d12_split_positions.csv`

**New documentation (1)** — this report.

Nothing is committed. Nothing in `data/`, `sql/` or the database was modified: the script runs with
`default_transaction_read_only = on` and proves it. `.gitignore` has **not** been extended to the new
`outputs/analysis/decisions/` directory — the curation decision for this phase is still open, and is
flagged in the handover below.

---

## G. Before this becomes advice

Three things should happen before any of these rules is given to a business as a recommendation.

1. **The pass-through question is still open.** Discovery deliberately did not establish whether
   fares respond to fuel at all. Several rules here are framed as "watch this cost" precisely because
   the causal link is untested — they should not harden into "fuel rose, therefore reprice by X".
2. **Every flag level rests on 14 month-pairs.** These are descriptive levels from a short series,
   not control limits and not action triggers. They should be recomputed as data extends. Turning
   a flag into a trigger requires company cost exposure, margin and pass-through ability first.
3. **No rule here has been tested against a real business's numbers.** The multipliers are arithmetic;
   whether they matter depends entirely on cost shares we do not hold.

---

*Produced by `python src/analysis/a03_decision_inputs.py` against the committed database milestone.
Stop point: report, code and validation summary for review.*
