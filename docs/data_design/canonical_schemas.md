# Canonical Clean Schemas

**Design only — none of these tables have been built.**

Thirteen clean tables plus one reference table, grouped into the eight source dataset families.
Every table is **long**: one row per observation, with the period in a column rather than a heading.

**On the example values below**

Values marked **[real]** were read from the raw files during profiling and are reproduced unchanged.
Values marked **[illustrative]** are invented to show the shape of a table that has not been built yet
— this applies to the whole NERC schema, since no PDF has been extracted. Provenance columns are
present on every table but usually omitted from the examples for width.

---

## Provenance columns (every table extracted from a spreadsheet)

| Column | Purpose |
|---|---|
| `source_file` | The ZIP or workbook in `data/raw/` |
| `source_member` | Workbook inside the ZIP, NULL for loose workbooks |
| `source_sheet` | Worksheet name, including known stale names |
| `source_row` | 1-based row number |
| `source_column_index` | 1-based column number |
| `source_cell_reference` | A1-style reference, e.g. `D17` |
| `source_period_label` | The original column heading, verbatim |
| `release_month` | The month the NBS release is titled for |

`source_row` alone is **not** sufficient to identify the origin of a value. Two columns in
`TRANSPORT_COST_Watch_MAR_2025.xlsx` carry the identical header `Average of Mar-24`, so
`source_row` + `source_period_label` is ambiguous. `source_column_index` and `source_cell_reference`
resolve every extracted value to exactly one cell.

**The rule runs one way.** Every clean row must cite exactly one source cell. One source cell may,
however, produce **several** clean rows where the expansion is deliberate and documented.

The documented exception is a **tied state callout**. `Kebbi/Nasarawa (6500)` is a single Excel cell;
cleaning emits one row for Kebbi and one for Nasarawa, and both correctly cite that same cell. So
`(source_file, source_member, source_sheet, source_cell_reference)` is unique in every table **except**
`food_price_extreme_callout` and `cooking_gas_extreme_callout`, where rows sharing a cell must all
carry `is_shared_extreme = TRUE`, an identical price and raw text, and distinct states.

---

## Release overlap — which tables restate periods

This distinction drives the primary keys, so it is stated exactly rather than generally.

**Tables built from three-period releases (year-ago, prior month, current month).** The same
`observation_month` is legitimately published by several releases, so `release_month` is part of row
identity:

| Table | Source of the overlap |
|---|---|
| `food_price_national_monthly` | `Selected Food <month>` sheet, three `Average of …` columns |
| `petrol_price_monthly` | state block, three datetime columns |
| `diesel_price_monthly` | three datetime columns |
| `cooking_gas_price_monthly` | three `Average of …` columns per cylinder block |
| `transport_fare_zone_monthly` | monthly sheet, three `Average of …` columns |
| `cpi_state_index_monthly` | Table-5, three period groups |
| `cpi_index_monthly` | Table1–Table4 restate the **entire historical series** every month — the largest overlap in the project |

**Tables that publish only the release month.** One row per observation; `release_month` is recorded
for provenance but is not needed for uniqueness:

| Table | Why |
|---|---|
| `food_price_zone_monthly` | `Zone All item` carries the current month only |
| `food_price_extreme_callout` | Highest/Lowest describe the current month only |
| `transport_fare_state_monthly` | `State Transport` carries the current month only |
| `cooking_gas_extreme_callout` | Extremes blocks describe the current month only |
| `fx_nfem_daily` | A single API snapshot, not a monthly release |
| `electricity_tariff_disco_monthly` | One order per DisCo per effective month |

`is_primary_release` remains on the overlapping tables as a **convenience flag**
(`observation_month = release_month`). It is never part of a key and is never relied upon to
distinguish one release from another — `release_month` does that.

---

## Geography model

| `geography_type` | Meaning | `state` | `zone` | `is_aggregate` |
|---|---|---|---|---|
| `STATE` | One of 36 states or FCT | populated | from `ref_state_zone` | `FALSE` |
| `ZONE` | One of six geopolitical zones | `NULL` | the zone itself | `TRUE` |
| `NATIONAL` | Whole-country figure as published | `NULL` | `NULL` | `TRUE` |
| `DISCO` | Electricity distribution licence area | **never** | `NULL` | `FALSE` |

1. `state` is populated **only** when `geography_type = 'STATE'`.
2. `zone` on a state row comes from `ref_state_zone` — never guessed from the data.
3. `DISCO` never populates `state`.

### `ref_state_zone` *(reference table — LOOKUP)* · **built**

`data/reference/ref_state_zone.csv` — **39 rows, 39 unique keys, 37 canonical entities.**

| alias_normalised | state | zone | observed_aliases | alias_variant_count | alias_source |
|---|---|---|---|---|---|
| `abia` | Abia | South East | `ABIA \| Abia` | 2 | observed |
| `akwa ibom` | Akwa Ibom | South South | `AKWA IBOM \| Akwa Ibom` | 2 | observed |
| `abuja` | Abuja | North Central | `ABUJA \| Abuja` | 2 | observed |
| `fct` | Abuja | North Central | `FCT` | 1 | **design_not_observed** |
| `nasarawa` | Nasarawa | North Central | `NASARAWA \| Nasarawa` | 2 | observed |
| `nassarawa` | Nasarawa | North Central | `NASSARAWA \| Nassarawa` | 2 | observed |

**Primary key:** `alias_normalised` — **exactly one row per key.**

`alias_normalised` is the label trimmed, internal whitespace collapsed, and casefolded. **One row per
key is the property that matters:** cleaning joins source geography to this table on
`alias_normalised`, and a duplicate key would silently multiply every joined observation.

Many keys may share a state — `abuja` and `fct` both → `Abuja`; `nasarawa` and `nassarawa` both →
`Nasarawa`. **No key may resolve to two states.**

`FCT` is the one key **not observed anywhere in the sources**. It is retained because the design
requires it, and flagged `design_not_observed` so the distinction stays visible.

**Validation (all passing):** `alias_normalised` unique · row count equals unique-key count · every
key resolves to exactly one state · all 37 entities present, 7/6/7/5/6/6 across the six zones · every
observed state-like label resolves · **simulated join of all observed labels returns 3,823 rows from
3,823 observations, max 1 row per label.**

### `ref_state_alias_observed` *(reference table — PROVENANCE)* · **built**

`data/reference/ref_state_alias_observed.csv` — **77 rows, one per raw spelling.**

| alias_raw | alias_normalised | state | zone | alias_source | observed_in |
|---|---|---|---|---|---|
| `Nassarawa` | `nassarawa` | Nasarawa | North Central | observed | cpi,diesel,petrol |
| `NASSARAWA` | `nassarawa` | Nasarawa | North Central | observed | transport |
| `ABIA` | `abia` | Abia | South East | observed | transport |

This table deliberately has **many rows per state** and is **never joined to observations** — it exists
so every raw spelling remains traceable. Its `alias_normalised` is a foreign key into the lookup.

Aliases were **harvested from the raw files, not authored from memory** — which is how `Nassarawa`
(double-s, used in CPI, diesel and petrol) was discovered.

### `ref_transport_mode` *(reference table)* · **built**

`data/reference/ref_transport_mode.csv` — **6 raw labels across the 5 canonical modes.**

| transport_mode | raw_label | match_prefix |
|---|---|---|
| `AIR` | `Air fare charg.for specified routes single journey` | `air fare` |
| `BUS_INTERCITY` | `Bus journey intercity, state route, charg. per per` | `bus journey intercity` |
| `BUS_INTRACITY` | `Bus journey within  city , per  drop constant  rou` | `bus journey within` |
| `OKADA` | `Journey by motorcycle (okada) per drop` | `journey by motorcycle` |
| `WATER` | `Water transport : water way passenger  transportat` | `water transport` |
| `WATER` | `Water transport : water way passenger  transportation` | `water transport` |

NBS truncates these headers at **exactly 50 characters**, cutting mid-word — which is why `WATER` has
both a truncated and a full variant. Raw labels are stored verbatim.

**Validation (all passing):** all five modes present · every label maps to exactly one mode · no prefix
matches two modes · no prefix is a prefix of another.

---

## 1. Food

### `food_price_national_monthly`

| observation_month | release_month | item_label | avg_price_ngn | value_status | source_period_label | is_primary_release |
|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | Beans Brown | 1344.93 **[real]** | OK | Average of May-26 | TRUE |
| 2026-04-01 | 2026-05-01 | Beans Brown | 1338.93 **[real]** | OK | Average of April-26 | FALSE |
| 2025-05-01 | 2026-05-01 | Beans Brown | 2385.15 **[real]** | OK | Average of May-25 | FALSE |
| 2025-05-01 | 2026-05-01 | Agric hen eggs, (a Crate of 30 pieces) | *NULL* | NOT_APPLICABLE | Average of May-25 | FALSE |

**Primary key:** `(release_month, observation_month, item_label)`

All three rows for `Beans Brown` come from the single May 2026 release, which restates May 2025 and
April 2026 alongside the current month. `release_month` is therefore required: without it the April
2026 row from this release collides with the April 2026 row from the April release.

The last row is one of the 15 items each month with no year-ago figure. Note that `observation_month`
is **2025-05-01** — the month the value describes — while `release_month` is **2026-05-01**, the report
it came from. The two are different by design and must never be conflated.

A duplicate on this key means the same release published the same item twice for one month — always a
parsing fault.

### `food_price_zone_monthly`

| observation_month | release_month | item_label | zone | avg_price_ngn | geography_type |
|---|---|---|---|---|---|
| 2025-09-01 | 2025-09-01 | Agric hen eggs, | North Central | 254.71726193263 **[real]** | ZONE |
| 2025-09-01 | 2025-09-01 | Agric hen eggs, | South East | 268.8533333333333 **[real]** | ZONE |

**Primary key:** `(observation_month, item_label, zone)`

`Zone All item` publishes only the release month, so `observation_month` and `release_month` always
agree and no release discriminator is needed. A duplicate means one zone appeared twice for an item.

### `food_price_extreme_callout`

| observation_month | release_month | item_label | extreme_type | state | price_ngn | is_shared_extreme | raw_callout_text |
|---|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | Beans Brown | HIGHEST | Oyo | 1941.78 **[real]** | FALSE | Oyo (1941.78) |
| 2026-05-01 | 2026-05-01 | Beans Brown | LOWEST | Taraba | 760 **[real]** | FALSE | Taraba (760) |
| 2025-02-01 | 2025-02-01 | *(illustrative tie)* | LOWEST | Kebbi | 6500 *[illustrative]* | TRUE | Kebbi/Nasarawa (6500) |
| 2025-02-01 | 2025-02-01 | *(illustrative tie)* | LOWEST | Nasarawa | 6500 *[illustrative]* | TRUE | Kebbi/Nasarawa (6500) |

**Primary key:** `(observation_month, item_label, extreme_type, state)`

`state` is in the key because a tie names several states in one cell, producing one legitimate row per
state within the same extreme.

> **This table is not state coverage.** It records which state was highest and which was lowest —
> nothing about the other 34.

---

## 2. Petrol · 3. Diesel

### `petrol_price_monthly`

| observation_month | release_month | geography_name | geography_type | state | zone | is_aggregate | price_ngn_per_litre | source_anomaly |
|---|---|---|---|---|---|---|---|---|
| 2026-01-01 | 2026-01-01 | Abia | STATE | Abia | South East | FALSE | 1054.25 **[real]** | MEMBER_FILENAME_YEAR_WRONG |
| 2025-12-01 | 2026-01-01 | Abia | STATE | Abia | South East | FALSE | 1032.1181125000003 **[real]** | MEMBER_FILENAME_YEAR_WRONG |
| 2025-12-01 | 2025-12-01 | Abia | STATE | Abia | South East | FALSE | 1032.1181125000003 **[real]** | *NULL* |
| 2025-10-01 | 2025-10-01 | Nigeria | NATIONAL | *NULL* | *NULL* | TRUE | 1052.311547273941 **[real]** | TITLE_ROW_MONTH_WRONG |
| 2025-10-01 | 2025-10-01 | South East | ZONE | *NULL* | South East | TRUE | 1047.1551516190477 **[real]** | *NULL* |

**Primary key:** `(release_month, observation_month, geography_type, geography_name)`

Rows 2 and 3 are the same observation — Abia, December 2025 — published by two different releases.
They carry identical values, which is exactly the cross-check described in D-10. Without
`release_month` in the key they would collide and one would be lost.

`geography_type` is in the key so that a state, a zone and the national aggregate can never be merged
by a name collision.

### `diesel_price_monthly`

Identical shape and identical key. Its distinguishing feature is that `geography_type` carries the
heaviest load in the project: states, zones and `NATIONAL` all arrive in one unnamed source column.

---

## 4. Cooking gas

### `cooking_gas_price_monthly`

| observation_month | release_month | cylinder_size_kg | geography_name | geography_type | zone | refill_price_ngn |
|---|---|---|---|---|---|---|
| 2025-04-01 | 2025-04-01 | 5.0 | North Central | ZONE | North Central | 7432.218771930892 **[real]** |
| 2025-04-01 | 2025-04-01 | 12.5 | North Central | ZONE | North Central | 19330.54692982723 **[real]** |

**Primary key:** `(release_month, observation_month, cylinder_size_kg, geography_type, geography_name)`

`cylinder_size_kg` is essential: the two product blocks carry **identical column headers**, so without
it the 5 kg and 12.5 kg prices for the same place and month collide directly.

> **2025 12.5 kg rows carry a known source defect.** In all twelve 2025 releases the 12.5 kg block
> prints `Taraba` in Kebbi's North West position, so Taraba appears twice and Kebbi is absent. Affected
> rows resolve to `geography_name = 'Kebbi'` with `geography_raw_label = 'Taraba'` and
> `source_anomaly = 'LPG_12_5KG_KEBBI_LABELLED_TARABA'` — applied **only** when all five fingerprint
> conditions in `cleaning_rulebook.md` §4a match. There is no global Taraba→Kebbi substitution.

### `cooking_gas_extreme_callout`

| observation_month | release_month | cylinder_size_kg | extreme_type | rank_within_block | state | price_ngn | is_shared_extreme |
|---|---|---|---|---|---|---|---|
| 2025-02-01 | 2025-02-01 | 12.5 | LOWEST | 1 | Lagos | 15750 **[real]** | FALSE |
| 2025-02-01 | 2025-02-01 | 12.5 | LOWEST | 2 | Kebbi | 16250 **[real]** | TRUE |
| 2025-02-01 | 2025-02-01 | 12.5 | LOWEST | 2 | Nasarawa | 16250 **[real]** | TRUE |

**Primary key:** `(observation_month, cylinder_size_kg, extreme_type, state)`

Unlike food, the LPG extremes blocks list **several ranked states**, not just one. `rank_within_block`
records the position as printed. The two rows at rank 2 come from the single source cell
`Kebbi/Nasarawa`.

---

## 5. Transport

### `transport_fare_state_monthly`

| observation_month | release_month | geography_name | geography_type | state | zone | is_aggregate | transport_mode | fare_ngn |
|---|---|---|---|---|---|---|---|---|
| 2025-04-01 | 2025-04-01 | Abia | STATE | Abia | South East | FALSE | AIR | 127530 **[real]** |
| 2025-04-01 | 2025-04-01 | Abia | STATE | Abia | South East | FALSE | BUS_INTERCITY | 8706.97550770297 **[real]** |
| 2025-04-01 | 2025-04-01 | Nigeria | NATIONAL | *NULL* | *NULL* | TRUE | AIR | 130243.90022074328 **[real]** |

**Primary key:** `(observation_month, geography_type, geography_name, transport_mode)`

Every key field is displayed above, and the geography fields follow the model exactly: the
`Grand Total` row becomes `geography_name = 'Nigeria'`, `geography_type = 'NATIONAL'`,
`is_aggregate = TRUE`, with **`state` and `zone` both NULL**. It is not a state and must never appear
in a state count.

No release discriminator is needed: `State Transport` publishes only the release month, so
`observation_month = release_month` on every row.

`transport_mode_raw` (the original header sentence) is carried but omitted above for width.

### `transport_fare_zone_monthly`

| observation_month | release_month | transport_mode | geography_name | geography_type | fare_ngn | source_period_label | source_cell_reference | source_anomaly |
|---|---|---|---|---|---|---|---|---|
| 2025-04-01 | 2025-04-01 | AIR | Nigeria | NATIONAL | 130243.90022074325 **[real]** | Average of Apr-25 | D2 | *NULL* |
| 2025-04-01 | 2025-04-01 | AIR | North East | ZONE | 131080.96678566668 **[real]** | Average of Apr-25 | D4 | *NULL* |
| 2025-03-01 | 2025-03-01 | AIR | Nigeria | NATIONAL | 128432.80177064867 **[real]** | Average of Mar-24 | D2 | DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION |
| 2024-03-01 | 2025-03-01 | AIR | Nigeria | NATIONAL | 88964.86486486487 **[real]** | Average of Mar-24 | B2 | DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION |

**Primary key:** `(release_month, observation_month, transport_mode, geography_type, geography_name)`

> The last two rows are the March 2025 defect, and they show why `source_cell_reference` was added.
> Both cells carry the **identical** label `Average of Mar-24`, so `source_period_label` cannot tell
> them apart. `B2` is genuinely March 2024; `D2` is March 2025 mislabelled. The cell reference
> disambiguates them; the wrong label is preserved verbatim on both.

---

## 6. CPI

### `cpi_index_monthly`

| observation_month | release_month | coverage | index_name | measure | value | value_status | index_base | is_working_sheet |
|---|---|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | NATIONAL | All Items | INDEX_MONTHLY | 140.683787 **[real]** | OK | 2024=100 | FALSE |
| 2026-04-01 | 2026-05-01 | NATIONAL | All Items | INDEX_MONTHLY | 138.27 **[real]** | OK | 2024=100 | FALSE |
| 2026-04-01 | 2026-05-01 | NATIONAL | All Items | CHANGE_MOM_PCT | 2.1312910266038614 **[real]** | OK | 2024=100 | FALSE |
| 2025-12-01 | 2026-05-01 | NATIONAL | All Items | INDEX_MONTHLY | *NULL* | SOURCE_ERROR_REF | 1985=100 | TRUE |

**Primary key:** `(release_month, observation_month, coverage, index_name, measure, index_base, is_working_sheet)`

This is the widest key in the project, and every field earns its place:

- `release_month` — Table1–Table4 restate the **whole historical series** in every release, so one
  `observation_month` appears in all 21 CPI releases.
- `index_base` — working sheets publish the same month and index on the 1985 and 2024 bases side by
  side; without it those two legitimate values collide.
- `is_working_sheet` — `Table3` and `Table3 (2)` can publish the same series; the flag keeps the
  quarantined rebasing sheets separate from the presentation tables.

### `cpi_state_index_monthly`

| observation_month | release_month | state | zone | index_name | measure | value | index_base | comparability_rule |
|---|---|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | Abia | South East | ALL_ITEMS | INDEX_LEVEL | 146.51124608741446 **[real]** | 2024=100 | LEVEL_NOT_COMPARABLE_ACROSS_STATES |
| 2026-05-01 | 2026-05-01 | Abia | South East | FOOD | INDEX_LEVEL | 142.83306042860238 **[real]** | 2024=100 | LEVEL_NOT_COMPARABLE_ACROSS_STATES |
| 2026-04-01 | 2026-05-01 | Abia | South East | ALL_ITEMS | INDEX_LEVEL | 139.6376484593503 **[real]** | 2024=100 | LEVEL_NOT_COMPARABLE_ACROSS_STATES |
| 2026-05-01 | 2026-05-01 | Abia | South East | ALL_ITEMS | CHANGE_YOY_PCT | 22.156809912767358 **[real]** | 2024=100 | LEVEL_NOT_COMPARABLE_ACROSS_STATES |

**Primary key:** `(release_month, observation_month, state, index_name, measure)`

Table-5 publishes three periods, so the April 2026 row above also appears in the April 2026 release.
`release_month` keeps them distinct.

> `comparability_rule` is carried on **every row** rather than kept in a document, so the NBS
> restriction survives into SQL, the BI model and the dashboard.
>
> Valid: `CHANGE_MOM_PCT` / `CHANGE_YOY_PCT` compared across states, and any measure tracked within one
> state over time. Invalid: ordering states by `INDEX_LEVEL` to claim one is more expensive.

---

## 7. CBN exchange rate

### `fx_nfem_daily`

| source_id | observation_date | record_status | nfem_rate | highest | lowest | closing | simple_avg | interbank_turnover_usd | nfem_deal_count | duplicate_of_source_id |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2025-01-02 | ACTIVE | 1541.3611 **[real]** | 1545.0000 **[real]** | 1538.0000 **[real]** | 1538.5000 **[real]** | 1540.6500 **[real]** | *NULL* | 0 **[real]** | *NULL* |
| 43 | 2025-02-03 | ACTIVE | 1488.9900 **[real]** | 1500.0000 **[real]** | 1480.0000 **[real]** | 1499.0000 **[real]** | 1491.2500 **[real]** | *NULL* | 0 | *NULL* |
| 44 | 2025-02-03 | EXACT_DUPLICATE | 1488.9900 **[real]** | 1500.0000 **[real]** | 1480.0000 **[real]** | 1499.0000 **[real]** | 1491.2500 **[real]** | *NULL* | 0 | 43 |
| 901 | 2026-07-15 | DATE_CONFLICT | 1310.0000 *[illustrative]* | … | … | … | … | *NULL* | 0 | *NULL* |
| 902 | 2026-07-15 | DATE_CONFLICT | 1312.5000 *[illustrative]* | … | … | … | … | *NULL* | 0 | *NULL* |

**Primary key:** `source_id` — CBN's own record identifier.

**Uniqueness rule (not the primary key):** `observation_date` must be unique **among rows where
`record_status = 'ACTIVE'`**.

This resolves the contradiction in the earlier draft. The rulebook requires that two records sharing
a date but differing in value are **both retained**; a primary key of `observation_date` made that
impossible. Using CBN's own `source_id` as the key means every published record can be stored, while
the uniqueness rule still guarantees a clean one-row-per-day series for analysis.

| `record_status` | Meaning | In the analysis view? |
|---|---|---|
| `ACTIVE` | The record to use for this date | Yes |
| `EXACT_DUPLICATE` | Identical to another record except `id`; `duplicate_of_source_id` points to the kept row | No |
| `DATE_CONFLICT` | Shares a date with another record but the values **differ** | No — **and validation raises** |

All six known duplicates (2025-02-03, 02-07, 02-18, 05-12, 05-23, 06-19) are `EXACT_DUPLICATE`: every
field matches apart from `id`. No `DATE_CONFLICT` currently exists in the data; the last two rows above
are illustrative only, showing that such a case could be stored rather than silently dropped. A
`DATE_CONFLICT` is a question for a human, not something de-duplication should decide.

**Storage: all records are kept. Nothing is deleted.**

| Count | Value |
|---|---|
| **Physical rows in `fx_nfem_daily`** (in-window) | **352** |
| of which `record_status = 'ACTIVE'` | **346** |
| of which `record_status = 'EXACT_DUPLICATE'` | **6** |
| of which `record_status = 'DATE_CONFLICT'` | **0** |
| **Active analytical observations** | **346** |

The six redundant records are **retained physically** and marked `EXACT_DUPLICATE`, not removed from
the table. Every record CBN published stays in the clean layer for auditability; the analysis view
supplies the clean daily series by filtering `record_status = 'ACTIVE'`.

This is why `source_id` is the primary key and `observation_date` is not: all 352 rows coexist, and
date uniqueness is enforced only across the 346 `ACTIVE` ones.

> Both kinds of absence appear on row 1: `interbank_turnover_usd` is `NULL` because nothing was
> published, while `nfem_deal_count` is `0` because zero was published.
>
> No row exists for the 22 weekdays with no observation — those dates are absent from the source
> entirely, which is different from being duplicated or conflicted.

---

## 8. NERC electricity tariffs

### `electricity_tariff_disco_monthly` — **DESIGN ONLY, NOT BUILT**

All values below are **[illustrative]**. No PDF has been extracted.

| disco | effective_month | order_identifier | customer_class | service_band | tariff_ngn_per_kwh | source_page | extraction_method | ocr_confidence | validation_status |
|---|---|---|---|---|---|---|---|---|---|
| IE | 2025-07-01 | ORDER/NERC/2025/064 | R2 | A | 225.0000 *[illustrative]* | 4 | TEXT_LAYER | *NULL* | VALIDATED |
| IE | 2025-07-01 | ORDER/NERC/2025/064 | C1 | B | 210.5000 *[illustrative]* | 4 | TEXT_LAYER | *NULL* | UNVALIDATED |
| KEDCO | 2026-05-01 | *(to be extracted)* | R2 | A | 231.0000 *[illustrative]* | 9 | OCR | 0.9640 | UNVALIDATED |

**Primary key:** `(disco, effective_month, customer_class, service_band)`

One DisCo publishes a grid of tariffs each month, one per customer class and service band. A duplicate
most likely means the same tariff table was parsed from two pages.

> **`state` is deliberately absent.** DisCo licence areas cross state boundaries.
>
> **Every tariff requires individual human validation before use** — not a sample. Only rows with
> `validation_status = 'VALIDATED'` may enter analysis. See D-12.

---

## Key design summary

| Table | Primary key | Geography |
|---|---|---|
| `food_price_national_monthly` | `release_month, observation_month, item_label` | NATIONAL |
| `food_price_zone_monthly` | `observation_month, item_label, zone` | ZONE |
| `food_price_extreme_callout` | `observation_month, item_label, extreme_type, state` | STATE *(callout)* |
| `petrol_price_monthly` | `release_month, observation_month, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `diesel_price_monthly` | `release_month, observation_month, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `cooking_gas_price_monthly` | `release_month, observation_month, cylinder_size_kg, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `cooking_gas_extreme_callout` | `observation_month, cylinder_size_kg, extreme_type, state` | STATE *(callout)* |
| `transport_fare_state_monthly` | `observation_month, geography_type, geography_name, transport_mode` | STATE/NATIONAL |
| `transport_fare_zone_monthly` | `release_month, observation_month, transport_mode, geography_type, geography_name` | ZONE/NATIONAL |
| `cpi_index_monthly` | `release_month, observation_month, coverage, index_name, measure, index_base, is_working_sheet` | NATIONAL/URBAN/RURAL |
| `cpi_state_index_monthly` | `release_month, observation_month, state, index_name, measure` | STATE |
| `fx_nfem_daily` | `source_id` *(unique `observation_date` among ACTIVE rows)* | NATIONAL |
| `electricity_tariff_disco_monthly` | `disco, effective_month, customer_class, service_band` | DISCO |
| `ref_state_zone` | `alias_normalised` | STATE |

Four geographic levels are preserved deliberately. They are **not** flattened into a single state
table, because three of the eight sources do not publish state values at all.
