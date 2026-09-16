# PostgreSQL Analytical Layer — Schema Design

**Phase 2.** The database layer that sits between the 12 cleaned CSVs and the later SQL analysis and
BI tools. Design approved with ten corrections, all incorporated here.

Target server: **PostgreSQL 18**. Database: `nigeria_business_cost`.

---

## 0. What this layer must protect

The cleaning phase produced 29,032 rows whose value is not their size but their defensibility: every
row cites one source cell, every published defect is flagged rather than corrected, and index levels
carry a warning saying they must not be used to rank states. A database that loses those properties
has destroyed the project's only real asset.

So three rules shape everything below.

1. **Exact decimal preservation.** Measure values were written with `repr(float)` — up to 18 decimal
   places. They are stored as unconstrained `numeric`, never `double precision`.
2. **No grain is merged.** Twelve canonical grains stay twelve fact tables.
3. **Every safety rule is enforced by the database, or by an audit, not by an analyst remembering it.**

---

## 1. Architecture

Three schemas, loaded left to right, each with a different contract.

```
17 CSV files  ──▶  staging  ──▶  core  ──▶  mart
                   all text      typed,      views, panel,
                   1 table/CSV   keyed,      anomaly register
                   + load_audit  constrained BI-facing
```

| Schema | Contract | Contents |
|---|---|---|
| `staging` | The **parsed CSV field values, loaded as text** before typed conversion. Every column `text`; no casting, no constraints, no interpretation. **Not a byte-exact copy of the files.** | 17 `stg_*` tables + `load_audit` |
| `core` | Typed, keyed, constrained system of record inside PostgreSQL. | 12 `fact_*`, 14 `dim_*`, 1 bridge |
| `mart` | Read-only analytical surface. Each view encodes a safety rule. | `v_*`, `mv_*` |

### 1.1 What the staging layer does and does not prove

This wording is precise because the distinction matters.

- **File byte integrity is established by SHA-256.** Each of the 17 input files is hashed before it is
  read, and the digest is recorded in `staging.load_audit`. That — and only that — is what proves the
  file on disk is the file the cleaning phase produced.
- **PostgreSQL staging validates parsed field-text preservation before typed casting.** After `COPY`,
  every staged field is compared against the field as parsed from the CSV by an independent reader. That
  proves the CSV parse and the load agree on each field's text.
- **Parsed relational rows do not reproduce the original CSV bytes, and this design does not claim they
  do.** A relational row has no column order guarantee, no quoting, no line terminator and no header.
  Round-tripping a table back to a byte-identical CSV is not a property of the database and is not
  asserted anywhere in this layer.

The practical consequence: byte-level questions are answered by the hash in `load_audit`; field-level
questions are answered by the staging comparison; typed-value questions are answered by the numeric
round-trip check in §9.

### 1.2 Why unconstrained `numeric`

| Candidate | Problem |
|---|---|
| `double precision` | Re-introduces binary float drift into a project that deliberately preserved exact decimals |
| `numeric(38,18)` | Wide enough, but **pads trailing zeros** — `116.41` renders `116.410000000000000000` and stops matching source text |
| **`numeric`** (no typmod) | Stores the input scale exactly, returns it unpadded. `4.00` stays `4.00`, `88.46628971318219` stays intact |

Observed extremes: 10 integer digits (`nfem_turnover_usd`), 18 decimal digits (`cpi.value`). At 29,032
rows the performance cost of `numeric` over `float8` is irrelevant.

---

## 2. Staging layer

Seventeen tables, one per input file — **12 processed fact CSVs and 5 reference CSVs**.

Each table holds the **parsed CSV field values, loaded as text before typed conversion**. It is
**not** a byte-exact copy of the file, and nothing here claims it is: a relational row has no column
order guarantee, no quoting, no line terminator and no header. Which claim is proved by what:

| Claim | Proved by |
|---|---|
| The original input **file bytes** are unchanged | the **SHA-256** recorded in `load_audit` |
| The **parsed field text** survived the load | field-by-field comparison against an independent CSV reader after `COPY` |
| The **typed values** are faithful | the numeric round-trip check after `core` is loaded |

Every column is `text`, column names identical to the CSV header, plus two load columns:

```sql
stg_line_number  integer    -- 1-based data row, ordinal within the file
stg_load_id      bigint     -- FK to load_audit.load_id
```

### `staging.load_audit`

One row per file per load run.

| Column | Type | Purpose |
|---|---|---|
| `load_id` | `bigint` identity PK | |
| `load_run_id` | `uuid` | Groups the 17 files of one run |
| `source_path` | `text` | Repo-relative path |
| `target_table` | `text` | `staging.stg_*` |
| `file_kind` | `text` | `PROCESSED_FACT` or `REFERENCE` |
| `file_sha256` | `char(64)` | **Hash of the file as read** |
| `file_bytes` | `bigint` | |
| `csv_row_count` | `integer` | Data rows counted by an independent CSV reader |
| `loaded_row_count` | `integer` | `COUNT(*)` in the staging table after `COPY` |
| `column_count` | `integer` | |
| `field_text_match` | `boolean` | Parsed field-text preservation verified |
| `loaded_at` | `timestamptz` | |

A run is valid only when, for all 17 rows, `csv_row_count = loaded_row_count` and
`field_text_match = true`.

---

## 3. Dimensions

Fourteen dimensions, **341 rows** in total (+621 optional).

| Dimension | Rows | Natural key | Notes |
|---|---|---|---|
| `dim_zone` | 6 | `zone_name` | The six geopolitical zones |
| `dim_state` | 37 | `state_name` | 36 states + Abuja (FCT); carries `zone_id` |
| `dim_state_alias` | 39 | `alias_normalised` | From `ref_state_zone`. Unique by construction — this is the join key |
| `dim_state_alias_observed` | 77 | — | From `ref_state_alias_observed`. **Provenance only, never joined** |
| `dim_geography` | 44 | `(geography_type, geography_name)` | 37 STATE + 6 ZONE + 1 NATIONAL |
| `dim_month` | 31 | `month_date` | 2024-01 … 2026-07, contiguous |
| `dim_food_item` | 42 | `item_code` | `unit`, `unit_source`, `unit_evidence`. **19 units legitimately NULL** |
| `dim_transport_mode` | 5 | `transport_mode` | AIR, BUS_INTERCITY, BUS_INTRACITY, OKADA, WATER |
| `dim_cpi_measure` | 3 | `measure` | INDEX→INDEX_2024_100; both CHANGE_*→PERCENT |
| `dim_disco` | 12 | `disco_code` | `state_mapping = 'NOT_MAPPED'` on all 12, kept explicit |
| `dim_nerc_order` | 11 | `order_number` | **New.** Order-level metadata, §3.2 |
| `dim_tariff_class` | 17 | `tariff_class` | `service_band` (A–E, LIFELINE) + `mdclass`; both FDs verified |
| `dim_tariff_period` | 3 | `period_position` | The three published period columns |
| `dim_anomaly_flag` | 14 | `flag_code` | Every observed flag, its meaning and decision-log reference |
| `dim_date` *(optional)* | 621 | `date` | Daily calendar for FX, only if BI needs it |

### 3.1 `dim_geography` owns the geography rules

**Correction 2.** Facts reference `geography_id` and nothing else. `geography_type`, `state_id`,
`zone_id` and `is_aggregate` live in `dim_geography`, where the structural constraints are declared
**once** instead of being duplicated onto six fact tables:

```sql
CHECK (geography_type IN ('STATE','ZONE','NATIONAL'))
CHECK ((geography_type = 'STATE')    = (state_id IS NOT NULL))
CHECK ((geography_type = 'NATIONAL') = (zone_id  IS NULL))
CHECK (is_aggregate = (geography_type <> 'STATE'))
UNIQUE (geography_type, geography_name)
```

`dim_geography` is a convenience, **not a flattening** — `geography_type` rides on every row, so the
STATE / ZONE / NATIONAL distinction survives every join.

> **The rule it carries: never aggregate across `geography_type`.** A `SUM` over a fuel fact without a
> `geography_type` filter counts the country three times. The `mart` views always filter; direct `core`
> queries must do so by hand.

**Known limitation, stated rather than hidden.** Because `geography_type` is deliberately *not* copied
onto the facts, a table constraint cannot assert "CPI facts must be STATE geography" — that would need
a composite FK on `(geography_id, geography_type)`, which reintroduces the duplication this correction
removed. Those assertions are therefore enforced in the independent audit (§11), not by DDL. This is a
conscious trade: one normalisation rule beats one extra constraint.

### 3.2 `dim_nerc_order`

**Correction 3.** The 11 processed July 2025 MYTO orders, with everything that is a property of the
*order* rather than of a tariff row.

| Column | Notes |
|---|---|
| `order_id` | identity PK |
| `order_number`, `order_number_raw` | e.g. `ORDER/NERC/2025/059` |
| `disco_id` | FK → `dim_disco`; one order per DisCo in this corpus |
| `source_file` | The PDF |
| `order_effective_date`, `order_effective_date_raw` | From the COMMENCEMENT clause only (D-39) |
| `order_signed_date`, `signing_date_raw` | **NULL on all 11** — page 7 is an image |
| `signing_date_status` | `NOT_IN_TEXT_LAYER` — records *why* it is absent |
| `website_publication_date` | 2025-08-28 |
| `vat_treatment` | `UNSTATED` (D-43) |
| `extraction_method`, `validation_status` | `PDF_TEXT_LAYER`, `VALIDATED` |
| `source_page`, `source_table_label` | Page 4, `Table – 2: Approved Allowed Tariffs` |
| `source_anomaly` | `SIGNING_PAGE_NOT_IN_TEXT_LAYER` |

This removes 11 order-level attributes from 525 fact rows and makes the effective-date / signing-date /
publication-date separation (D-39) structural rather than conventional.

---

## 4. Fact tables

Twelve facts, one per verified grain. Each has a surrogate `bigint` identity PK plus a **UNIQUE
constraint on the canonical natural key** — the natural key is what validates the load, the surrogate
is what BI tools want.

| Fact table | Natural key | Measure | Rows |
|---|---|---|---|
| `fact_fx_rate_daily` | `source_id` | 5 rates, 2 turnovers, 2 deal counts | 425 |
| `fact_petrol_price_monthly` | `release_month, observation_month, geography_id` | `price_ngn_per_litre` | 2,040 |
| `fact_diesel_price_monthly` | `release_month, observation_month, geography_id` | `price_ngn_per_litre` | 2,244 |
| `fact_lpg_price_monthly` | + `cylinder_size_kg` | `refill_price_ngn` | 4,224 |
| `fact_lpg_extreme_callout` | `release_month, observation_month, cylinder_size_kg, extreme_type, geography_id` | `price_ngn` | 193 |
| `fact_transport_fare_state_monthly` | `release_month, observation_month, geography_id, transport_mode_id` | `fare_ngn` | 3,230 |
| `fact_transport_fare_zone_monthly` | `release_month, observation_month, transport_mode_id, geography_id` | `fare_ngn` | 1,785 |
| `fact_food_price_national_monthly` | `release_month, observation_month, item_id` | `avg_price_ngn` (nullable) | 2,142 |
| `fact_food_price_zone_monthly` | `release_month, observation_month, item_id, geography_id` | `avg_price_ngn` | 4,284 |
| `fact_food_extreme_callout` | `release_month, observation_month, item_id, extreme_type, geography_id` | `price_ngn` | 1,428 |
| `fact_cpi_state_monthly` | `release_month, observation_month, geography_id, cpi_group, cpi_measure_id` | `value` | 6,512 |
| `fact_electricity_tariff` | `order_id, tariff_class_id, tariff_period_id` | `tariff_ngn_per_kwh` | 525 |
| | | **Total** | **29,032** |

### 4.0 Every natural key carries `release_month`

All twelve facts include `release_month` in the natural key. For six of them this is load-bearing:
their sheets publish three periods per release, so the same `observation_month` legitimately appears
under several releases.

For four — `fact_lpg_extreme_callout`, `fact_transport_fare_state_monthly`,
`fact_food_price_zone_monthly` and `fact_food_extreme_callout` — the source sheets publish only one
period per release, and `observation_month = release_month` on **every** row. Measured before and
after widening, the key cardinality is identical: **193 / 3,230 / 4,284 / 1,428**, equal to the row
counts. Including `release_month` therefore changes nothing about today's data.

It is included anyway, because omitting it would make the constraint set contradict itself:

| Rule | Says about a restatement (`observation_month < release_month`) |
|---|---|
| `*_order_ck CHECK (observation_month <= release_month)` | **permitted** |
| a natural key without `release_month` | **rejected** with a unique violation |

Those four sheets spend their columns on a non-time dimension — six zones, five transport modes, or a
Highest/Lowest pair — which is *why* only one period appears per release. `Zone All item` is the
clearest case: it carries no period label at all, and its month was established by the weighted
reconciliation (D-31). So a restatement is not expressible in the source as it stands today.

But "not expressible today" is an observation about 16–17 releases, not a guarantee. This corpus has
already seen NBS move header rows, change a base mid-series and ship a legacy `.xls`. If a corrected
earlier month ever appears, it must be **stored as a new publication, not rejected** — which is the
project rule stated for CPI in D-53: nothing is collapsed onto a latest value; every publication keeps
its own row, told apart by `release_month`.

**Correction 1** applied: `fact_fuel_price_monthly` → **`fact_petrol_price_monthly`**. Petrol and diesel
remain separate tables — separate NBS publications, independently moving header rows, and different
zone-block structures (diesel publishes 3 periods per zone row, petrol 1: 132 vs 120 rows per release).

### 4.1 Provenance block

On all 10 spreadsheet facts: `source_file`, `source_member`, `source_sheet`, `source_row`,
`source_column_index`, `source_cell_reference`, `source_period_label`.

```sql
-- encodes the one-cell-one-row rule; NULLS NOT DISTINCT because
-- source_member is NULL for loose (non-ZIP) workbooks
UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference)
```

Verified unique in 9 of 10 spreadsheet facts. The exception is `fact_lpg_extreme_callout` — 192 cells
→ 193 rows, the documented tie. It gets the weaker form instead:

```sql
CHECK (tie_member_count = 1 OR is_shared_extreme)
```

### 4.2 Anomaly columns

**Correction 9.** `source_anomaly` is stored **verbatim** — byte-exact, never re-serialised, because it
is provenance. A generated column handles the separator inconsistency (food and CPI use `|`, petrol
uses `;`) without touching the stored text:

```sql
source_anomaly_flags text[] GENERATED ALWAYS AS (
  CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
       ELSE regexp_split_to_array(source_anomaly, '[|;]') END
) STORED
```

and `core.bridge_fact_anomaly` (§7) gives BI tools a normalised relational path that needs no string
parsing at all.

---

## 5. Constraints

Every constraint below was tested against the actual CSV data and **passes** at the CSV level.

> **What a constraint failure means.** It does **not** automatically mean the load is wrong. A
> failure is a signal to investigate, and the cause may be any of:
>
> 1. **loading / transformation** — the loader mapped, joined or ordered something incorrectly;
> 2. **SQL implementation** — the constraint is written differently from the rule it intends;
> 3. **casting or NULL semantics** — `''` versus `NULL`, numeric scale, date coercion, or
>    three-valued logic making a predicate behave unlike the Python check that validated it;
> 4. **an incorrect constraint expression** — right idea, wrong predicate;
> 5. **an invalid design assumption** — the rule itself does not hold on this data.
>
> The required response is to **report the evidence first** — the failing rows, their source cells,
> and which of the five causes the evidence supports — and only then change the data, the loader or
> the rule. A constraint is never weakened merely to make a run pass.

**Period semantics** (10 monthly facts):

```sql
CHECK (release_month     = date_trunc('month', release_month)::date)
CHECK (observation_month = date_trunc('month', observation_month)::date)
CHECK (observation_month <= release_month)
```

**`is_primary_release` is one-way — this is the subtle one:**

```sql
CHECK (NOT is_primary_release OR observation_month = release_month)
```

Not an equality. CPI has **74 rows where `observation_month = release_month` but
`is_primary_release = FALSE`** — the April 2025 alignment-disputed rows, deliberately demoted under
D-52. An equality constraint would reject them and destroy the defect handling.

**Value integrity:**

```sql
-- food: a blank is never a zero
CHECK ((avg_price_ngn IS NULL) = (value_status = 'NOT_REPORTED'))
CHECK (price_ngn_per_litre > 0)          -- and every other NGN measure
```

**CPI — the D-48 rule, enforced by the database:**

```sql
CHECK (cpi_group IN ('FOOD','ALL_ITEMS'))
CHECK (base_period = '2024=100')
-- measure/unit agreement lives in dim_cpi_measure, declared once
```

**NERC:**

```sql
CHECK (period_end >= period_start)                   -- dim_tariff_period
CHECK (validation_status = 'VALIDATED')              -- dim_nerc_order, D-12
CHECK (vat_treatment = 'UNSTATED')                   -- dim_nerc_order, D-43
CHECK (tariff_ngn_per_kwh > 0)
```

The NERC current-period rule — logically *"`(order_id, tariff_class_id)` must be unique where
`is_current_period` is true"* — **must be a partial unique INDEX, not a partial UNIQUE table
constraint.** PostgreSQL has no `UNIQUE (...) WHERE ...` table-constraint syntax; uniqueness that
applies to only some rows is expressible only as a unique partial index:

```sql
-- Correction 3: scoped to the ORDER, not the DisCo
CREATE UNIQUE INDEX IF NOT EXISTS tariff_current_period_uix
    ON core.fact_electricity_tariff (order_id, tariff_class_id)
    WHERE is_current_period;
```

**CBN:**

```sql
CHECK (record_status IN ('ACTIVE','EXACT_DUPLICATE'))
CHECK ((duplicate_of_source_id IS NOT NULL) = (record_status = 'EXACT_DUPLICATE'))
CHECK (lowest_rate_ngn_per_usd <= highest_rate_ngn_per_usd)   -- holds 425/425
CREATE UNIQUE INDEX ON fact_fx_rate_daily (observation_date) WHERE record_status = 'ACTIVE';
```

### 5.1 Two constraints deliberately NOT declared

1. **`lowest <= nfem_rate <= highest`.** Fails on 5 of 425 CBN rows — the closing rate falls outside the
   published band on 4 days, and on **2026-03-06 the headline NFEM rate itself** (1393.2556) sits below
   the published low (1398.0000). This is published source data, not a cleaning error. It is surfaced by
   `mart.v_fx_band_exceptions` and recorded as a source characteristic.
2. **`nfem_deal_count = 0` implies `nfem_turnover_usd IS NULL`.** 297 rows fit; 3 rows have a real deal
   count with NULL turnover and 1 row has a literal `0` turnover with populated interbank. The
   blank-versus-zero distinction is real and irregular — it must not be forced into a rule.

---

## 6. Indexes

At 29k rows indexes are for join ergonomics and constraint enforcement, not scale. Do not over-index.

```sql
-- the dominant analytical filter
CREATE INDEX ON core.fact_<x> (observation_month) WHERE is_primary_release;
-- geography-then-time, the natural BI drill path
CREATE INDEX ON core.fact_<x> (geography_id, observation_month);
-- CPI: measure leads, because INDEX and PERCENT rows are never queried together
CREATE INDEX ON core.fact_cpi_state_monthly (cpi_measure_id, observation_month, geography_id);
-- anomaly triage
CREATE INDEX ON core.fact_<x> USING gin (source_anomaly_flags);
CREATE INDEX ON core.fact_<x> (observation_month) WHERE source_anomaly IS NOT NULL;
```

Skipped: indexes on `source_file` / `source_sheet` (low cardinality, provenance only) and any index on
`release_month` alone — it is always used together with `observation_month`.

---

## 7. The anomaly bridge

**Correction 9.** BI tools must never have to split a string.

```sql
CREATE TABLE core.bridge_fact_anomaly (
  fact_table text   NOT NULL,
  fact_id    bigint NOT NULL,
  flag_code  text   NOT NULL REFERENCES core.dim_anomaly_flag(flag_code),
  PRIMARY KEY (fact_table, fact_id, flag_code)
);
```

One row per (fact row × flag). Populated from `source_anomaly_flags`, so the verbatim text stays
authoritative and the bridge is derived.

**Polymorphic key, stated honestly.** `fact_id` cannot carry a real FK because it points at twelve
different tables. Integrity is asserted in the audit: every `(fact_table, fact_id)` must resolve, and
every flag instance in `source_anomaly` must appear in the bridge and vice versa.

BI does not consume the bridge directly — it consumes `mart.v_anomaly_register`, which resolves the
bridge into a flat table of dataset, month, geography, flag code, flag meaning and decision reference.

---

## 8. Analytical layer

### 8.1 The state cost panel is LONG, not wide

**Correction 7.** Joining the state facts on `(state_id, observation_month)` is unsafe because three of
them are **not** one row per state-month:

| Dataset | Rows per state-month | Why |
|---|---|---|
| Petrol | 1 | — |
| Diesel | 1 | — |
| **LPG** | **2** | 5 kg and 12.5 kg cylinders |
| **Transport** | **5** | AIR, BUS_INTERCITY, BUS_INTRACITY, OKADA, WATER |
| **CPI** | **6** | 2 groups × 3 measures |

A naive five-way join produces `1 × 1 × 2 × 5 × 6 = 60` rows per state-month — a 60× Cartesian
multiplication that would silently inflate every average.

**Chosen approach: a long metric panel.**

```sql
mart.mv_state_cost_panel_monthly (
  state_id, state_name, zone_name,
  observation_month,
  metric_code, metric_value, unit,
  source_dataset, release_month, source_anomaly_flags
)
-- grain: (state_id, observation_month, metric_code) — unique by construction
```

Fifteen metric codes, each fully qualifying its own dimension so nothing is left implicit:

```
PETROL_PRICE_NGN_PER_LITRE          CPI_ALL_ITEMS_INDEX
DIESEL_PRICE_NGN_PER_LITRE          CPI_FOOD_INDEX
LPG_REFILL_5KG_NGN                  CPI_ALL_ITEMS_YOY_PCT
LPG_REFILL_12_5KG_NGN               CPI_FOOD_YOY_PCT
TRANSPORT_AIR_NGN_PER_JOURNEY       CPI_ALL_ITEMS_MOM_PCT
TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY   CPI_FOOD_MOM_PCT
TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY
TRANSPORT_OKADA_NGN_PER_JOURNEY
TRANSPORT_WATER_NGN_PER_JOURNEY
```

**Why long rather than pre-pivoted.** Both were viable. Long wins here because:

- the grain is unique by construction, so a Cartesian join is not merely avoided but *impossible*;
- adding a metric later is a row, not a schema migration;
- the datasets have ragged coverage (LPG ends 2026-04, CPI starts 2025-02) — a wide table would fill
  the gaps with NULL columns that look like zero to a careless aggregate, whereas a long table simply
  has no row, which is the honest representation of "not published";
- `unit` travels with each value, so an index level and a naira price can never be summed by accident.

A pivoted convenience view `mart.v_state_cost_panel_wide` is provided on top for tools that need it,
built with explicit `FILTER` aggregates over the long panel — pivoting *after* reduction, never joining
before it.

### 8.1a Publication selection — every mart object must say which version it means

Widening the four natural keys (§4.0) made a restatement *storable*. That in turn made it mandatory
for every mart object reading those tables to state **which publication** it returns, instead of
assuming there is only one.

**Two primary rules exist, because the facts are not uniform:**

| Facts | Primary publication is | Why |
|---|---|---|
| petrol, diesel, LPG, transport zone, food national, CPI | `is_primary_release = TRUE` | the column exists; CPI additionally demotes 74 disputed rows (D-52), so it is **not** simply a date comparison |
| LPG callout, transport state, food zone, food callout | `release_month = observation_month` | no `is_primary_release` column — their sheets publish one period per release, so the rule is structural |

The second rule is **computed, never hard-coded**. `v_state_dataset_windows` previously asserted
`true` for transport's primary flag; that would have let a restatement drag the primary window
forward. It now evaluates `release_month = observation_month`.

**Publication views:**

| View | Returns |
|---|---|
| `v_transport_state_primary` | `release_month = observation_month` |
| `v_transport_state_latest_restatement` | greatest `release_month` per `(observation_month, geography_id, transport_mode_id)` |
| `v_food_zone_primary` | `release_month = observation_month` |
| `v_food_zone_latest_restatement` | greatest `release_month` per `(observation_month, item_id, geography_id)` |

Both `latest` views use `DISTINCT ON` with a **surrogate-key tie-break** (`… release_month DESC,
<pk> DESC`), so the result is deterministic even if two rows ever shared a release month.

**Which rule each business object uses:**

| Object | Rule | Reason |
|---|---|---|
| `mv_state_cost_panel_monthly` | **primary** throughout | every other input to the panel is primary; mixing would break the grain |
| `v_transport_mode_comparison` | **primary** | stated explicitly rather than silently returning all versions |
| `v_food_zone_vs_national` | **primary zone vs primary national** | compares like with like |
| `v_food_zone_vs_national_latest` | **latest vs latest** | exposed separately, with both release months visible, rather than blended into the default |

> **Never mix the two semantics in one aggregate.** A primary figure and a restated figure answer
> different questions: "what was first published for that month" versus "what is currently believed".

**The two callout tables** (`fact_lpg_extreme_callout`, `fact_food_extreme_callout`) feed no business
view. They appear only in `v_coverage_matrix`, which is a raw per-month row count with no uniqueness
assumption, and in the anomaly bridge and register, which key on the surrogate `fact_id`. Neither
assumes one publication per observation, so **no publication views were added for them** — symmetry is
not a reason to create objects nobody reads.

`mv_cross_release_stability` was extended to all four widened-key facts. It contributes zero rows
while no restatement exists and would surface one immediately if it appeared.

**Proof rather than assertion.** Because every current row has `release_month = observation_month`,
the live data cannot demonstrate any of this. `src/database/simulate_restatement.py` injects a
restatement into transport state and food zone inside a transaction, checks the whole mart layer, and
**rolls back** — nothing synthetic is ever committed. It proves core stores both versions, primary
views return the original, latest views return the newer, the panel grain and its unique index
survive, `v_food_zone_vs_national` does not duplicate, the primary window is not dragged forward, and
the stability monitor surfaces both restatements. **15 of 15 checks pass.**

### 8.2 Two windows, recorded separately

**Correction 8.** These are different concepts and are never conflated.

| Window | Span | Definition |
|---|---|---|
| **Available observation window** | **2025-01 → 2026-04** (16 months) | Intersection of `observation_month` across the five state-grain datasets, counting **every** published row including restatements |
| **Primary-release common window** | **2025-02 → 2026-04** (15 months) | Intersection over rows that are each dataset's own first publication of that month |

They differ because CPI's first release is February 2025: January 2025 CPI exists in the data only as
another release's prior-month or year-ago column, never as a primary publication.

Both are exposed as data in `mart.v_analysis_windows` and asserted by the audit. The panel carries
`in_available_window` and `in_primary_release_window` booleans so an analyst picks a window explicitly
rather than by accident.

### 8.3 Views

**Safety views** — build first, they encode the rules:

| View | Purpose |
|---|---|
| `v_<fact>_primary` | `WHERE is_primary_release` per overlapping fact. The default an analyst should reach for |
| `v_<fact>_latest_restatement` | Most recent `release_month` per observation — "best current estimate" |
| `v_anomaly_register` | Every flagged row across all 12 facts, flag meaning resolved |
| `v_coverage_matrix` | Rows per dataset per month, so a gap is visible rather than inferred |
| `v_analysis_windows` | The two windows above, as data |
| `v_fx_band_exceptions` | The 5 CBN rows outside their own published band |

**Business views:**

| View | Content |
|---|---|
| `mv_state_cost_panel_monthly` | The long state panel above. **Not** a composite index — no business-cost index has been defined |
| `v_state_cost_panel_wide` | Pivoted convenience layer over the panel |
| `v_cpi_state_inflation` | `CHANGE_*` rates only — **never index levels** |
| `v_fuel_price_spread` | Highest vs lowest state per fuel per month, with zones |
| `v_food_zone_vs_national` | Zone premium/discount to national per item per month |
| `v_transport_mode_comparison` | Fare by mode across states, mode by mode |
| `v_tariff_band_cross_section` | July 2025 NERC tariffs by DisCo and band, labelled a cross-section |
| `v_fx_monthly_summary` | FX aggregated to month from `ACTIVE` rows only |
| `mv_cross_release_stability` | Where restatements disagree, by dataset |

**Correction 6** applied: the panel is `mv_state_cost_panel_monthly`. There is **no**
`mv_state_cost_index_monthly`, because no composite business-cost index has been defined yet. Naming a
view "index" before defining one would imply an aggregation method that does not exist.

---

## 9. Relationships that are unsafe or unsupported

| ❌ Do not | Why |
|---|---|
| Join NERC tariffs to any state dataset | DisCo licence areas cross state boundaries; `state_mapping = 'NOT_MAPPED'` on all 12 (D-44) |
| Rank or compare states by CPI `INDEX` level | NBS prints the prohibition inside the table; `comparability_warning` is on all 6,512 rows. `CHANGE_*` rates may be compared |
| Treat food callout states as a state price series | Callouts are only the highest and lowest state per item per month — an extremes sample, not coverage |
| Derive state-level food prices from zone values | Food has a hard source ceiling at zone level |
| Treat the 525 NERC rows as a tariff history | One effective date across all 11 orders; the three period columns are historical context published *inside* a July 2025 order |
| Sum or average across `geography_type` | STATE + ZONE + NATIONAL coexist in the fuel facts |
| Join state facts directly on `(state_id, observation_month)` | LPG ×2, transport ×5, CPI ×6 — see §8.1 |
| Mix CPI `INDEX` and `CHANGE_*` in one aggregate | Different units; ranges overlap (index 88–169, changes −14 to +64) |
| Assume a shared end date | LPG 2026-04, most NBS 2026-05, CPI 2026-07, FX 2026-09-11 |
| Treat the 74 disputed April 2025 CPI rows as primary | `is_primary_release = FALSE` by design; never recompute it from date equality |

---

## 10. Permission model

**Correction 10.** Three roles, least privilege, and the BI reader never touches staging.

```sql
CREATE ROLE nbci_owner      NOLOGIN;   -- owns every object
CREATE ROLE nbci_etl        NOLOGIN;   -- writes staging + core
CREATE ROLE nbci_bi_reader  NOLOGIN;   -- reads mart only
```

| Role | `staging` | `core` | `mart` |
|---|---|---|---|
| `nbci_owner` | owner | owner | owner |
| `nbci_etl` | USAGE + full DML | USAGE + full DML | USAGE + SELECT |
| `nbci_bi_reader` | **no USAGE** | **no USAGE** | USAGE + SELECT |

The BI reader has **no `USAGE` on `staging` or `core` at all** — not merely no `SELECT`. It cannot see
that those schemas exist.

This works because `mart` views are owned by `nbci_owner` and PostgreSQL runs a view with its **owner's**
privileges (`security_invoker` defaults to `false`). The reader selects a view that reads `core` without
itself holding any `core` privilege. Materialized views are refreshed by `nbci_etl`.

Login roles (e.g. `nbci_app`, `nbci_bi`) are granted the appropriate NOLOGIN role. Passwords are never
stored in this repository.

### 10.1 Privileges must be granted AFTER the objects exist

`01_schemas_roles.sql` creates the roles and schemas and grants schema `USAGE`. It **cannot** grant
table privileges, and an early version of this design wrongly assumed it could. Two things defeated it:

- `GRANT … ON ALL TABLES IN SCHEMA` affects only the tables that exist **at that instant**, and script
  01 runs first, when both schemas are empty.
- `ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner` never fired, because the objects are created by the
  connecting role, not by `nbci_owner`.

The result was a permission model that read correctly and granted nothing: `nbci_etl` held **0
privileges on all 45 tables and 24 sequences**, and `nbci_bi_reader` could see the `mart` schema while
being able to `SELECT` **none of its 30 objects**.

It survived review because the audit asserted `has_schema_privilege('nbci_etl','core','USAGE')` and
called that write access. **Schema USAGE is not access.** The audit now verifies every
`SELECT/INSERT/UPDATE/DELETE/TRUNCATE` on every table, `USAGE` on every sequence, and that the reader
can actually read all 30 mart objects.

`sql/11_grants.sql` runs **last** and fixes both halves:

1. **Ownership** — every table, view and materialized view is reassigned to `nbci_owner`. The design
   depends on mart views running with their *owner's* privileges; that is only true if `nbci_owner`
   actually owns them. (Sequences are skipped: one owned by an identity column follows its table.)
2. **Privileges** — explicit grants once every object exists, plus `ALTER DEFAULT PRIVILEGES` scoped
   both to the current role and to `nbci_owner`, so an object added later inherits the same shape
   instead of arriving with no grants.

### 10.1a `MAINTAIN` — refreshing a materialized view needs more than SELECT

PostgreSQL 17 introduced the **`MAINTAIN`** privilege, and from 17 onward `REFRESH MATERIALIZED VIEW`
requires it from any role that is not the object's owner. `SELECT` is not sufficient.

The design said `nbci_etl` refreshes the materialized views. On PostgreSQL 18.3 that was **false**,
and the proof is an execution, not a catalog read — with `SELECT` alone:

```text
SET ROLE nbci_etl;
REFRESH MATERIALIZED VIEW mart.mv_state_cost_panel_monthly;
-- InsufficientPrivilege: permission denied for materialized view
```

| Role | `SELECT` | `MAINTAIN` | Can refresh |
|---|---|---|---|
| `nbci_owner` (owner) | ✔ | ✔ | ✔ |
| `nbci_etl` | ✔ | ✔ | ✔ |
| `nbci_bi_reader` | ✔ | **✘** | **✘** |

**How future materialized views receive `MAINTAIN`.** By **object class**, in a loop in
`11_grants.sql` restricted to `relkind = 'm'` in `mart`. The loop is not a trigger and not a default
privilege: a materialized view receives `MAINTAIN` **when `11_grants.sql` is next run**, which the
normal clean-build workflow does on every rebuild because `11_grants.sql` runs last. A materialized
view created by hand outside that workflow holds no `MAINTAIN` until `11_grants.sql` is run again.

```sql
FOR r IN SELECT n.nspname, c.relname FROM pg_class c
         JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'mart' AND c.relkind = 'm'
LOOP
    EXECUTE format('GRANT MAINTAIN ON %I.%I TO nbci_etl', ...);
    EXECUTE format('REVOKE MAINTAIN ON %I.%I FROM nbci_bi_reader', ...);
END LOOP;
```

**Why not `ALTER DEFAULT PRIVILEGES`.** It would have to be written `GRANT MAINTAIN … ON TABLES`, and
in PostgreSQL that object class covers ordinary tables and plain views as well as materialized views.
That would hand `MAINTAIN` to 28 objects in `mart` alone that can never be refreshed, plus every table
in `staging` and `core` if applied there — unnecessary privilege on unrelated objects.

The loop is both simpler and tighter: a materialized view added later is covered by re-running
`11_grants.sql` with no edit to it, and nothing else ever receives the privilege. The audit asserts
this directly — `MAINTAIN` is held on both matviews and on **zero** ordinary tables or plain views.

**Verified by execution, not inspection.** The audit performs `SET ROLE nbci_etl` and actually runs
`REFRESH MATERIALIZED VIEW` on both matviews, then `SET ROLE nbci_bi_reader` and confirms both are
refused with `InsufficientPrivilege` while `SELECT` still succeeds. A `lock_timeout` distinguishes a
genuine privilege refusal from a lock wait, and the audit connection commits first to release its own
`ACCESS SHARE` locks — without that, the refresh blocks on the auditor's own read.

### 10.2 What "independent audit" has to mean

The audit originally read `staging.load_audit.field_text_match` — a boolean the **loader** wrote — and
treated it as proof that staging matched the CSVs. That is circular: it verified the loader against
itself.

`audit_database.py` now re-parses all 17 CSVs with its own reader and compares **every field of every
row** against staging in `stg_line_number` order, excluding only `stg_line_number` and `stg_load_id`.
That is **644,578 field comparisons**. The loader's boolean is still checked, but only as a *secondary*
reconciliation, explicitly labelled as such.

The same principle applies to the load run: the audit identifies **one** `load_run_id` and proves that
single run contains 17 files, 12 processed facts, 5 references, the expected hashes and the expected
counts — rather than assembling a "latest" picture per file from records that could span different
runs. It also proves no staging row belongs to any other run.


---

## 11. Independent database audit

Same discipline as the cleaning phase: the auditor **never imports the cleaning code** and never reads
the cleaners' constants. It re-derives every figure from (a) the CSV files and (b) the database, then
compares.

Assertions:

1. 17 staging tables, row counts equal to independently counted CSV rows
2. All 17 SHA-256 digests recorded and matching a fresh hash of each file
3. Field-text preservation true for all 17
4. 12 fact tables, counts per §12, total exactly **29,032**
5. 14 dimension counts as designed
6. Zero orphans on every declared FK
7. Every CHECK and UNIQUE constraint present and validated
8. **Numeric round-trip**: for every measure column, the typed `numeric` cast back to text equals the
   staging text for all rows
9. Geography-type assertions that DDL cannot express (CPI is STATE-only, callouts are STATE-only,
   food zone facts are ZONE-only)
10. Panel grain unique on `(state_id, observation_month, metric_code)`
11. Anomaly bridge complete and symmetric with `source_anomaly`
12. Both windows equal to the documented spans

---

## 12. Expected row counts

**Staging — 17 tables.** 12 processed fact CSVs (29,032 rows) + 5 reference CSVs (176 rows).

| Reference file | Rows |
|---|---|
| `ref_state_zone.csv` | 39 |
| `ref_state_alias_observed.csv` | 77 |
| `ref_transport_mode.csv` | 6 |
| `ref_food_item.csv` | 42 |
| `ref_disco.csv` | 12 |
| **Total reference** | **176** |

**Core facts — 29,032.**

| Fact | Rows |
|---|---|
| `fact_cpi_state_monthly` | 6,512 |
| `fact_food_price_zone_monthly` | 4,284 |
| `fact_lpg_price_monthly` | 4,224 |
| `fact_transport_fare_state_monthly` | 3,230 |
| `fact_diesel_price_monthly` | 2,244 |
| `fact_food_price_national_monthly` | 2,142 |
| `fact_petrol_price_monthly` | 2,040 |
| `fact_transport_fare_zone_monthly` | 1,785 |
| `fact_food_extreme_callout` | 1,428 |
| `fact_electricity_tariff` | 525 |
| `fact_fx_rate_daily` | 425 |
| `fact_lpg_extreme_callout` | 193 |
| **Total** | **29,032** |

**Dimensions — 341.** `dim_zone` 6, `dim_state` 37, `dim_state_alias` 39,
`dim_state_alias_observed` 77, `dim_geography` 44, `dim_month` 31, `dim_food_item` 42,
`dim_transport_mode` 5, `dim_cpi_measure` 3, `dim_disco` 12, `dim_nerc_order` 11,
`dim_tariff_class` 17, `dim_tariff_period` 3, `dim_anomaly_flag` 14.

**Secondary assertions:**

| Assertion | Expected |
|---|---|
| CPI by measure | INDEX 3,922 / MoM 1,332 / YoY 1,258 |
| CPI `is_primary_release` | 3,848 (not 3,922 — 74 demoted) |
| CPI `STATE_VALUE_ALIGNMENT_DISPUTED` | 74 |
| Petrol geography split | STATE 1,887 / ZONE 102 / NATIONAL 51 |
| Diesel geography split | STATE 1,887 / ZONE 306 / NATIONAL 51 |
| LPG geography split | STATE 3,552 / ZONE 576 / NATIONAL 96 |
| NERC | 11 orders × 175 classes × 3 periods = 525; 1 effective date |
| CBN | 419 ACTIVE + 6 EXACT_DUPLICATE; 419 distinct ACTIVE dates |
| Food NULL prices | 195 national (all `NOT_REPORTED`), 0 zone |
| Available observation window | 2025-01 → 2026-04 |
| Primary-release common window | 2025-02 → 2026-04 |

---

## 13. Implementation order

| # | Step | Gate |
|---|---|---|
| 1 | This document | — |
| 2 | DDL under `sql/` | — |
| 3 | Create `staging`, `core`, `mart` + roles | — |
| 4 | Create `load_audit` | — |
| 5 | Create 17 staging tables | — |
| 6 | Load 17 CSVs; verify hashes and row counts | 17/17 hash + count + field-text match |
| 7 | Build 14 dimensions | Counts match §12 |
| 8 | Build 12 facts | Counts match §12; total 29,032 |
| 9 | Numeric round-trip verification | Every measure column round-trips |
| 10 | Add FKs | 0 orphans |
| 11 | Add CHECK and UNIQUE constraints | All validate |
| 12 | Add indexes | — |
| 13 | Safety views + state cost panel | Panel grain unique; both windows correct |
| 14 | Anomaly bridge | Symmetric with `source_anomaly` |
| 15 | Independent database audit | All assertions pass |

---

## 14. Decisions recorded

New decision-log entries accompany this design: **D-55** (three-schema architecture and the staging
contract), **D-56** (unconstrained `numeric` for exact decimal preservation), **D-57** (geography rules
owned by `dim_geography`), **D-58** (the long state panel and why not a wide join), **D-59** (two
windows recorded separately), **D-60** (verbatim `source_anomaly` plus a derived bridge).
