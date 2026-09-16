# Canonical Clean Schemas

**Design only — none of these tables have been built.**

Thirteen clean tables plus one reference table, grouped into the eight source dataset families.
Every table is **long**: one row per observation, with the period in a column rather than a heading.

> **Project scope.** `acquisition_cutoff_date = 2026-09-13`. That is the date sources were last
> checked — it is **not** the end date of any dataset. Coverage is source-specific and each family
> legitimately stops where its publisher stopped: see
> [`docs/acquisition/source_coverage_2026-09-13.md`](../acquisition/source_coverage_2026-09-13.md).
> No table should assume a shared end date.

**On the example values below**

Values marked **[real]** were read from the raw files and are reproduced unchanged. Values marked
**[illustrative]** are invented to show the shape of a table that has not been built yet. Provenance
columns are present on every table but usually omitted from the examples for width.

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
`cooking_gas_extreme_callout`, where rows sharing a cell must all carry `is_shared_extreme = TRUE`, an
identical price and raw text, and distinct states. `food_price_extreme_callout` has the same shape but
no such row in the corpus: all 1,428 food callout cells name exactly one state, so that table is
one-row-per-cell too (D-35).

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
| `food_price_zone_monthly` | `Zone All item` carries the current month only — established by the weighted reconciliation (D-31), not by a label, because the sheet has none |
| `food_price_extreme_callout` | Highest/Lowest describe the current month only |
| `transport_fare_state_monthly` | `State Transport` carries the current month only |
| `cooking_gas_extreme_callout` | Extremes blocks describe the current month only |
| `fx_nfem_daily` | A single API snapshot, not a monthly release |
| `electricity_tariff_disco_period` | One order per DisCo per effective month, each publishing three period columns |

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

Built by `src/cleaning/clean_nbs_food.py`. Every item resolves through `data/reference/ref_food_item.csv`,
which supplies `item_code`, the canonical `item_label`, the known raw aliases, and the `unit` /
`unit_source` pair. `item_label_raw` on every row preserves the text that sheet actually printed.

### `food_price_national_monthly`

| observation_month | release_month | item_code | item_label | avg_price_ngn | value_status | period_position | source_period_label | is_primary_release | source_anomaly |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | BEANS_BROWN | Beans Brown | 1344.9319046192759 **[real]** | OK | CURRENT_MONTH | Average of May-26 | TRUE | |
| 2026-04-01 | 2026-05-01 | BEANS_BROWN | Beans Brown | 1338.9328294458949 **[real]** | OK | PRIOR_MONTH | Average of April-26 | FALSE | |
| 2025-05-01 | 2026-05-01 | BEANS_BROWN | Beans Brown | 2385.151862935156 **[real]** | OK | YEAR_AGO | Average of May-25 | FALSE | |
| 2025-01-01 | 2025-01-01 | SEMOVITA_1KG | Semovita, Prepacked (1kg) | *NULL* | NOT_REPORTED | YEAR_AGO | Average of Jan-24 | TRUE | |
| 2025-03-01 | 2025-03-01 | EGG_AGRIC_CRATE30 | Agric hen eggs, (a Crate of 30 pieces) | 7670.559190085271 **[real]** | OK | CURRENT_MONTH | Average of Mar-25 | TRUE | STALE_SHEET_NAME\|NATIONAL_ABOVE_ALL_ZONES |

**Primary key:** `(release_month, observation_month, item_code)` — 2,142 rows.

All three `Beans Brown` rows come from the single May 2026 release, which restates May 2025 and
April 2026 alongside the current month. `release_month` is therefore required: without it the April
2026 row from this release collides with the April 2026 row from the April release, and the four
verified substantive revisions would be silently collapsed.

`observation_month` is the month the value describes; `release_month` is the report it came from. The
two are different by design and must never be conflated.

**The NULL row is a 2025 row, not a 2026 one.** Exactly 15 items carry a NULL year-ago average in
each of the 12 releases 2025-01 … 2025-12, and the same 15 carry a NULL prior-month average in the
2025-01 release only — 195 NULLs in total. **From the 2026-01 release onward the year-ago column is
complete for all 42 items**, because those items entered the basket in January 2025. Writing this as
"15 items each month" would be wrong and would fail the five 2026 releases.

The status is `NOT_REPORTED`, not `NOT_APPLICABLE`: the pattern is consistent with a basket change,
but no official NBS source states that these values could not exist, so the clean layer claims only
what it can show — the cell is empty (D-34).

A duplicate on this key means the same release published the same item twice for one month — always a
parsing fault.

### `food_price_zone_monthly`

| observation_month | release_month | item_code | item_label | zone | avg_price_ngn | value_status | geography_type | observation_month_basis | source_anomaly |
|---|---|---|---|---|---|---|---|---|---|
| 2025-09-01 | 2025-09-01 | EGG_AGRIC | Agric hen eggs, | North Central | 254.71726193263 **[real]** | OK | ZONE | RELEASE_CURRENT_PERIOD_COLUMN | |
| 2025-09-01 | 2025-09-01 | EGG_AGRIC | Agric hen eggs, | South East | 268.8533333333333 **[real]** | OK | ZONE | RELEASE_CURRENT_PERIOD_COLUMN | |
| 2025-07-01 | 2025-07-01 | YAM_TUBER | Yam Tuber | South South | 3290.084005837685 **[real]** | OK | ZONE | RELEASE_CURRENT_PERIOD_COLUMN | ZONE_ABOVE_STATE_MAXIMUM |

**Primary key:** `(observation_month, item_code, zone)` — 4,284 rows, no NULLs.

`Zone All item` carries **no period label of any kind**. That it publishes the release month is
established arithmetically, not assumed: `national = Σ(zone × states_in_zone) / 37` matches the
main sheet's current-month column in 713 of 714 item-releases and its prior-month column in none
(D-31). `observation_month_basis` records that derivation on every row.

### `food_price_extreme_callout`

| observation_month | release_month | item_code | item_label | extreme_type | state | zone | price_ngn | is_shared_extreme | raw_callout_text |
|---|---|---|---|---|---|---|---|---|---|
| 2026-05-01 | 2026-05-01 | BEANS_BROWN | Beans Brown | HIGHEST | Oyo | South West | 1941.78 **[real]** | FALSE | Oyo (1941.78) |
| 2026-05-01 | 2026-05-01 | BEANS_BROWN | Beans Brown | LOWEST | Taraba | North East | 760 **[real]** | FALSE | Taraba (760) |

**Primary key:** `(observation_month, item_code, extreme_type, state)` — 1,428 rows, exactly one
HIGHEST and one LOWEST per item-release.

`state` is in the key because the cooking-gas equivalent can name several states in one tied cell.
**Food never does.** All 1,428 food callout cells match `State (number)` exactly, contain no slash
and name exactly one state, so no splitting rule is implemented for this table and every row has
`is_shared_extreme = FALSE` — asserted by a check. A slash or a second state in a future release is a
hard failure requiring inspection, never a silent split (D-35).

Callout values are published rounded (0, 1 or 2 dp), so they are not byte-comparable with the
full-precision national and zone series.

> **This table is not state coverage.** It records which state was highest and which was lowest —
> nothing about the other 35.

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

**Grain per release.** The state table publishes three periods; the zone table publishes one. Each of
the 17 spreadsheet releases therefore contributes **37 states × 3 + 1 national × 3 + 6 zones × 1 = 120
rows**, giving **2,040 rows** for 2025-01 … 2026-05.

**Blocks are found by content, not coordinate (D-22).** The zone table sits in columns F/G in 16
releases and in columns **A/B beneath the state table** in January 2026 — that release is complete, not
zone-less, and its six zone rows are cleaned like any other's. Each block ends at the first row whose
label stops classifying as that block's type, which is what keeps the `STATES WITH THE
HIGHEST/LOWEST AVERAGE PRICES` callouts, the `Year on Year` / `Month on Month` footnotes and July
2025's `MAX` / `MIN` cells out of the table (D-23). Petrol has **no** canonical extreme-callout table;
the tied label `Ekiti/Oyo` therefore never reaches a geography field and is not in `ref_state_zone`.

The six petrol PDFs are corroborative only. They cannot supply `source_cell_reference`, so they
generate no canonical rows.

### `diesel_price_monthly`

Identical shape and identical key. Its distinguishing feature is that `geography_type` carries the
heaviest load in the project: states, zones and `NATIONAL` all arrive in one unnamed source column.

**Grain per release.** Unlike petrol, diesel's zone rows sit in the main table and carry **all three**
period columns, where petrol's zone table has a single `Average Price` column. Each release therefore
contributes **37 states + 6 zones + 1 national = 44 geographies × 3 periods = 132 rows**, giving
**2,244 rows** across the 17 spreadsheet releases 2025-01 … 2026-05 — more per release than petrol's
120.

**The main column is nested.** Each zone heads a section of its own member states and `NATIONAL`
closes the table. Verified across all 17 releases: identical pattern every time, no blank rows inside
the block, and every state under the zone `ref_state_zone.csv` assigns it (0 mismatches).

**Four parallel areas are excluded (D-25):** the duplicate side zone table in columns H/I, the `YoY`
and `MoM` percentage columns, the highest/lowest callout blocks, and July 2025's stray `MAX` / `MIN`
cells at K1/L1. Diesel has **no** canonical extreme-callout table, so its tied labels
`Adamawa/Plateau` and `Kogi/Zamfara` never reach a geography field and are not in `ref_state_zone`.

**Period dates are truncated, never corrected (D-24).** 50 of diesel's 51 period headers fall on day
14; `DIESEL_NOV_2025.xlsx` prints `2025-10-25`. It maps to `observation_month = 2025-10-01` while
`source_period_label` keeps `2025-10-25` verbatim.

The six diesel PDFs are corroborative only. They cannot supply `source_cell_reference`, so they
generate no canonical rows.

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

**Grain per release.** Verified uniform across all 32 blocks (16 releases × 2 sizes): 3 period columns
and 44 main-table geographies each (37 states/FCT + 6 zones + 1 national). That is
**44 × 3 × 2 = 264 rows per release**, and **4,224 rows** across the 16 spreadsheet releases
2025-01 … 2026-04.

**Blocks are identified by order, not by banner (D-26).** The left geography block is 5 kg and the
right is 12.5 kg in all 16 releases. The row-1 banner drifts 0–2 columns away from its block and reads
**`12KG`** in January 2026, so it is kept as published provenance and never used to locate or size a
block. Geography columns sit at 1/9 through 2026-01 and at 3/11 from 2026-02.

**The national row is `Average` or `Grand Total` (D-27).** Both resolve to `NATIONAL` / `Nigeria`; the
main table ends at the first row that *classifies* national, never at a literal word.

The six LPG PDFs are corroborative only. They cannot supply `source_cell_reference`, so they generate
no canonical rows.

> **2025 12.5 kg rows carry a known source defect.** In all twelve 2025 releases the 12.5 kg block
> prints `Taraba` in Kebbi's North West position, so Taraba appears twice and Kebbi is absent. Affected
> rows resolve to `geography_name = 'Kebbi'` with `geography_raw_label = 'Taraba'` and
> `source_anomaly = 'LPG_12_5KG_KEBBI_LABELLED_TARABA'` — applied **only** when all five fingerprint
> conditions in `cleaning_rulebook.md` §4a match. There is no global Taraba→Kebbi substitution.

### `cooking_gas_extreme_callout`

| observation_month | release_month | cylinder_size_kg | extreme_type | rank_within_block | state | price_ngn | is_shared_extreme |
|---|---|---|---|---|---|---|---|
| 2025-02-01 | 2025-02-01 | 12.5 | LOWEST | 1 | Lagos | 15750 **[real]** | FALSE |

**Grain.** 3 highest + 3 lowest per block × 2 sizes × 16 releases = **192 callout slots**. Exactly one
slot — 2025-02, 12.5 kg, lowest, row 56 — holds the tie **`Kebbi/Nasarawa`**, which splits into two
rows flagged `is_shared_extreme = TRUE`, giving **193 clean rows**. `Kebbi/Nasarawa` is never a
canonical state and is never added to `ref_state_zone`.

This is the **only** canonical extreme-callout table in the project for a fuel: petrol and diesel
document their callout blocks but deliberately do not extract them (D-23, D-25).
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
`observation_month = release_month` on every row. `release_month` is retained as a column for
provenance and symmetry with the other tables, but is deliberately **not** part of the logical key.

**Grain.** 5 modes × 38 geographies (37 states/FCT + `Grand Total`) × 1 period = **190 rows per
release**, **3,230** across the 17 releases 2025-01 … 2026-05.

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

**Grain.** 5 modes × 7 geographies (1 national + 6 zones) × 3 periods = **105 rows per release**,
**1,785** across the 17 releases. Periods are taken from columns 2, 3 and 4 **by position** — year-ago,
prior month, current month — never from the header text.

**Cross-sheet reconciliation.** The `NATIONAL` current-month fare in this table and the `Grand Total`
in `transport_fare_state_monthly` are the same figure reached independently. They are asserted equal
within a relative tolerance of 1e-12: 85 comparisons, 45 byte-identical, 40 precision-only, 0
substantive.

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

Counts below are for the **2026-09-13 acquisition snapshot**, window 2025-01-01 to 2026-09-13.
They are regression expectations for this snapshot, not invariants of the design — see the
structural rules beneath the table.

| Count | Value |
|---|---|
| **Physical rows in `fx_nfem_daily`** (in-window) | **425** |
| of which `record_status = 'ACTIVE'` | **419** |
| of which `record_status = 'EXACT_DUPLICATE'` | **6** |
| of which `record_status = 'DATE_CONFLICT'` | **0** |
| **Active analytical observations** | **419** |
| Latest observation | **2026-09-11** |

**The rules that actually hold, whatever the snapshot:**

- physical rows == the number of in-window records in the raw snapshot
- `ACTIVE` == the number of *distinct* in-window observation dates
- `EXACT_DUPLICATE` == in-window records − distinct dates
- `DATE_CONFLICT` == 0, or the run fails and no output is written

Validation asserts the structural rules *and* the frozen counts, so a changed snapshot fails loudly
for review rather than passing silently.

The six redundant records are **retained physically** and marked `EXACT_DUPLICATE`, not removed from
the table. Every record CBN published stays in the clean layer for auditability; the analysis view
supplies the clean daily series by filtering `record_status = 'ACTIVE'`.

This is why `source_id` is the primary key and `observation_date` is not: all 425 rows coexist, and
date uniqueness is enforced only across the 419 `ACTIVE` ones.

> Both kinds of absence appear on row 1: `interbank_turnover_usd` is `NULL` because nothing was
> published, while `nfem_deal_count` is `0` because zero was published.
>
> No row exists for the 24 weekdays with no observation — those dates are absent from the source
> entirely, which is different from being duplicated or conflicted. The exact 24 dates are listed in
> `docs/validation/cbn_nfem_validation.md`; 22 of them are corroborated by the acquisition evidence,
> the other 2 (2026-06-12, 2026-08-25) were derived from the snapshot when the cutoff was extended.

---

## 8. NERC electricity tariffs

Built by `src/cleaning/clean_nerc_tariffs.py`. DisCos resolve through
`data/reference/ref_disco.csv`.

> **What this table is.** *A validated July 2025 cross-section of complete text-extractable NERC MYTO
> tariff tables* — 11 of 217 acquired orders. It is **not** a complete 2025–2026 NERC tariff history.
> The other 206 orders are outside processed coverage: 27 partial, 1 heading-only, 178 with no usable
> tariff text, plus 22 `HOLDCO_YSS` files whose document type is unverified (D-45).

### `electricity_tariff_disco_period`

| disco_code | tariff_class | service_band | mdclass | tariff_ngn_per_kwh | period_start | period_end | period_label_raw | is_current_period | order_effective_date | vat_treatment |
|---|---|---|---|---|---|---|---|---|---|---|
| IE | A - Non-MD | A | NON_MD | 225.00 **[real]** | 2024-04-01 | 2024-04-30 | `Apr 2024` | FALSE | 2025-07-01 | UNSTATED |
| IE | A - Non-MD | A | NON_MD | 206.80 **[real]** | 2024-05-01 | 2024-06-30 | `May – Jun 2024` | FALSE | 2025-07-01 | UNSTATED |
| IE | A - Non-MD | A | NON_MD | 209.50 **[real]** | 2024-07-01 | 2025-07-31 | `Jul 2024 – Jul 2025` | **TRUE** | 2025-07-01 | UNSTATED |
| IE | Life-line | LIFELINE | NON_MD | 4.00 **[real]** | 2024-07-01 | 2025-07-31 | `Jul 2024 – Jul 2025` | **TRUE** | 2025-07-01 | UNSTATED |
| YEDC | D - MD2 | D | MD2 | 54.93 **[real]** | 2024-07-01 | 2025-07-31 | `Jul 2024 – Jul 2025` | **TRUE** | 2025-07-01 | UNSTATED |

**Logical key:** `(source_file, disco_code, tariff_class, period_start, period_end)` — **525 rows**.

**One row is one published tariff for one class over one period**, not one rate per DisCo-month.
Table 2 is a history table: rows are tariff classes, **columns are period ranges**. A single order
publishes three tariffs per class and puts one of them into force, so `source_file` is in the key —
without it two orders restating the same period would collide.

`is_current_period` is TRUE where `period_end`'s month equals `order_effective_date`'s month. It is a
selection convenience, never a substitute for the period columns: **the two historical columns are
restatements, not monthly tariff changes**, and must not be counted as such (D-42).

### Arithmetic

| | |
|---|---|
| Orders processed | 11 |
| Tariff classes | 17 (AEDC) + 17 (IE) + 13 (YEDC) + 8 × 16 = **175** |
| Period columns per class | 3 |
| **Tariff records** | 175 × 3 = **525** |
| Current-period records | 175 |

**YEDC publishes no Band E.** Its Table 2 has 13 classes and ends at `D - MD2`; no Band E row is
fabricated for it. AEDC and IE publish a 17th class, `A - MD2 Special`, that the other eight do not.
`service_band` and `mdclass` are split out of the published `tariff_class` and are never invented;
`tariff_class_raw` keeps the label exactly as the page printed it, en dash and all.

### Dates — three columns, never conflated

| Column | Source | Value across the 11 |
|---|---|---|
| `order_effective_date` | `COMMENCEMENT AND TERMINATION` clause only (D-39) | 2025-07-01 |
| `order_signed_date` | `Dated this …` signature block | *empty* — page 7 is an image in all 11 |
| `website_publication_date` | NERC site, via `nerc_myto_coverage.csv` | 2025-08-28 |

`signing_date_status` records **why** a signing date is absent (`NOT_IN_TEXT_LAYER`), and the row is
flagged `SIGNING_PAGE_NOT_IN_TEXT_LAYER`. Nothing is inferred from the effective month. Impossible
published dates found elsewhere in the corpus — `EEDC_February_2025_006.pdf` prints *"Dated this 30th
day of February 2025"* — are preserved with an anomaly flag rather than repaired, wherever they are
encountered.

> **`state` is deliberately absent.** DisCo licence areas cross state boundaries (D-44), so
> `ref_disco.csv` records `state_mapping = 'NOT_MAPPED'` for every DisCo and this table cannot be
> joined to the state-level datasets.
>
> **`vat_treatment` is `UNSTATED` on every row.** The orders approve tariffs in ₦/kWh and say nothing
> about VAT; nothing is inferred (D-43).
>
> **Every tariff requires individual human validation before use** — not a sample. Only rows with
> `validation_status = 'VALIDATED'` may enter analysis. See D-12.

---

## Key design summary

| Table | Primary key | Geography |
|---|---|---|
| `food_price_national_monthly` | `release_month, observation_month, item_code` | NATIONAL |
| `food_price_zone_monthly` | `observation_month, item_code, zone` | ZONE |
| `food_price_extreme_callout` | `observation_month, item_code, extreme_type, state` | STATE *(callout)* |
| `petrol_price_monthly` | `release_month, observation_month, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `diesel_price_monthly` | `release_month, observation_month, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `cooking_gas_price_monthly` | `release_month, observation_month, cylinder_size_kg, geography_type, geography_name` | STATE/ZONE/NATIONAL |
| `cooking_gas_extreme_callout` | `observation_month, cylinder_size_kg, extreme_type, state` | STATE *(callout)* |
| `transport_fare_state_monthly` | `observation_month, geography_type, geography_name, transport_mode` | STATE/NATIONAL |
| `transport_fare_zone_monthly` | `release_month, observation_month, transport_mode, geography_type, geography_name` | ZONE/NATIONAL |
| `cpi_index_monthly` | `release_month, observation_month, coverage, index_name, measure, index_base, is_working_sheet` | NATIONAL/URBAN/RURAL |
| `cpi_state_index_monthly` | `release_month, observation_month, state, index_name, measure` | STATE |
| `fx_nfem_daily` | `source_id` *(unique `observation_date` among ACTIVE rows)* | NATIONAL |
| `electricity_tariff_disco_period` | `source_file, disco_code, tariff_class, period_start, period_end` | DISCO |
| `ref_state_zone` | `alias_normalised` | STATE |

Four geographic levels are preserved deliberately. They are **not** flattened into a single state
table, because three of the eight sources do not publish state values at all.
