# Analysis Discovery Report

**Phase:** Analysis — discovery (pass 01) and source verification (pass 02)
**Database:** `nigeria_business_cost` (PostgreSQL 18.3), mart layer, read-only
**Baseline commit:** `1eaff933eba24e34f292300ed205c0ce4a781fc6`
**Scripts:** [`a01_discovery.py`](../../src/analysis/a01_discovery.py) ·
[`a02_source_verification.py`](../../src/analysis/a02_source_verification.py)
**Validation:** **83 of 83 checks pass** (64 discovery + 19 verification)
**Revision:** 4 — rank-stability reframing. Revision 3 was the final evidence review. Material
changes in §12.
**Status:** evidence only. No recommendations, no composite index, no dashboards.

### Geography terminology

The dataset covers **36 states and the Federal Capital Territory (FCT)** = **37 state-level
jurisdictions**. The FCT is an administrative territory, not a state. "Jurisdictions" means all 37;
"states" means the 36 states. The database column `state_id` includes the FCT (labelled `Abuja`).

---

## 1. Analytical surface

`mart` exposes **30 objects** (28 views + 2 materialized views).

**Primary working surface:** `mv_state_cost_panel_monthly` (9,435 rows — long grain
`(state_id, observation_month, metric_code)`, 15 metrics, 37 jurisdictions, primary publications
throughout); `v_state_cost_panel_wide` (703); `v_cpi_state_inflation` (2,590, **change rates only**);
`v_transport_mode_comparison` (3,145); `v_fuel_price_spread` (34).

**Publication-selection layer:** `v_petrol_primary` (748), `v_diesel_primary` (748),
`v_lpg_primary` (1,408), `v_cpi_primary` (3,848), `v_transport_state_primary` (3,230),
`v_transport_zone_primary` (595), `v_food_zone_primary` (4,284), `v_food_national_primary` (714),
each with a `_latest_restatement` counterpart. **This analysis reads only the `_primary` side.**

**Non-state grains, never merged into the panel:** `v_food_zone_vs_national` (4,284, **ZONE**);
`v_tariff_band_cross_section` (525, **DISCO**, July 2025, `NOT_MAPPED`); `v_fx_monthly_summary`
(21, **NATIONAL**).

**Governance:** `v_analysis_windows`, `v_coverage_matrix`, `v_anomaly_register` (2,676),
`v_state_dataset_windows`, `v_geography`, `v_fx_band_exceptions`, `mv_cross_release_stability`.

---

## 2. Analysis questions

**Jurisdiction-level:** S1 how far each input cost moved (F5) · S2 which categories are most
dispersed (F2) · S3 North–South fuel gap (F4) · S4 fare behaviour when petrol fell (F3) · S5 do
fast-fuel jurisdictions have fast fares (F6) · S6 does any jurisdiction hold a high-cost position
persistently, across how many cost families (F6b) · S7 accelerating vs merely high (F1) ·
S8 inflation divergence (F10, first look).

**Zone-level (food only):** Z1 zone premium and its stability · Z2 most zone-dispersed items.
**Neither can ever be answered at jurisdiction level.**

**National context:** N1 FX path · N2 electricity band spread.

**Cannot be answered:** total operating cost; "cheapest jurisdiction overall"; electricity or food
cost by jurisdiction; any causal claim about tariffs.

---

## 3. Business archetypes

**No weights assigned.** Every archetype is missing **rent and labour** — for most Nigerian small
businesses the two largest line items.

### A. Road logistics / delivery — *best supported*
**Available:** `DIESEL`, `PETROL`, all five `TRANSPORT` modes (jurisdiction, 17 months).
**Unavailable:** freight rates, driver wages, vehicle finance, tyres, insurance, tolls, levies.
**Limitation:** NBS transport figures are **passenger fares, not freight rates**.

### B. Restaurant / food service — *strong on energy, capped on food*
**Available:** `LPG` 5 kg and 12.5 kg (16 months), `DIESEL`, `TRANSPORT`, `FOOD` (**zone only**),
NERC band (DisCo). **Unavailable:** jurisdiction-level food prices, rent, wages, water, packaging.
**Limitation:** a Lagos restaurant gets Lagos LPG and diesel but only **South West** food.

### C. Light manufacturing — *moderate*
**Available:** `DIESEL`, `LPG`, NERC band (DisCo, July 2025), FX (national).
**Unavailable:** industrial consumption, raw materials, plant, labour, land, duty.
**Limitation:** electricity, likely dominant, is the least localisable component.

### D. Retail (non-food) — *partial, mostly indirect*
**Available:** `DIESEL`, `TRANSPORT`, `CPI` rates. **Unavailable:** rent, wholesale goods, wages.
**Limitation:** CPI rates describe the **customer's** squeeze, not the retailer's cost base.

### E. Office-based service business — *weakest*
**Available:** `TRANSPORT`, `DIESEL`, NERC band, `CPI` rates. **Unavailable:** rent, salaries,
internet, software. **Limitation:** dominant costs are salaries and rent; we hold neither.

### F. Pharmacy / healthcare retail — *external environment only*

| | |
|---|---|
| **Observable cost components** | Petrol and diesel (delivery runs; generator for cold-chain and lighting); jurisdiction-level transport fares (staff commute, customer access, last-mile delivery); CPI **change rates** (consumer purchasing-power pressure on health spend); FX (**national context** for an import-dependent pharmaceutical supply chain); NERC band tariffs (**DisCo context**, with no DisCo assigned to any jurisdiction) |
| **Datasets** | `PETROL`, `DIESEL`, `TRANSPORT` (jurisdiction, 17 months); `CPI` rates (jurisdiction, 18); `FX` (national, 21); `v_tariff_band_cross_section` (DisCo, July 2025) |
| **Unavailable — and decisive** | Medicine and product **acquisition prices**; rent; wages; **pharmacy-specific electricity consumption**; inventory turnover; supplier credit terms and discounts; revenue, margins, product mix |
| **What the project can say** | It can describe the **external operating-cost environment** a pharmacy faces in a jurisdiction — how energy, generator, delivery and staff-commute costs are moving, and what consumer price pressure looks like there |
| **What it cannot say** | It **cannot calculate or infer a pharmacy's profitability, margin or viability** from these external indicators. That requires company-level data we do not hold. Cold-chain electricity cost in particular cannot be estimated: neither consumption nor the DisCo band of any premises is known, and DisCo territories are not jurisdictions |

**Ranking of support:** 1. Logistics · 2. Restaurant/food service · 3. Light manufacturing ·
4. Pharmacy/healthcare retail · 5. Retail · 6. Service business.

---

## 4. Time windows

| Window | Span | Months | Use |
|---|---|---:|---|
| **Primary-release common window** | **2025-02 → 2026-04** | 15 | **Default** for multi-dataset comparison |
| Available observation window | 2025-01 → 2026-04 | 16 | Restatements only; not used |
| Petrol / diesel / transport own history | 2025-01 → 2026-05 | 17 | Single-dataset, YoY, F1 |
| LPG own history | 2025-01 → 2026-04 | 16 | Single-dataset LPG |
| CPI own history | 2025-02 → 2026-07 | 18 | Single-dataset inflation |
| Food (zone) | 2025-01 → 2026-05 | 17 | Zone only |
| FX | 2025-01 → 2026-09 | 21 | National context |
| NERC | July 2025 | 1 | Cross-section, never a trend |

Windows are read from `mart.v_analysis_windows` at run time and asserted against the script's
constants.

### Completeness, and two real holes

37 jurisdictions × 15 months = **555** expected per metric.

| Metric group | Rows | Status |
|---|---:|---|
| 9 price metrics | 555 each (4,995) | **Complete** |
| CPI MoM (both groups) | 555 each | **Complete** |
| CPI YoY (both groups) | 518 each | **2026-02 missing entirely** |
| CPI INDEX (both groups) | 518 each | **2025-04 has no primary publication** |

- **2026-02 YoY:** the February 2026 release's year-ago column is labelled 2025-02 but holds 2025-01
  data. No YoY row exists for any jurisdiction. **Any YoY chart must show a break.**
- **2025-04 INDEX:** all 222 April-2025 index rows are `is_primary_release = FALSE`; 74 carry
  `STATE_VALUE_ALIGNMENT_DISPUTED`. April 2025 **change rates are primary and present**.

---

## 5. Metrics appropriate to each dataset

| Dataset | Grain | Appropriate | Not appropriate |
|---|---|---|---|
| Petrol, diesel | jurisdiction | Level, change, MoM, YoY, median/IQR/CV, volatility; single-month rank snapshots | **Persistent rank-based claims (§7 F6b(a))**; summing across `geography_type` |
| LPG | jurisdiction × cylinder | As above, **per cylinder size** | **Persistent rank-based claims**; averaging cylinder sizes |
| Transport | jurisdiction × mode | As above, **per mode**; rank and persistence for the rank-stable modes | **Averaging or combining modes**; treating fares as freight; **folding air into "local mobility"** |
| CPI | jurisdiction × group × measure | **Change rates only** | **Index levels across jurisdictions — never** |
| Food | ZONE + NATIONAL | Zone premium, dispersion, trend | Any jurisdiction attribution |
| NERC | DISCO × class × band | Band comparison, DisCo spread, July 2025 level | Any time series; any jurisdiction mapping |
| FX | NATIONAL | Monthly mean/min/max, trend | Any jurisdiction-level use |

**Median, not mean,** for cross-jurisdiction summaries, **equally weighted per jurisdiction** —
never population- or consumption-weighted, and never NBS's published national figure.

---

## 6. Limitations

**Structural:** no rent, wages, land, water, taxes or levies · food has no jurisdiction grain ·
electricity is DisCo-grain and a single cross-section · CPI index levels cannot rank jurisdictions ·
FX is national.

**Methodological:**

6. **Short window.** 15 months common; YoY for 4–5 months. No seasonal decomposition.
7. **Endpoint sensitivity.** Series are V-shaped; window growth and trough-to-latest differ.
8. **Convergence statistics are biased toward convergence.** The −0.971 rank correlation between
   starting price and growth is partly regression to the mean. **F4's evidence is the directly
   measured gap, not that correlation.**
9. **n = 37, no significance testing on correlations.**
10. **Transport fares are passenger fares.**
11. **Cross-jurisdiction median ≠ national statistic.**
12. **Published source defects are carried, not corrected.**
13. **Observations are not independent.** Jurisdictions share national supply conditions; repeated
    months are serially correlated. Row counts overstate effective sample size throughout.
14. **Five of nine price metrics cannot support rank-based claims** (§7 F6b(a)). For those, an
    absence of persistence is a property of the ranking, not evidence that costs are uniform.
15. **Only one December exists in the transport series**, so the December 2025 air spike cannot be
    tested for seasonality from this corpus.

---

## 7. Findings

FACT and INTERPRETATION are separated throughout.

---

### F1 — Diesel prices accelerated sharply, September 2025 to May 2026

> **FACT**
> **Metric:** each jurisdiction's own percentage change; the median of those changes
> **Period:** 2025-09 → 2026-05 · **Geography:** all 37 jurisdictions, equally weighted
> **Coverage:** 37 of 37 in both months for every series · **Calculation:** §11 → `f31_shock_trough_to_latest.csv`, `f32_national_diesel_corroboration.csv`
>
> **This is a dataset-specific comparison, not a common-window one.** It ends at **2026-05, outside
> the five-dataset primary common window** (which ends 2026-04). Only petrol, diesel and the five
> transport modes publish 2026-05. **LPG (ends 2026-04) and CPI are absent from this comparison**
> and no claim is made about them over this span. **Every mode is reported separately; no fare
> measure is averaged across modes.**

| Series | Median change | Range across jurisdictions | Up |
|---|---:|---|---:|
| **Diesel** | **+158.2%** | +115.1% to +192.3% | **37 of 37** |
| **Petrol** | **+65.3%** | +45.5% to +87.1% | 37 of 37 |
| Okada | +42.5% | +16.9% to +127.3% | 37 of 37 |
| Bus intracity | +37.0% | +10.2% to +84.4% | 37 of 37 |
| Water transport | +26.3% | +10.1% to +80.2% | 37 of 37 |
| Bus intercity | +22.1% | −7.8% to +52.7% | 34 of 37 |
| Air | +18.7% | +9.1% to +46.3% | 37 of 37 |

> **Corroboration:** NBS's separately published **NATIONAL** diesel row — different rows, nine
> monthly release files — moved **₦1,277.81 → ₦3,277.47 (+156.5%)**, with no anomaly flag.

> **INTERPRETATION** Diesel's median change over this span exceeds that of every individual
> transport mode and of petrol. For businesses running generators or diesel fleets, the input-cost
> change in this period is of a different order from the rest of the series.
> **No pass-through claim is made.** This report does not establish that fare changes are caused by,
> lagged against, or constrained by diesel prices. The difference between the diesel figure and each
> fare figure is an observed difference between series, **not a measured pass-through deficit**.

> **LIMITATION** 2026-05 is outside the common window. 2025-09 is the observed fuel trough, so this
> is an upper-bound framing; the window-based figure in F5 is smaller.

---

### F2 — Petrol prices are far less dispersed between jurisdictions than transport fares are

> **FACT** · **Metric:** cross-jurisdiction CV and dearest ÷ cheapest, per metric per month ·
> **Period:** 15 primary-window months, final month 2026-04 · **Coverage:** 37 in all 15 months for
> all 9 price metrics · **Calculation:** §3 → `f05_dispersion_summary.csv`

| Cost | Mean CV, 15 months | Dearest ÷ cheapest, 2026-04 |
|---|---:|---:|
| Water transport | **67.8%** | **6.91×** |
| Okada | 18.8% | 2.32× |
| Bus intracity | 17.5% | 2.12× |
| Bus intercity | 11.6% | 1.39× |
| Diesel | 9.7% | 1.29× |
| Air | 6.6% | 1.36× |
| **Petrol** | **6.1%** | **1.14×** |
| LPG 5 kg | 5.6% | 1.35× |
| LPG 12.5 kg | 5.3% | 1.31× |

> The measured statement: **state-to-state petrol prices are much less dispersed than state-to-state
> transport fares in this dataset.**

> **INTERPRETATION** For the costs measured here, choosing between jurisdictions changes a petrol
> bill very little and a local-mobility bill a great deal. This says nothing about costs the dataset
> does not contain — rent, wages, goods — which may be dispersed very differently and are more
> likely to drive an actual location decision.

> **LIMITATION** Water transport's 6.91× partly reflects that a "water journey" is not a
> standardised product; read it as heterogeneity of service as well as of price.

---

### F3 — Fare stickiness despite petrol declines

*("Ratchet" is used elsewhere only as informal shorthand for this result.)*

> **FACT** · **Metric:** YoY % change, petrol and five fare modes, matched by jurisdiction and month
> · **Period:** 2026-01 → 2026-04 (5 YoY months exist; such observations occur in 4)
> · **Calculation:** §10B → `f29_fare_ratchet_summary.csv`
>
> **Scope of the observation set** (petrol cheaper than twelve months earlier):
>
> | | |
> |---|---:|
> | Unique jurisdictions | **35 of 37** |
> | Unique months | **4** (2026-01 … 2026-04) |
> | Jurisdiction-month pairs | **81** |
> | Jurisdiction-month-mode observations | **405** (81 × 5 modes) |
> | Median petrol YoY in the set | **−13.81%** |
>
> **Results by mode — reported separately, never pooled:**

| Fare mode | Obs | Rose | Share | Median fare YoY |
|---|---:|---:|---:|---:|
| Okada | 81 | 81 | **100.0%** | +47.33% |
| Water transport | 81 | 81 | **100.0%** | +34.00% |
| Air | 81 | 81 | **100.0%** | +19.72% |
| Bus intracity | 81 | 80 | 98.8% | +29.77% |
| Bus intercity | 81 | 68 | 84.0% | +12.17% |

> **INTERPRETATION** **Fare reductions did not accompany petrol-price reductions in these
> observations.** A business budgeting staff commute or last-mile delivery should not assume that a
> fall in pump prices will reduce transport costs.
> This is **not** a claim that petrol determines fares, that petrol is the main input to fares, or
> that any causal mechanism has been identified. Fares depend on vehicle costs, wages, route
> conditions, regulation and local competition, none of which we observe.

> **LIMITATION** These observations are **not independent events**. They fall in 4 of 5 available
> YoY months and repeat across jurisdictions that share national supply conditions, so the
> **effective sample is far smaller than 405** — closer to a handful of month-level episodes. Air in
> particular is carrier-priced nationally (F6c), so its 81 observations are better read as 4. Strong
> enough to reject "petrol down → fares down"; not strong enough to estimate an elasticity.

---

### F4 — The North–South fuel price gap narrowed to near zero

> **FACT — method stated in full**
>
> | Parameter | Value |
> |---|---|
> | **Statistic** | **Median** of jurisdiction-level published prices within each half |
> | **Weighting** | **Each jurisdiction counts once (equal weight)** — not population- or volume-weighted |
> | **Grouping** | **Our own** grouping of NBS's six zones. **NBS publishes no North/South aggregate** |
> | **Formula** | `north_premium_pct = 100 × (median_North / median_South − 1)` |
> | **Start / end** | **2025-02** / **2026-04** |
> | **Population** | 36 states + FCT = 37; FCT sits in North Central and counts in the North |
>
> **North — 20 jurisdictions** (`f33_north_south_membership.csv`)
> *North Central (7):* Abuja (FCT), Benue, Kogi, Kwara, Nasarawa, Niger, Plateau
> *North East (6):* Adamawa, Bauchi, Borno, Gombe, Taraba, Yobe
> *North West (7):* Jigawa, Kaduna, Kano, Katsina, Kebbi, Sokoto, Zamfara
>
> **South — 17 states**
> *South East (5):* Abia, Anambra, Ebonyi, Enugu, Imo
> *South South (6):* Akwa Ibom, Bayelsa, Cross River, Delta, Edo, Rivers
> *South West (6):* Ekiti, Lagos, Ogun, Ondo, Osun, Oyo

| | 2025-02 | 2026-04 |
|---|---:|---:|
| **Petrol** — North premium | **+17.24%** (₦1,326.10 vs ₦1,131.11) | **+0.17%** (₦1,550.32 vs ₦1,547.72) |
| **Diesel** — North premium | **+14.94%** (₦1,532.56 vs ₦1,333.33) | **+2.80%** (₦2,493.83 vs ₦2,425.94) |

> Petrol **fell in absolute naira** in Sokoto (−16.4%), Jigawa (−9.1%), Kaduna (−7.6%), Katsina
> (−2.1%) and Kano (−0.5%) while rising 52–63% across the South West.

> **INTERPRETATION** The northern fuel premium visible at the start of the window is not visible at
> the end. If this reflects a change in supply routing it would remove a long-standing reason to
> treat northern locations as disadvantaged on fuel. It says nothing about non-fuel costs, or why.

> **LIMITATION** See §6.8. The split is our construction; a different grouping or population
> weighting would give different numbers.

---

### F5 — Costs fell hard in mid-2025 before rising; window endpoints hide it

> **FACT** · Median across 37 jurisdictions, 2025-02 → 2026-04 · **Calculation:** §2 → `f01_trend_primary_window.csv`

| Cost | Start | End | Window change | Trough | Trough → end |
|---|---:|---:|---:|---|---:|
| Diesel | ₦1,450 | ₦2,472 | +70.5% | ₦1,266 (2025-09) | **+95.2%** |
| Okada | ₦580 | ₦977 | +68.5% | = start | +68.5% |
| Bus intracity | ₦950 | ₦1,397 | +47.1% | = start | +47.1% |
| Water | ₦1,150 | ₦1,665 | +44.8% | = start | +44.8% |
| Petrol | ₦1,166 | ₦1,548 | +32.7% | ₦963 (2025-09) | **+60.8%** |
| Bus intercity | ₦7,478 | ₦9,783 | +30.8% | = start | +30.8% |
| LPG 12.5 kg | ₦17,550 | ₦22,374 | +27.5% | ₦13,420 (2025-12) | **+66.7%** |
| Air | ₦127,000 | ₦157,301 | +23.9% | = start | (peak ₦235,143 at 2025-12 — see F6c) |
| LPG 5 kg | ₦7,103 | ₦8,776 | +23.6% | ₦5,368 (2025-12) | **+63.5%** |

> **INTERPRETATION** Energy series are V-shaped; fare series only rise. "+32.7% petrol" understates
> what an operator experienced, which was −17% then +61%. Volatility, not the endpoint, is the
> planning problem for energy-intensive businesses.

---

### F6 — Growth rates in different cost categories are weakly related across jurisdictions

> **FACT** · Spearman correlation of jurisdictions' window growth rates, 9 price metrics, 37
> jurisdictions, complete matrix · **Calculation:** §7 → `f15_growth_correlation.csv`
>
> Of 36 pairs, **one** is strongly correlated: LPG 5 kg vs 12.5 kg, **ρ = +0.72** (same commodity,
> two cylinder sizes). Next strongest: diesel vs petrol **+0.29**. All others between **−0.34 and
> +0.29**, including diesel vs intracity bus **−0.30**, petrol vs intercity bus **−0.29**, LPG 5 kg
> vs petrol **−0.34**.

> **INTERPRETATION** Answers S5: **jurisdictions with fast-rising fuel costs are not systematically
> those with fast-rising fares.** The components appear to capture **different dimensions** of the
> operating-cost environment rather than one shared pressure.

> **LIMITATION** n = 37, descriptive, no significance testing or multiple-comparison correction.
> Weak correlation over 15 months does not establish that the series are unrelated in general.

---

### F6b — Persistence: high-cost position is sticky within a metric and rarely crosses cost families

> **FACT — the complete classification rule** (declared once in `nbci_analysis.py` and reproducible
> from these values alone; **not** adjusted to produce cleaner results)
>
> | Parameter | Value |
> |---|---|
> | **Ranking method** | `pandas.rank(pct=True, method='average')`, **ascending**, computed independently within each `(metric, month)` across the 37 jurisdictions |
> | **High-cost threshold** | percentile rank **strictly > 0.75** |
> | **Low-cost threshold** | percentile rank **≤ 0.25** |
> | **Tied values** | tied published prices receive the **same averaged percentile rank** and cross the boundary together. Ties are never broken arbitrarily — this is why quartile sizes vary (observed: 9–10 high, 7–10 low; **24% of metric-months contain ties**) |
> | **Minimum eligible months** | **12** observed months. A pair below the floor is reported **INELIGIBLE**, never as "not persistent" (observed: **0 ineligible pairs**) |
> | **Persistence denominator** | months **actually observed** for that `(jurisdiction, metric)` pair — **not** the 15-month window length (observed: 15 for every pair) |
> | **Missing observations** | contribute to **neither numerator nor denominator**; the observed-month count is reported with every share |
> | **Persistent high** | `share_high ≥ 0.80` among eligible pairs |
>
> **Period:** 2025-02 → 2026-04 · **Coverage:** complete 9 × 37 × 15 grid = 4,995 observations
> **Calculation:** §12 → `f40_rank_stability.csv`, `f35_quartile_stickiness.csv`, `f41_persistent_high_per_metric.csv`, `f39_persistence_by_cost_family.csv`, `f38_persistence_permutation.csv`

**(a) Which metrics can support a rank-based claim at all?**

`ratio = mean |month-over-month %| ÷ mean cross-jurisdiction CV %`. At or above **1.0** a typical
monthly move is as large as the whole spread, so the ranking reshuffles on ordinary price movement.

| Metric | mean abs MoM % | mean CV % | ratio | Rank claims |
|---|---:|---:|---:|---|
| LPG 5 kg | 11.76 | 5.56 | **2.12** | **UNSAFE** |
| LPG 12.5 kg | 10.97 | 5.31 | **2.07** | **UNSAFE** |
| Air | 9.37 | 6.64 | **1.41** | **UNSAFE** |
| Petrol | 7.25 | 6.14 | **1.18** | **UNSAFE** |
| Diesel | 10.83 | 9.72 | **1.11** | **UNSAFE** |
| Bus intercity | 3.08 | 11.64 | 0.26 | SAFE |
| Okada | 4.82 | 18.78 | 0.26 | SAFE |
| Bus intracity | 4.25 | 17.51 | 0.24 | SAFE |
| Water transport | 2.95 | 67.80 | 0.04 | SAFE |

> **Persistence is computed for all nine metrics and reported, but the business-facing conclusion is
> drawn only from the four rank-stable ones.** For an unsafe metric, an absence of persistence
> **cannot be distinguished from rank noise** and is not evidence that costs are uniform there.

**(b) Is high-cost status sticky month to month?**

| Metric | Rank-stable | Base rate | P(high \| high) | P(high \| not) | Stickiness |
|---|---|---:|---:|---:|---:|
| Water transport | ✔ | 0.270 | **0.957** | 0.016 | +94.1 pp |
| Bus intercity | ✔ | 0.270 | 0.907 | 0.034 | +87.3 pp |
| Okada | ✔ | 0.268 | 0.878 | 0.045 | +83.3 pp |
| Bus intracity | ✔ | 0.270 | 0.857 | 0.053 | +80.4 pp |
| Air | ✘ | 0.270 | 0.850 | 0.056 | +79.4 pp |
| Diesel | ✘ | 0.268 | 0.674 | 0.121 | +55.3 pp |
| LPG 5 kg | ✘ | 0.270 | 0.600 | 0.148 | +45.2 pp |
| LPG 12.5 kg | ✘ | 0.270 | 0.593 | 0.151 | +44.2 pp |
| Petrol | ✘ | 0.270 | 0.571 | 0.159 | +41.3 pp |

> Sticky for every metric; far stickier for transport fares (0.85–0.96) than for fuels (0.57–0.67).

**(c) Jurisdictions persistently high, per metric**

| Metric | Rank-stable | Jurisdictions persistently high |
|---|---|---:|
| Water transport | ✔ | 9 |
| Bus intracity / intercity / Okada | ✔ | 7 each |
| Air | ✘ | 3 |
| Petrol | ✘ | 1 |
| LPG 5 kg | ✘ | 1 |
| Diesel | ✘ | **0** |
| LPG 12.5 kg | ✘ | **0** |

**(d) Cross-family evidence — the main business-facing result**

Families: **LIQUID_FUEL** (petrol, diesel) · **LPG** (5 kg, 12.5 kg) · **LOCAL_MOBILITY** (okada,
intracity bus, water) · **INTERREGIONAL_TRANSPORT** (air, intercity bus). **Air is never in
LOCAL_MOBILITY** (F6c).

| | |
|---|---|
| Families owning ≥ 1 rank-stable metric (**testable**) | LOCAL_MOBILITY, INTERREGIONAL_TRANSPORT — **2 of 4** |
| Families owning no rank-stable metric (**untestable**) | **LIQUID_FUEL, LPG** |

> **This is a real limit on scope, not a caveat.** For the two untestable families the absence of a
> persistently dear jurisdiction is a statement about **the ranking**, not about costs.

**Rank-stable metrics only (the defensible version):**

| | |
|---|---:|
| Persistently high on ≥ 1 rank-stable metric | 22 of 37 |
| Persistently high within exactly **1** family | **20** |
| Persistently high across **2+ testable families** | **2** — Ogun and Imo, both LOCAL_MOBILITY + INTERREGIONAL_TRANSPORT |
| Maximum metrics on any one jurisdiction | 3 |

Across all nine metrics (informational, includes rank-unstable): 5 of 37 span 2+ families;
persistent-high jurisdictions per family are LOCAL_MOBILITY 17, INTERREGIONAL 9, LIQUID_FUEL 1,
LPG 1.

**(e) Supporting test only — permutation null**

> **This test does not and cannot establish that broadly expensive jurisdictions cannot exist.** It
> answers one narrow question.
>
> | | |
> |---|---|
> | **Permuted** | Which jurisdictions occupy each metric's persistent-high set — membership reassigned at random, without replacement, independently per metric |
> | **Preserved** | The **size** of each metric's persistent-high set, the number of metrics (9), the number of jurisdictions (37) |
> | **Not preserved** | Any real correlation between metrics, and any geographic structure — so the null is deliberately **generous** to the "broadly expensive" hypothesis |
> | **Test statistics** | (i) maximum metrics on any one jurisdiction; (ii) count of jurisdictions high on ≥ 3 metrics |
> | **Draws** | 10,000, seed 20260916 |
> | **p-value rule** | one-sided upper tail, `mean(null_statistic ≥ observed_statistic)` |
>
> | Statistic | Observed | Null mean | p |
> |---|---:|---:|---:|
> | Max metrics on one jurisdiction | 3 | 3.11 | **0.900** |
> | Jurisdictions high on ≥ 3 metrics | 4 | 1.87 | 0.072 |
>
> **Reading, in full:** *under the specified null model, with metric set sizes preserved, the
> observed maximum overlap is not unusually large.* That is all it says.

> **INTERPRETATION — which conclusion the evidence supports**
>
> **A jurisdiction can be persistently expensive for a particular cost component without being
> broadly expensive across unrelated cost families.**
>
> - **Within-metric persistence is strong and real** for every rank-stable metric — a jurisdiction
>   dear on water transport this month is 95.7% likely to be dear next month.
> - **20 of 22** persistently-dear jurisdictions are dear within a **single** cost family,
>   overwhelmingly local mobility. Only Ogun and Imo span two testable families, and both do so by
>   combining local mobility with intercity bus.
> - **Scope is limited:** liquid fuel and LPG own no rank-stable metric, so for those families the
>   question cannot be answered from ranks at all.
>
> "Expensive" therefore requires naming the cost.

> **LIMITATION** 15 months and a 12-of-15 threshold; a different threshold changes set sizes. The
> permutation null assumes metrics are exchangeable across jurisdictions, which understates real
> geographic clustering. Only the 9 price metrics are tested; CPI rates measure change, not level.

---

### F6c — Air fare is not a local operating-cost signal — **NEW, from pass 02**

> **FACT** · **Test:** one-way ANOVA decomposing each mode's month-over-month percentage changes
> into a common **month** effect (all jurisdictions moving together — national or carrier-driven)
> and a within-month effect (jurisdictions moving differently — locally driven). Statistic:
> `eta² = SS_between_month / SS_total`. · **Coverage:** 592 observations per mode, 16 months, 37
> jurisdictions · **Calculation:** `a02` V2 → `v2a_mode_variance_decomposition.csv`

| Mode | η² (share of variation that is a common national movement) | mean CV of level |
|---|---:|---:|
| **Air** | **0.826** | 6.4% |
| Bus intercity | 0.660 | 11.7% |
| Bus intracity | 0.503 | 17.5% |
| Water transport | 0.303 | — |
| **Okada** | **0.200** | 18.8% |

> **INTERPRETATION** **83% of air's month-to-month variation is a common national movement**, the
> highest of the five modes, and its December swing hit all 37 jurisdictions at once. Air fares are
> set on carrier route networks, not by local market conditions in a state. The gradient is orderly:
> the longer-distance and more networked the service, the more nationally synchronised its price.

> **RULE ADOPTED** Air is **kept and reported**, but is **excluded from statements about local
> mobility costs**. "Local mobility" means **okada, intracity bus and water transport**. Intercity
> bus and air are inter-regional services and are named explicitly wherever used. This rule is
> encoded in `nbci_analysis.LOCAL_MOBILITY_METRICS` and asserted by the discovery script.

---

### F7 — Zones carry a stable, large food premium on a North/South gradient

> **FACT** · Zone premium vs published national average, per item per month · 2025-01 → 2026-05 ·
> **ZONE grain — 6 zones, not jurisdictions** · 714 rows per zone · **Calculation:** §9a → `f22_food_zone_premium.csv`

| Zone | Mean premium | Median |
|---|---:|---:|
| South East | **+12.49%** | +10.16% |
| South South | +9.13% | +6.61% |
| South West | +2.24% | +0.04% |
| North Central | −0.47% | −1.07% |
| North East | −8.22% | −7.16% |
| North West | **−11.30%** | −11.34% |

> Widest item dispersion (latest month): white maize **2.10×**, white beans 2.08×, brown beans
> 2.04×, Irish potato 1.91×, fresh onions 1.89×.

> **INTERPRETATION** Roughly a 24-percentage-point gradient. Note the contrast with F4: fuel costs
> converged North–South over this period while the food gradient persisted.

> **LIMITATION** **Zone, not jurisdiction.** A Lagos restaurant inherits "South West" food pricing
> averaged over six states. This can never be sharpened from this corpus.

---

### F8 — Electricity cost is set by service band, not by location

> **FACT** · **July 2025 cross-section only** · **DISCO grain — `NOT_MAPPED` on all rows** ·
> **Calculation:** §9c → `f25_nerc_band_cross_section.csv`

| Band | DisCos | Median ₦/kWh | Range | Spread |
|---|---:|---:|---|---:|
| A | 11 | **209.50** | 209.50 – 209.50 | **0.00** |
| B | 11 | 66.55 | 61.00 – 76.15 | 15.15 |
| C | 11 | 53.82 | 45.80 – 63.44 | 17.64 |
| D | 11 | 46.64 | 31.24 – 55.82 | 24.58 |
| E | 10 | 46.40 | 31.24 – 55.82 | 24.58 |
| LIFELINE | 11 | 4.00 | 4.00 – 4.00 | 0.00 |

> Band A is **3.15×** Band B and **52×** LIFELINE, and is identical across every DisCo.

> **INTERPRETATION** Band assignment appears to matter more than which DisCo serves the premises.

> **LIMITATION** One cross-section; cannot be joined to any jurisdiction dataset.

---

### F9 — The naira strengthened while naira-denominated energy costs rose

> **FACT** Monthly mean NFEM rate — **NATIONAL** — **₦1,535.95 (2025-01) → ₦1,352.97 (2026-08, last
> full month)**, an **11.9% appreciation**, while cross-jurisdiction median diesel rose 158%.
> **Calculation:** §9b → figures in `a01_discovery_log.txt` (FX series not exported)

> **INTERPRETATION** The 2026 energy cost rise is not explained by naira weakness. This removes an
> explanation rather than supplying one.

> **LIMITATION** National grain; two series over 21 months prove nothing causal. 2026-09 is partial
> (9 trading days) and excluded.

---

### F10 — Inflation rates decelerated while energy costs accelerated

> **FACT** Cross-jurisdiction median all-items YoY **22.34% → 15.36%**; food YoY **22.03% → 17.37%**
> with a trough of **9.21%** (2026-01). In 2026-04, food YoY ranged **+1.67% to +32.67%** across
> jurisdictions. **Change rates only.** **Calculation:** §2 → figures in `a01_discovery_log.txt` (CPI rate series not exported)

> **INTERPRETATION** Headline disinflation and business input-cost inflation point in opposite
> directions at the end of the series. The 31-point spread means national inflation commentary is a
> poor guide to any specific jurisdiction.

> **LIMITATION** YoY has a **genuine break at 2026-02**. Deceleration is partly a base effect.

---

## 8. Source verification (pass 02)

Two observations were flagged in the previous revision as possibly structural. Both were traced to
the original cleaned provenance. **19 of 19 checks pass.** Nothing was smoothed, excluded or
corrected.

### 8.1 The December 2025 air-fare spike — **GENUINELY PUBLISHED BY NBS**

| Candidate cause | Evidence | Verdict |
|---|---|---|
| **Period alignment** (a two-month report read twice) | Nov and Dec 2025 come from **one archive** (`Transport Fare Watch Report Nov_Dec_2025.zip`) but **two distinct workbook members** — `TRANSPORT COST Watch NOV_2025_.xlsx` and `…DEC_2025_.xlsx` — each with its own period label (`Transport November 2025` / `Transport December 2025`) | **Ruled out** |
| **The known duplicate-period-header defect** | That defect occurs at **2025-03 only** (`TRANSPORT_COST_Watch_MAR_2025.xlsx`), nowhere near these months | **Ruled out** |
| **Extraction problem** | Identical sheet (`State Transport`), column (B, index 2) and cell block (B2–B39) in every month; **38 geographies** read each time; **zero anomaly flags** on transport in 2025-10 … 2026-02 | **Ruled out** |
| **Structural change in publication** | No column, sheet or row-block change across these releases | **Ruled out** |
| **Genuine publication** | NBS's **separately published NATIONAL row** shows the same movement: **₦133,415 → ₦243,745 → ₦151,356 (+82.7% then −37.9%)** | **Confirmed** |

**Breadth:** all **37 of 37** jurisdictions rose, median **+74.2%**, range +5.3% to +148.3%. Every
other mode moved only +3.5% to +10.2% that month.

> **SAFE FOR ANALYSIS, WITH ONE CONSTRAINT.** It is a real, broad, single-month published movement
> that reversed the following month. Its **cause is unknown**, and because the transport series
> contains **only one December**, a seasonal explanation can be hypothesised but **cannot be tested
> from this corpus**. Any trend, growth or volatility figure spanning 2025-12 must disclose it.

### 8.2 The LPG rank swings — **GENUINE PRICES, MEANINGLESS RANKS**

| Candidate cause | Evidence | Verdict |
|---|---|---|
| **Ties** | LPG 12.5 kg values are almost all distinct (≤ 5 tied rows across 16 months) | **Ruled out** |
| **Cylinder-size confusion** | Exactly two sizes exist (5.0, 12.5); never merged | **Ruled out** |
| **Geography misalignment** | Each jurisdiction holds **one stable source row number** in every release (Nasarawa row 8, Yobe row 17, Katsina row 22) | **Ruled out** |
| **Release / restatement behaviour** | **0** primary LPG rows where `release_month ≠ observation_month` | **Ruled out** |
| **Publication structure** | The source **column did move**, `L → N`, when NBS changed the workbook layout at 2026-02, and the sheet name changed to `Sheet1` at 2026-03. Both are **tracked, not silently absorbed**; values continue coherently | **Occurred, correctly handled** |
| **Extraction problem** | Stable cells, coherent series, no flags | **Ruled out** |

**The actual cause is arithmetic.** In 2025-10 all 37 jurisdictions lay between **₦17,610.88 and
₦19,391.57** — a total spread of **₦1,780.68, CV 2.42%**. A price move of a few hundred naira
therefore traverses most of the ranking. The formal measure (F6b(a)) puts LPG's move-to-spread ratio
at **2.07–2.12**, the worst of the nine metrics.

> **CONSEQUENCE.** **LPG price levels are safe for analysis. LPG ranks are not**, and no
> jurisdiction-level "cheapest / dearest LPG" claim should be made. This independently explains why
> the persistence test found **zero** jurisdictions persistently dear on LPG 12.5 kg — and shows
> that this absence is a property of the ranking, not evidence that LPG costs are uniform.

---

## 9. On a composite Business Cost Index

**The position:** no composite index is currently justified because **normalisation, weighting and
component treatment have not been defined or approved**. That is a governance and method question,
not a data question.

Low cross-metric correlation (F6) and the concentration of persistence within single cost families
(F6b) are **useful evidence that the components capture different dimensions of business cost** —
which is exactly why weighting would have to be argued explicitly rather than assumed. They are
**not** proof that an index can never be constructed. A defensible index would need at minimum: a
stated purpose, a named business type, an argued weighting scheme, a normalisation method, a rule
for ragged coverage, and a treatment of metrics we do not hold (rent, wages).

---

## 10. Patterns still open

| # | Pattern | Status |
|---|---|---|
| P1 | December 2025 air-fare spike | **RESOLVED** — §8.1. Genuinely published; cause unknown; seasonality untestable |
| P4 | LPG rank swings | **RESOLVED** — §8.2. Genuine prices in a compressed distribution; ranks unusable |
| P2 | LPG fell 35% then recovered 67% (₦20,719 → ₦13,420 → ₦22,374) | **OPEN** — a large swing in a cooking-fuel staple; levels are safe to study |
| P3 | Five northern jurisdictions saw petrol get **cheaper in absolute naira** while the median rose 33.3% | **OPEN** — five of six are North West; suggests a supply/logistics change |
| P5 | Same-zone neighbours diverge ~2× (North West okada 2.20×, North Central water 2.00×) | **OPEN** — undermines zone-level proxies for local transport |
| P6 | Dispersion itself moves: diesel CV ranged 2.9% → 16.4% | **OPEN** — possible supply-disruption signatures |
| P7 | Transport-fare positions far stickier than fuel positions (0.85–0.96 vs 0.57–0.67) | **OPEN** — but see F6b(a): fuel stickiness is measured on an unsafe ranking |
| P8 | Diesel +158% vs fare changes of +19% to +43% over the same span | **OPEN** — an observed difference between series; whether any pass-through relationship exists is **untested** |

---

## 11. Proposed next analysis steps

1. **Test whether a fuel → fare relationship exists at all.** F3 and P8 describe co-movement and its
   absence; neither establishes a relationship. Specify lag structure, test by mode, and be prepared
   to conclude fares are not fuel-driven.
2. **Date the regime changes** (2025-09 trough, 2026-03 inflection) from the data, not by eye.
3. **Study LPG and fuel by level, not by rank** (§8.2) — distribution shape, dispersion over time,
   and whether any jurisdiction-level structure exists that ranking cannot see.
4. **Per-archetype cost-exposure profiles** (§3) as separate named components with their own units.
5. **Jurisdiction profiles** for the strongest exposure cases, stating what we hold and what we do not.
6. **A revisions study** using the `_latest_restatement` views — currently untouched.
7. **Then dashboards**, driven by whatever survives.

**Not proposed:** a composite index (§9); jurisdiction-level food or electricity analysis;
forecasting.

---

## 12. What changed in this revision

### Revision 4 — rank stability for persistent decision use

This revision changes **language and framing only**. No figure, threshold, metric or conclusion in
this report moved, and the validation count is unchanged.

Earlier revisions described five of the nine price metrics as *"rank unsafe"*. That wording implied
a verdict on the data, which was never the intent and is not what the test measures. It is now
framed as **rank stability for persistent decision use**:

- **Each published monthly ranking remains a valid snapshot.** The underlying values are correctly
  extracted and correctly ordered, and the rank is accurate as of its observation month. Nothing in
  this test questions any published figure.
- **The move-to-spread test is a project decision-use heuristic** — the ratio of a typical monthly
  move to the cross-jurisdiction spread it must traverse, with a 1.0 cut this project adopted for
  consistency.
- **It is used only to judge whether a ranking is stable enough to anchor a persistent decision** —
  siting, sourcing, a standing supplier preference — where a name has to survive from one month to
  the next to be worth acting on.
- **It is not a statistical standard and not a data-quality test.** A metric marked UNSTABLE has
  sound data and valid monthly ranks; what it lacks is a durable order.

Accordingly `SAFE`/`UNSAFE` became `STABLE`/`UNSTABLE`, the column `rank_safe` became
`stable_for_persistent_ranking`, and two evidence files were renamed
(`f40_rank_stability.csv`, `v4_rank_stability.csv`). The consequence for F6b is unchanged: the
persistence conclusion is still drawn only from the four stable metrics, and liquid fuel and LPG
still own none, so that scope limit still stands.

### Revision 3 — final evidence review

| Was | Now |
|---|---|
| Persistence rule described informally | **Fully specified** (F6b): ranking method, both thresholds, tie handling, 12-month eligibility floor, observed-month denominator, missing-observation rule. Declared once in `nbci_analysis.py` |
| Persistence reported for all 9 metrics equally | **Rank-stablety gate added.** 5 of 9 metrics (LPG ×2, air, petrol, diesel) **cannot support rank-based claims**; the conclusion is drawn only from the 4 safe ones |
| "Cross-family persistence is essentially absent — 1 of 37" | **Refined.** Under the finer family taxonomy the defensible figure is **2 of 22 spanning 2+ testable families**; 20 of 22 are single-family. And **only 2 of 4 families are testable at all** — liquid fuel and LPG own no rank-stable metric |
| Permutation framed as near-proof | **Narrowed** (F6b(e)): what was permuted, what preserved, what deliberately not preserved, both statistics, 10,000 draws, seed, exact p-rule. Explicitly labelled *supporting test only*; the direct cross-family evidence is the business-facing result |
| P1 air spike "verify before use" | **RESOLVED** (§8.1). Genuinely published; period alignment, the known duplicate-header defect, and extraction all ruled out on evidence; corroborated by the national row. Cause unknown; seasonality untestable (one December) |
| P4 LPG churn "verify before use" | **RESOLVED** (§8.2). Ties, cylinder confusion, geography misalignment, restatement and extraction all ruled out. Cause is a compressed distribution (CV 2.42%). **Levels safe, ranks not** |
| Air grouped with local transport | **Separated** (F6c). η² = 0.826 — 83% of air's variation is a common national movement. `LOCAL_MOBILITY` = okada, intracity bus, water only |
| "Transport fares are a ratchet" | **"Fare stickiness despite petrol declines"** (F3). "Ratchet" retained only as declared informal shorthand |

**Headlines that changed materially:** F6b's scope (rank-stability gate and the 2-of-4 testable
families); air's removal from local-mobility claims; P1 and P4 moving from *suspected* to
*resolved*. **Preserved unchanged:** F1–F5, F7–F10, and the core conclusion —

> *A jurisdiction can be persistently expensive for a particular cost component without being
> broadly expensive across unrelated cost families.*

---

## 13. Files: what is committed, and what is not

Nothing committed. Nothing in `data/`, `sql/` or the database modified — both scripts run with
`default_transaction_read_only = on` and prove it by attempting a write and confirming SQLSTATE
25006.

### Intended for commit — 28 new files + 1 modified

**Modified (1):** `.gitignore` — adds the rules that ignore the 34 uncommitted generated outputs and
re-include the 22 curated CSVs by name.

**Code and documentation (4)**

| Path | Lines | Purpose |
|---|---:|---|
| `src/analysis/nbci_analysis.py` | 287 | Read-only access, windows asserted against the DB, validation harness, **the persistence classification constants**, local-mobility definition |
| `src/analysis/a01_discovery.py` | 1,181 | 13-section discovery pass |
| `src/analysis/a02_source_verification.py` | 451 | Source verification of P1 and P4 |
| `docs/analysis/analysis_discovery_report.md` | — | This report |

**Curated evidence set (24)** — the two complete run logs, plus one machine-readable file per table
displayed in this report.

| File | Substantiates |
|---|---|
| `discovery/a01_discovery_log.txt` | **All 64 discovery checks** and every intermediate table, in full |
| `discovery/f01_trend_primary_window.csv` | **F5** level-and-trend table (start, end, window change, trough) |
| `discovery/f05_dispersion_summary.csv` | **F2** mean CV over 15 months — the dispersion headline |
| `discovery/f15_growth_correlation.csv` | **F6** Spearman matrix of growth-rate correlations |
| `discovery/f22_food_zone_premium.csv` | **F7** zone premium vs national |
| `discovery/f25_nerc_band_cross_section.csv` | **F8** tariff by service band |
| `discovery/f26_north_south_fuel_gap.csv` | **F4** North-premium series, both fuels |
| `discovery/f29_fare_ratchet_summary.csv` | **F3** fare stickiness, per mode, with scope counts |
| `discovery/f31_shock_trough_to_latest.csv` | **F1** per-series change 2025-09 → 2026-05 |
| `discovery/f32_national_diesel_corroboration.csv` | **F1** independent corroboration from NBS's published NATIONAL row |
| `discovery/f33_north_south_membership.csv` | **F4** exact jurisdiction membership of each half |
| `discovery/f35_quartile_stickiness.csv` | **F6b(b)** month-to-month stickiness of high-cost status |
| `discovery/f38_persistence_permutation.csv` | **F6b(e)** permutation spec, statistics and p-values |
| `discovery/f39_persistence_by_cost_family.csv` | **F6b(d)** cross-family result — the main business-facing finding |
| `discovery/f40_rank_stability.csv` | **F6b(a)** the rank-stability gate that bounds the persistence conclusion |
| `discovery/f41_persistent_high_per_metric.csv` | **F6b(c)** persistently-high count per metric |
| `verification/a02_verification_log.txt` | **All 19 verification checks** and every trace, in full |
| `verification/v1a_air_provenance.csv` | **§8.1** file / member / sheet / column per month |
| `verification/v1c_national_air_corroboration.csv` | **§8.1** NBS's published NATIONAL air row |
| `verification/v1d_december_move_by_mode.csv` | **§8.1** breadth of the December move, all five modes |
| `verification/v2a_mode_variance_decomposition.csv` | **F6c** η² — air is nationally, not locally, driven |
| `verification/v3a_lpg_source_trace.csv` | **§8.2** full source trace for three extreme movers |
| `verification/v3c_lpg_distribution.csv` | **§8.2** the compressed distribution that explains the churn |
| `verification/v4_rank_stability.csv` | **§8.2 / F6b(a)** move-to-spread ratio for all nine metrics |

### The 34 generated files not committed

The scripts produce **58** files; **24** are kept above and **34** are not. The excluded ones are
intermediate row-level extracts (`f02`, `f04`, `f07`, `f09`, `f11`, `f12`, `f19`, `f21`, `f28`,
`f30`, `f34`), tables superseded by a kept file (`f16` by `f15`, `f36`/`f36b`/`f37` by `f39` and
`f41`, `v2b` by `f05`), secondary lists that appear inline in the text rather than as a table
(`f03`, `f06`, `f08`, `f10`, `f13`, `f14`, `f17`, `f18`, `f20`, `f23`, `f24`, `f27`, `v1b`, `v3b`),
and validation-only or purely descriptive exports (`v01`, `v02`, `s01`, `s02`).

All 34 are regenerated by re-running the two scripts, and **every figure in them is printed in the
two committed run logs**, so nothing becomes unverifiable by leaving them out. They are matched by
`.gitignore` rules that ignore `outputs/analysis/**/*.csv` and then re-include exactly the 22 kept
CSVs by name.

**Also excluded:** `src/analysis/__pycache__/*.pyc` (already gitignored); `handoff.md` (gitignored by
project convention); and every exploratory probe script written during this phase — those live in
the session scratchpad outside the repository and were never inside it. Everything they established
was re-expressed as a check inside `a01`/`a02`, which is why the verification is reproducible rather
than anecdotal.

### Reference integrity

Every output file named anywhere in this report is in the committed set. The `**Calculation:**` line
of each finding names its backing file in full. Two findings — **F9** (FX) and **F10** (CPI rates) —
quote figures inline rather than displaying a table; their series are not exported as CSVs and their
`**Calculation:**` lines say so and point to `a01_discovery_log.txt` instead.

---

## 14. Validation

| Pass | Checks |
|---|---|
| `a01_discovery.py` | **64 of 64 pass** |
| `a02_source_verification.py` | **19 of 19 pass** |
| **Total** | **83 of 83 pass** |

Coverage: read-only enforcement (both passes), window agreement with the database, source row counts
after filtering, duplicate analytical grain, named missing months, unexpected NULLs, jurisdiction
coverage, one unit per metric, publication-selection rule, complete YoY grids, quartile sizes with
tie tolerance, eligibility floor, denominator equals observed months, complete 9 × 37 × 15
persistence grid, rank-stability partition, cost-family assignment and its agreement with the module's
local-mobility definition, permutation p-value well-formedness, common endpoint month, NERC
remaining unmapped, and — in pass 02 — provenance separation of the Nov/Dec members, the scope of
the duplicate-header defect, national corroboration, and each ruled-out LPG cause.

Three assertions failed on first run and were corrected — **the assertions, not the data**: a
complete-metric count of 13 where the truth is 11; a quartile-size tolerance that did not allow for
tied published prices; and a cross-family claim of "≤ 1 jurisdiction" that did not survive splitting
transport into local and inter-regional families.

---

*Produced by `python src/analysis/a01_discovery.py` and
`python src/analysis/a02_source_verification.py`. Stop point: awaiting approval to commit.*
