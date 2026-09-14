# Cleaning Rulebook

**Design only. No data has been cleaned.** This document states the rules to be implemented in the
cleaning phase. It is written so another analyst could implement them without guessing.

Every rule is grounded in evidence recorded in `docs/profiling/`. Where a rule exists because of a
specific observed defect, the evidence is cited.

**Standing principles**

1. `data/raw/` is never modified. Source errors are corrected in the clean layer and documented; the
   raw file keeps the error.
2. Source values are never rounded. Casting text to decimal is allowed; changing precision is not.
3. A blank is not a zero. Neither is ever silently converted to the other.
4. Aggregates (national, zone, grand total) are never mixed with detail rows without an explicit flag.
5. Every clean row keeps enough provenance (`source_file`, `source_sheet`, `source_row`,
   `source_period_label`) to be traced back to the exact cell it came from.
6. Geography is never invented. A value published at zone level stays at zone level.
7. `acquisition_cutoff_date = 2026-09-13` is the date sources were last checked. It is **not** an end
   date for any dataset. Each family ends where its publisher ended, and those dates differ — see
   [`docs/acquisition/source_coverage_2026-09-13.md`](../acquisition/source_coverage_2026-09-13.md).
   No rule may assume a shared endpoint.
8. Row counts quoted in this document are **regression expectations for the 2026-09-13 snapshot**, not
   design invariants. Validation asserts structural rules first; frozen counts are an additional guard
   so that a changed snapshot fails loudly instead of passing silently.

---

## 0. Cross-cutting rules

### 0.1 Header detection

**RAW PROBLEM** — The header row is not fixed. Profiling found headers on row 1, 2, 3, 4, **15**
(petrol) and **16** (diesel). Later releases put a report title and a paragraph of commentary above
the table; earlier loose workbooks start at row 1.

**WHY IT MATTERS** — Any loader hard-coded to `header=0` reads a title sentence as column names for
one group of months and works correctly for the other. It fails silently: no error, just wrong data.

**CLEANING RULE** — Detect the header rather than assume it.

1. Scan the first 25 rows of the sheet.
2. Score each row: number of non-empty cells, plus the number of cells that are *not* purely numeric.
3. A candidate header row must additionally contain at least one **anchor token** for that dataset:
   - petrol: a cell equal to `State` (case-insensitive, trimmed)
   - diesel / cooking gas: a cell that is a real datetime, or text matching `Average of <month>-<yy>`
   - food: a cell equal to `Item Label` or `Item Labels`
   - transport (state sheet): a cell equal to `State`
   - transport (monthly sheet): a cell equal to `Zone`
   - CPI: a cell equal to `Monthly`, `All Items`, or `State`
4. Choose the highest-scoring row that satisfies the anchor test. Record it as `header_row_used`.
5. If no row satisfies the anchor test, **stop and raise**. Do not fall back to row 1.

**EXPECTED CLEAN OUTPUT** — Each parsed sheet reports the header row it used, stored alongside the
extracted rows.

**VALIDATION CHECK** — For all 219 profiled sheets, the detected header row must equal the
`header_row_estimate` already recorded in `docs/profiling/dataset_structure_summary.csv`. Any
disagreement is investigated before cleaning proceeds, not overridden.

### 0.2 Geography classification

**RAW PROBLEM** — Diesel and cooking gas interleave state rows, zone rows and a national row in one
column. Diesel's geography column has no header at all. Transport prints states in upper case
(`AKWA IBOM`) while petrol uses title case (`Akwa Ibom`). One cooking gas cell reads `Kebbi/Nasarawa`.

**WHY IT MATTERS** — If `NORTH CENTRAL` or `NATIONAL` is treated as a state, every state-level
average double-counts. Nigeria appears to have 38+ states. If casing is not reconciled, the same
state fails to join across datasets.

**CLEANING RULE**

1. Use `data/reference/ref_state_zone.csv` — **the lookup table, one row per unique
   `alias_normalised`.** `alias_normalised` is the alias trimmed, internal whitespace collapsed, and
   casefolded. It is the join key and it is **unique**: 39 rows, 39 keys, covering 37 canonical
   entities. Joining a source observation to it can never return more than one row, so a join can
   never multiply observations.

   Raw spellings are preserved two ways without creating duplicate keys: the `observed_aliases`
   column lists every raw variant behind each key (`ABIA | Abia`), and
   `data/reference/ref_state_alias_observed.csv` holds one row per raw spelling (77 rows) with the
   dataset it was seen in.

   Many keys may share a state — `abuja`, `fct` → `Abuja`; `nasarawa`, `nassarawa` → `Nasarawa` — but
   **no key may resolve to two states.** Loading fails if one does.

   The aliases were **harvested from the raw files**, not authored from memory. That is how
   `Nassarawa` (double-s, used in CPI, diesel and petrol) was found.
2. Preserve the original value in `geography_raw_label` **before** any change.
3. Normalise for matching only: trim, collapse internal whitespace, casefold.
4. Classify explicitly into `geography_type`:
   - exact `alias_normalised` match in `ref_state_zone` → `STATE`
   - match to one of the six zone names, **after zone normalisation** → `ZONE`
   - `AVERAGE`, `NATIONAL`, `Grand Total`, `Nigeria` → `NATIONAL`
   - **anything else → `UNCLASSIFIED`**

   **Zone normalisation.** Zone labels carry their own spelling variants and must be normalised by
   the same trim → collapse-whitespace → casefold rule, then matched against the six controlled
   values with internal spaces removed. One variant is already observed:

   | Observed raw label | Source | Resolves to |
   |---|---|---|
   | `SouthWest` (no space) | `AGO JANUARY 2026.xlsx`, diesel | **South West** |

   `SouthWest` is a **zone**, never a state. It must not enter `ref_state_zone`, and a check asserts
   no zone label — in any spelling — ever appears as a state alias.
5. `UNCLASSIFIED` rows are a hard failure. The run stops and the value is added to the reference
   table deliberately, or excluded deliberately. Silent dropping is not permitted.

**Splitting combined labels is NOT a general rule.** It applies only to the extreme-callout fields
(`food_price_extreme_callout`, `cooking_gas_extreme_callout`), where NBS genuinely uses `Kebbi/Nasarawa`
to record a tie. It is never applied to a main geography column.

The restricted rule, in the callout fields only:

- split the label on `/` only if **every** resulting part resolves to a known state via
  `ref_state_zone`;
- if any part fails to resolve, do **not** split — keep the value whole, mark it `UNCLASSIFIED`
  and stop for review;
- when a split does occur, emit one row per state, each flagged `is_shared_extreme = TRUE`, each
  carrying the same price and the same `raw_callout_text`.

A slash in a main geography column is treated as an unrecognised value and raises. It is not
evidence of a tie there, and silently splitting it could manufacture two states out of one bad cell.

**EXPECTED CLEAN OUTPUT** — Every row carries `geography_raw_label`, `geography_name`,
`geography_type`, and (`state`, `zone`) populated only where genuinely applicable.

**VALIDATION CHECK** — Count of distinct `state` values ≤ 37. Zero rows with
`geography_type = 'UNCLASSIFIED'`. For every dataset that publishes state rows, the set of states in
each month is reported; a month with fewer than 36 is flagged for review, not padded.

### 0.3 Aggregate rows

**RAW PROBLEM** — Every one of the 50 petrol, diesel and cooking gas sheets contains an `AVERAGE` or
`NATIONAL` row inside the state block. Every `State Transport` sheet ends with `Grand Total`.

**WHY IT MATTERS** — `AVG(price)` over an un-flagged table averages the national average together
with the states. The query succeeds and the answer is wrong.

**CLEANING RULE** — Aggregates are **kept, not deleted**, and marked:
`is_aggregate = TRUE` together with `geography_type IN ('ZONE','NATIONAL')`.
All state-level analysis filters on `geography_type = 'STATE'`. The published national figure remains
available as the authoritative national value — which is better than recomputing it, because NBS
weights its national average rather than taking a plain mean of states.

**EXPECTED CLEAN OUTPUT** — One row per aggregate, clearly typed, never deleted.

**VALIDATION CHECK** — The count of `NATIONAL` rows must be checked **at each table's own grain**, not
per dataset-month. Several tables carry extra dimensions, so "one national row per month" would be
wrong for them:

| Table | Expected `NATIONAL` rows |
|---|---|
| `petrol_price_monthly`, `diesel_price_monthly` | exactly 1 per (`release_month`, `observation_month`) |
| `cooking_gas_price_monthly` | exactly 1 per (`release_month`, `observation_month`, `cylinder_size_kg`) — **two per month**, one per cylinder |
| `transport_fare_state_monthly` | exactly 1 per (`observation_month`, `transport_mode`) — **five per month**, one per mode |
| `transport_fare_zone_monthly` | exactly 1 per (`release_month`, `observation_month`, `transport_mode`) |
| `food_price_zone_monthly` | **none** — this table is zone-only; the national series is a separate table |
| `food_price_national_monthly` | every row is national, by design; the check does not apply |

Separately, the published national value is compared with the unweighted mean of that month's state
values at the same grain. They are expected to **differ**, because NBS weights its national average.
A suspiciously exact match is investigated as a possible mis-classification.

### 0.4 Wide to long

**RAW PROBLEM** — Seven of the eight datasets store the period in the column heading, not in a column.

**WHY IT MATTERS** — You cannot filter, group or join on a value that only exists as a header.

**CLEANING RULE** — Unpivot the period columns into rows. The header text becomes
`source_period_label` (kept verbatim) and is parsed into `observation_month`.

Month-label parsing must handle every form observed across the 52 distinct labels in
`column_inventory.csv`:
- Excel datetimes (petrol dated the 1st, diesel dated the **14th**) → truncate to month start
- abbreviated names: `Apr-25`, `Sept-24`
- full names: `April-26`, `December-25`
- lower case: `feb-24`
- two-digit years → 20xx

**EXPECTED CLEAN OUTPUT** — One row per (geography × period × measure), with both the parsed
`observation_month` and the original `source_period_label`.

**VALIDATION CHECK** — Zero unparsed period labels. Every `observation_month` falls within
2024-01-01 … 2026-05-01 (the three-period windows reach a year before the study period). Each
release contributes exactly the periods its headers advertise.

### 0.5 Overlapping periods across releases

**RAW PROBLEM** — **Some, not all,** NBS sheets publish three periods per release: the current month,
the prior month, and the same month a year earlier. Those sheets restate months that earlier releases
already published. Other sheets publish only the release month and never overlap.

The distinction is exact, and it determines the primary keys:

**Sheets with overlapping multi-period releases**

| Clean table | Source sheet | Periods per release |
|---|---|---|
| `food_price_national_monthly` | `Selected Food <month>` | 3 |
| `petrol_price_monthly` | state block, datetime columns | 3 |
| `diesel_price_monthly` | datetime columns | 3 |
| `cooking_gas_price_monthly` | 3 columns per cylinder block | 3 |
| `transport_fare_zone_monthly` | monthly sheet | 3 |
| `cpi_state_index_monthly` | `Table-5` | 3 |
| `cpi_index_monthly` | `Table1`–`Table4` | **the entire historical series**, restated every release |

**Sheets that publish the release month only — no overlap**

| Clean table | Source sheet |
|---|---|
| `food_price_zone_monthly` | `Zone All item` |
| `food_price_extreme_callout` | Highest/Lowest columns |
| `transport_fare_state_monthly` | `State Transport` |
| `cooking_gas_extreme_callout` | extremes blocks |

`fx_nfem_daily` and `electricity_tariff_disco_monthly` are not built from monthly NBS releases and are
outside this rule entirely.

**WHY IT MATTERS** — Naively stacking the overlapping tables produces several rows per month that look
like duplicates and may be silently averaged. For `cpi_index_monthly` the effect is far larger than
three: 21 releases each restate the whole series.

**CLEANING RULE** — Keep every extracted row, tagged with both `release_month` and `observation_month`.

**`release_month` is part of the primary key on every overlapping table.** It is what makes two
publications of the same observation distinguishable. `is_primary_release`
(`observation_month = release_month`) is retained as a **convenience flag only** — useful for
filtering to the first publication of a month, but never part of a key and never relied on to tell two
releases apart. Three releases can restate one month; a boolean cannot separate three things.

**EXPECTED CLEAN OUTPUT** — Full publication history retained, with each row attributable to the exact
release that carried it.

**VALIDATION CHECK** — Where the same `observation_month` is published by two releases, the values are
compared. An exact match is expected and is a genuine cross-check of extraction correctness — this is
how the January 2026 petrol anomaly was proved. A mismatch means NBS revised the figure, and is
reported rather than silently resolved. Exactly one row per key; more than one means the same release
published the same observation twice.

### 0.6 Missing, zero, and not applicable

**RAW PROBLEM** — Three different absences exist and look similar: empty cells, literal zeros, and
values that cannot exist.

**WHY IT MATTERS** — Converting blanks to zero invents data. In FX, `0` deals is a measurement while
blank turnover is an absent one; treating them alike corrupts both.

**CLEANING RULE**

| Source state | Clean representation |
|---|---|
| empty cell | `NULL`, with `value_status = 'MISSING'` |
| literal `0` published | `0`, with `value_status = 'OK'` |
| value cannot exist (e.g. year-ago figure for a newly added item) | `NULL`, `value_status = 'NOT_APPLICABLE'` |
| `#REF!` or other Excel error | `NULL`, `value_status = 'SOURCE_ERROR_REF'` |

**No blank is ever filled.** Not by zero, not by interpolation, not by carrying a value forward.

**EXPECTED CLEAN OUTPUT** — Every measure column is paired with a status, so absence is queryable.

**VALIDATION CHECK** — In food, exactly 15 items per month carry a NULL year-ago average and a NULL
YoY — matching the profiled count. In CBN, exactly **298** in-window rows carry `nfem_deal_count = 0`
with status `OK`, and **300** carry NULL turnover with status `MISSING` (2026-09-13 snapshot; both are
regression expectations, and the rule they guard is that the two absences never convert into each
other).

### 0.7 Numeric casting

**CLEANING RULE** — Cast to `DECIMAL`, never to float, for all money and index values. Strip thousands
separators and stray whitespace. **Never round, truncate or reformat.** A value published as
`1032.1181125000003` is stored at full precision. Percentages stay in the units NBS published them in
(whole percent, not fractions).

**VALIDATION CHECK** — Re-read a random 1% sample of cells directly from the raw workbook and compare
to the clean value at full precision. Any difference is a defect.

### 0.8 Exact-cell provenance

**RAW PROBLEM** — `source_row` plus `source_period_label` does not uniquely identify a source cell.
In `TRANSPORT_COST_Watch_MAR_2025.xlsx`, sheet `Transport March 2025`, **columns 2 and 4 carry the
identical header** `Average of Mar-24`. A clean row citing row 2 and label `Average of Mar-24` could
have come from either cell — and the two hold different years of data.

**WHY IT MATTERS** — Provenance that cannot resolve to one cell is not provenance. The 1% re-read
check in §0.7 and the human validation of anomalies both depend on being able to reopen the exact cell.

**CLEANING RULE** — Every extracted value carries, in addition to `source_file`, `source_member`,
`source_sheet` and `source_row`:

- **`source_column_index`** — 1-based column number in the source sheet.
- **`source_cell_reference`** — A1-style reference, e.g. `D17`, derived from the row and column.

Together these identify exactly one cell in exactly one sheet in exactly one file. Both are recorded
even when the header is unambiguous, so the provenance contract is uniform across all tables.

**EXPECTED CLEAN OUTPUT** — Every row in every spreadsheet-derived table resolves to a single,
identified source cell.

**The direction of the rule matters.** The requirement is that **every clean row points at exactly one
source cell** — not that every source cell produces exactly one clean row. Those are different claims,
and only the first is true.

**One source cell may legitimately expand into several clean rows.** The documented case is a **tied
state callout**: the single cell `Kebbi/Nasarawa (6500)` is one cell in one sheet, and cleaning
deliberately emits one row for Kebbi and one for Nasarawa. Both rows correctly cite the same
`source_cell_reference`, because that is genuinely where both came from. Forbidding this would either
make the tie unrepresentable or force a fake cell reference on the second row.

**VALIDATION CHECK**

1. **Completeness (applies to every spreadsheet-derived table).** `source_cell_reference`,
   `source_column_index` and `source_row` are non-null on every row, and the reference is well-formed
   A1 notation consistent with the recorded row and column.

2. **One-to-one by default.** In every table **except** `food_price_extreme_callout` and
   `cooking_gas_extreme_callout`, `(source_file, source_member, source_sheet, source_cell_reference)`
   is **unique**. Two rows claiming one cell in a price table is a parser bug.

3. **Controlled expansion in the two callout tables.** Rows may share a source cell, but only under
   all of these conditions:
   - every row in the group has `is_shared_extreme = TRUE`;
   - they share an identical `price_ngn` and an identical `raw_callout_text`;
   - their `state` values are **distinct** and each resolves through `ref_state_zone`;
   - the group size equals the number of `/`-separated parts in `raw_callout_text`.

   Any sharing that fails these conditions fails the run. A group of one is the normal case and needs
   `is_shared_extreme = FALSE`.

4. **March 2025 transport.** The two rows labelled `Average of Mar-24` must carry different
   `source_cell_reference` values (`B2` and `D2`) and different `observation_month` values
   (2024-03-01 and 2025-03-01). This is the opposite situation — one label, two cells — and rule 2
   applies to it in full.

---

## 1. Food

**RAW PROBLEM** — The spreadsheets publish national and six-zone figures only. There is **no state
column**. State names appear only inside `Highest` / `Lowest` cells as packed text such as
`Oyo (1941.78)`. Verified across the May 2025, Nov 2025, Jan 2026 and May 2026 report PDFs: every
contents page lists *National* then the six zones, with no state section.

Two files carry a stale worksheet name (`selected_food_table_Apr25.xlsx` and
`selected_food_table_Mar_25.xlsx` both name their sheet `Selected Food Dec 2024`). February 2025
renames the first column to `Item Labels` (plural).

**WHY IT MATTERS** — The project question is about states. Food cannot answer it at state level, and
pretending otherwise would be fabrication. This is a **source limitation, not a cleaning problem**,
and no amount of PDF extraction changes it.

**CLEANING RULE**

1. Produce three tables and no others:
   - `food_price_national_monthly` — item × month, from the three period columns of the monthly sheet
   - `food_price_zone_monthly` — item × zone × month, from `Zone All item`
   - `food_price_extreme_callout` — item × month × HIGHEST/LOWEST, parsed from the packed text
2. Accept `Item Label` and `Item Labels` as the same field.
3. Ignore the worksheet **name** entirely when deriving periods. Derive the period from the column
   headers, which profiling confirmed are correct even in the two stale-named files.
4. Parse callout cells with a strict pattern: text before `(`, number inside `(...)`. Keep the
   original in `raw_callout_text`. Split `/` into multiple rows.
5. **Do not build, infer, interpolate or reconstruct a complete state-level food price table.**

**EXPECTED CLEAN OUTPUT** — National and zone series that are complete, plus a callout table that is
explicitly labelled as extremes, never as state coverage.

**VALIDATION CHECK** — Ties mean an item-month can legitimately produce **more than two rows**, so the
check is on categories and internal consistency, not on a row count:

- `extreme_type` for any (`observation_month`, `item_label`) is a subset of `{HIGHEST, LOWEST}` —
  no third category may ever appear.
- Each item-month has **at most one HIGHEST group and at most one LOWEST group**.
- Within a group, one row is normal. More than one row is permitted **only** when every row in that
  group has `is_shared_extreme = TRUE`, shares an identical `price_ngn`, and shares an identical
  `raw_callout_text` — i.e. they all came from one tied source cell.
- More than one row in a group with differing prices, or with `is_shared_extreme = FALSE`, is a
  parsing fault and fails.
- Every `state` resolves through `ref_state_zone`.

A separate test asserts that no query joins this table as though it were full state coverage. The zone
table has exactly six zones per item-month.

---

## 2. Petrol (PMS)

**RAW PROBLEM** — A petrol sheet holds **four distinct blocks**, and their positions move between
releases:

| Block | Usual position | Contents | Canonical? |
|---|---|---|---|
| State table | col A + three datetime cols B–D | 37 states/FCT, then `AVERAGE`, then `Year on Year` / `Month on Month` | **yes** — `STATE` + `NATIONAL` |
| Zone table | cols F–G, header `Zone` \| `Average Price` | the six zones, **one** price column | **yes** — `ZONE` |
| Extreme callouts | below the zone table, same columns | `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES` + three state rows each | **no** |
| Derived stats | July 2025 only, cols I–J | `MAX` / `MIN` over the zone averages | **no** |

Header row moves between **1, 2, 3 and 15**. Period columns are Excel datetimes dated the 1st.
The state table carries **three** periods; the zone table carries **one** (the release month).

> **January 2026 structural variation — verified 2026-09-14.**
> An earlier version of this rulebook stated that January 2026 *"drops the zone block entirely."*
> **That was wrong.** `PMS_Report_JANUARY_2026.zip` member `PMS_JANUARY_2025.xlsx`, sheet `Sheet1`,
> contains the complete publication:
>
> | Rows | Content |
> |---|---|
> | 2 | `State` header, datetime columns 2025-01, 2025-12, **2026-01** |
> | 3–39 | all **37** states/FCT |
> | 40 | national `AVERAGE` |
> | 41–42 | `Year on Year`, `Month on Month` footnotes |
> | **44** | **a second header, `Zone` \| `Average Price`, in columns A/B** |
> | **45–50** | **all six geopolitical zones** |
> | 54–62 | highest/lowest callout blocks |
>
> The zone table is **below** the state table in columns A/B rather than beside it in F/G. Nothing is
> missing — only the layout differs. These zone rows are valid published data and **must be cleaned**.
> See D-22.

Two verified label errors: the January 2026 release contains a member named `PMS_JANUARY_2025.xlsx`
whose internal title row also reads `JANUARY 2025`, and the October 2025 sheet's title row reads
`AUGUST 2025 REPORT`.

**WHY IT MATTERS** — Reading the two side-by-side tables as one produces rows where a state is paired
with an unrelated zone average. Reading the F/G column pair to its end turns six callout states into
six fake `ZONE` rows per release. Locating the zone table by coordinate loses January 2026 entirely.
Trusting the filename files January 2026 data under January 2025.

**CLEANING RULE**

1. **Locate blocks by content, never by coordinate.** Scan the whole sheet for header cells:
   - a cell equal to `State` (case-insensitive, trimmed) opens a **state block**;
   - a cell equal to `Zone` opens a **zone block**, wherever it sits — F/G beside the state table, or
     A/B beneath it. Both must work without a coordinate rule.
   A sheet may contain more than one block header; process each.
2. **Each block ends where its rows stop resolving to its own type.** Walk downward from the header
   and stop at the first label that does not classify (§0.2) as a member of that block:
   - state block: accept `STATE`; accept the first `NATIONAL` row and stop immediately after it;
   - zone block: accept `ZONE` only, and stop at the first non-zone label.
   This single rule discards the `Year on Year` / `Month on Month` footnotes, the
   `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES` headings and the callout state rows beneath them,
   without naming any of them.
3. **Never join the blocks row-wise.** A state row and a zone row that share a spreadsheet row number
   are unrelated.
4. Derive the period **only** from the datetime column headers. Ignore the filename, the worksheet
   name and the title row. The zone block has a single `Average Price` column and takes the release
   month as its `observation_month`.
5. Record the known label errors in a `source_anomaly` column on affected rows:
   `MEMBER_FILENAME_YEAR_WRONG` (Jan 2026), `TITLE_ROW_MONTH_WRONG` (Oct 2025). These are the only two
   title corrections; there is no general title-repair rule.

**NOT INGESTED — and why**

- **Extreme callouts.** `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES` and the three state rows under
  each are a reporting highlight, not a geography series. The states and prices they show are already
  present in the state block; ingesting them would duplicate observations and, if read as part of the
  zone block, would classify states as zones. Petrol has **no** canonical extreme-callout table, so
  the structure is documented here and left unextracted.
  The February 2025 lowest-price block contains the tied label **`Ekiti/Oyo`**. It stays in the
  callout area and is never resolved: `Ekiti/Oyo` is **not** added to `ref_state_zone`, and the
  slash-splitting rule in §0.2 remains restricted to the food and cooking-gas callout fields. A slash
  in a main petrol geography column still raises.
- **July 2025 `MAX` / `MIN`.** `Fuel_Report_July_2025.xlsx` carries `MAX` (I2/J2) and `MIN` (I5/J5)
  computed across the six zone averages — the only petrol cells beyond column G in any release. They
  are derived statistics over values already published, recomputable from the zone rows, and belong to
  no geography. Excluded from `petrol_price_monthly`; the cells remain untouched in the raw workbook.

**EXPECTED CLEAN OUTPUT** — `petrol_price_monthly`, per release: **37 states × 3 periods + 1 national ×
3 periods + 6 zones × 1 period = 120 rows.** Across the 17 spreadsheet releases 2025-01 … 2026-05 that
is **2,040 rows.** The six petrol PDFs are corroborative only — they cannot supply a spreadsheet cell
reference and so generate no canonical rows.

**VALIDATION CHECK** — All 17 releases processed, 2025-01 … 2026-05 with no gap. Every release yields
all 37 states/FCT and exactly six zones — **including January 2026**, whose zone rows come from A/B.
January 2026 rows carry `observation_month = 2026-01-01`; their prior-month column equals the December
2025 release's current-month values for every comparable state. October 2025 rows carry
`observation_month = 2025-10-01` despite the title row. No callout state, no `Ekiti/Oyo`, no `MAX` or
`MIN` cell and no footnote label reaches the clean table.

---

## 3. Diesel (AGO)

**RAW PROBLEM** — Header row moves between 1, 2, 3 and 16. The geography column has **no header**.
States, the six zones and a `NATIONAL` row are interleaved in that same column. Four sheets are named
`Sheet1`. Period headers are datetimes dated the **14th** of the month.

**WHY IT MATTERS** — Selecting "all rows" yields a mixture of three geographic levels with nothing but
the row label to distinguish them.

**CLEANING RULE**

1. Detect the header (§0.1) using the datetime anchor.
2. Address the geography column **by position** (first column), since it has no name.
3. Apply §0.2 classification to every row. `UNCLASSIFIED` stops the run.
4. Truncate the datetime header to month start — the 14th is a label convention, not an observation date.
5. Ignore the worksheet name entirely; four are `Sheet1`.

**EXPECTED CLEAN OUTPUT** — `diesel_price_monthly` where `geography_type` cleanly separates the three
levels that share one source column.

**VALIDATION CHECK** — Per month: exactly 6 `ZONE` rows, exactly 1 `NATIONAL` row, and the remainder
`STATE`. Any other distribution fails.

---

## 4. Cooking gas (LPG)

**RAW PROBLEM** — Each sheet holds **two side-by-side product tables** (5 kg on the left, 12.5 kg on
the right) whose column headers are **identical text**, distinguished only by a merged banner in row 1.
Beneath the main table sit an `Average` national row and two further stacked blocks,
`STATES WITH THE HIGHEST AVERAGE PRICES` and `STATES WITH THE LOWEST AVERAGE PRICES`. In 2026 releases
the geography column silently moved from position 1 to position 3, `MoM`/`YoY` became `MOM`/`YOY`, and
sheet names drifted to `Sheet1`. One cell reads `Kebbi/Nasarawa`.

**WHY IT MATTERS** — Selecting columns by name cannot distinguish 5 kg from 12.5 kg, because the names
are the same. Selecting by fixed position breaks in 2026.

**CLEANING RULE**

1. Locate the geography column **by content**: the first column whose values match known states or
   zones. Do not assume position 1 or 3.
2. Assign `cylinder_size_kg` by **column block position relative to the banner row**, not by header
   text: the block under `5KG` is 5.0, the block under `12.5KG` is 12.5.
3. Treat header names case-insensitively so `MoM` and `MOM` are the same field.
4. Parse the main table until the `Average` row; capture that as `NATIONAL`.
5. Parse the two extremes blocks into `cooking_gas_extreme_callout`, tagged by the banner above them.
6. Split `Kebbi/Nasarawa` into two rows, both `is_shared_extreme = TRUE`.

### 4a. LPG 12.5 kg block: Kebbi is published as "Taraba" (2025)

**RAW PROBLEM** — In the **12.5 kg block of all twelve 2025 LPG releases**, the North West zone
position that should hold **Kebbi** is labelled **`Taraba`**. Taraba therefore appears **twice** in
that block — once correctly under North East, once in Kebbi's North West slot — and **Kebbi is absent
from the 12.5 kg main table entirely**, surviving only in the "lowest prices" callout.

**Evidence** (read-only inspection, `GAS_PRICE_WATCH_JAN_2025.xlsx`):

| Position | 5 kg block (column 1) | 12.5 kg block (column 9) |
|---|---|---|
| North East, row 16 | Taraba | Taraba |
| North West, row 23 | **Kebbi** | **Taraba** ← defect |

The 5 kg block in the same workbook is correct. Each block still contains exactly 37 state rows, so a
row-count check does not detect this. Confirmed in **12 files**: January through December 2025. The
2026 releases are **not** affected — their North West lists read
`Jigawa, Kaduna, Kano, Katsina, Kebbi, Sokoto, Zamfara`.

**WHY IT MATTERS** — A naive load yields **two Taraba rows and no Kebbi** for 12.5 kg in every month
of 2025. Both Taraba rows carry different prices, so any aggregation silently mixes two states'
values under one name while a whole state disappears.

**CLEANING RULE** — A narrowly-conditioned correction. **All** of the following must hold before a
row is reinterpreted; if any fails, no correction is applied and the run raises:

1. the dataset is cooking gas **and** `cylinder_size_kg = 12.5`;
2. the `release_month` falls in **2025**;
3. the row sits inside the **North West** zone block, in the position **between `Katsina` and
   `Sokoto`**;
4. the label `Taraba` **also** appears in its correct North East position in the same block;
5. `Kebbi` is **absent** from that block's main table.

Only then is the row's canonical geography set to `Kebbi`, with
`source_anomaly = 'LPG_12_5KG_KEBBI_LABELLED_TARABA'`. The published text `Taraba` is preserved
verbatim in `geography_raw_label`, so the correction is visible and reversible.

> **There is no global Taraba→Kebbi rule, and there must never be one.** Taraba is a real state with
> its own legitimate rows in every dataset, including the North East position of this very block. A
> blanket substitution would destroy real Taraba data. The correction is keyed to the exact verified
> fingerprint, not to the label.

**EXPECTED CLEAN OUTPUT** — `cooking_gas_price_monthly` with one row per
(geography × month × cylinder size), plus a separate callout table. For 2025 12.5 kg months, 37
distinct states including both Taraba and Kebbi exactly once each.

**VALIDATION CHECK** — Every month yields both cylinder sizes. The number of geographies is identical
between the two size blocks for a given month. No row has a NULL `cylinder_size_kg`.

**Zone-block completeness check (new, and it is what would have caught this defect).** For every
dataset that publishes states grouped under zone headers — cooking gas and diesel — each zone block
must contain **exactly** its canonical state set from `ref_state_zone`, each state **exactly once**:

| Zone | Expected states |
|---|---|
| North Central | 7 — Abuja, Benue, Kogi, Kwara, Nasarawa, Niger, Plateau |
| North East | 6 — Adamawa, Bauchi, Borno, Gombe, Taraba, Yobe |
| North West | 7 — Jigawa, Kaduna, Kano, Katsina, Kebbi, Sokoto, Zamfara |
| South East | 5 — Abia, Anambra, Ebonyi, Enugu, Imo |
| South South | 6 — Akwa Ibom, Bayelsa, Cross River, Delta, Edo, Rivers |
| South West | 6 — Ekiti, Lagos, Ogun, Ondo, Osun, Oyo |

A missing state, an extra state, or any state appearing twice **within or across blocks** fails the
run. A total of 37 is not sufficient evidence of correctness — this defect keeps the total at 37.

---

## 5. Transport

**RAW PROBLEM** — Two sheets with different grains. `State Transport` is genuinely state × 5 modes,
with a `Grand Total` row, state names in UPPER CASE, and column headers that are full sentences whose
spacing and punctuation vary between months. The monthly sheet is headed `Zone` but is actually **five
blocks**, each a national mode row followed by that mode's six zone rows — so the mode exists only on
the block header and must be carried down.

**A verified source defect:** in `TRANSPORT_COST_Watch_MAR_2025.xlsx`, sheet `Transport March 2025`,
columns 2 and 4 carry the **identical header** `Average of Mar-24`. Column 4 is in fact March 2025:
its value `128432.80177064867` matches the `Average of Mar-25` column of the April 2025 release
exactly, and column 3 (`Average of Feb-25`) matches the February 2025 release's current-month value.

**WHY IT MATTERS** — Without the forward-fill, every zone row loses its mode. Without the March 2025
correction, a whole month of transport data is filed a year early, or the duplicate column name
crashes the load.

**CLEANING RULE**

1. Parse the two sheets as two separate tables with different keys.
2. `State Transport`: unpivot the five fare columns; map each long header to a controlled code
   (`AIR`, `BUS_INTERCITY`, `BUS_INTRACITY`, `OKADA`, `WATER`) via a documented lookup that matches on
   a normalised prefix, tolerating the observed spacing variants; keep the original in
   `transport_mode_raw`. Classify `Grand Total` as `NATIONAL`.
3. Monthly sheet: detect block boundaries — a row whose first cell is *not* a zone name starts a new
   block and supplies the mode. Forward-fill that mode across the six zone rows beneath it. The block
   header row itself is `geography_type = 'NATIONAL'`.
4. **March 2025 override:** where a sheet contains duplicate period headers, resolve by column
   position — the three period columns are always, in order, year-ago, prior month, current month —
   and set `source_anomaly = 'DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION'` on every row from that
   sheet. Keep the wrong label verbatim in `source_period_label`, and rely on
   `source_column_index` / `source_cell_reference` (§0.8) to tell the two identically-labelled columns
   apart. Column B is the year-ago period; column D is the current month.

5. **Geography fields on the `Grand Total` row** follow the standard model exactly:
   `geography_name = 'Nigeria'`, `geography_type = 'NATIONAL'`, `is_aggregate = TRUE`, and
   **`state` and `zone` both NULL**. It is not a state and must never be counted as one.

**EXPECTED CLEAN OUTPUT** — `transport_fare_state_monthly` (state/national × mode × month) and
`transport_fare_zone_monthly` (zone/national × mode × month).

**VALIDATION CHECK** — The monthly sheet yields exactly 5 modes × (1 national + 6 zones) = 35 rows per
period. In `transport_fare_state_monthly`, each month has exactly one `NATIONAL` row **per mode**
(five in total) and 37 `STATE` rows per mode; no `NATIONAL` row has a non-NULL `state` or `zone`.
March 2025's current-month column resolves to `2025-03-01` and its value equals the `Average of Mar-25`
column of the April 2025 release; the two rows sharing the label `Average of Mar-24` carry different
`source_cell_reference` values and different `observation_month` values. No mode is NULL.

---

## 6. CPI

**RAW PROBLEM** — Ten sheets per workbook with headers on rows 2, 3 and 4 and column counts from 12
to 65. Headers are **two stacked rows**: a group row and a measure row, so `Food` and `All Items`
repeat across the sheet meaning a different period each time. The `(2)` / `(3)` sheets are rebasing
working sheets carrying both the 1985 and 2024 bases, plus `Multipling Factor` and
`Rereferencing Average` rows. **69,411 `#REF!` cells** exist, ~92% confined to `Table1 (2)`; the
presentation tables contain zero. `Table-5` is the only state-level table, and carries NBS's printed
warning against inter-state comparison. **March 2026 ships a legacy `.xls`** nested in a subfolder —
unreadable without an `.xls` reader. **January 2025 does not exist.**

**WHY IT MATTERS** — Reading one header row loses either the period or the measure. Reading the
working sheets as data imports tens of thousands of broken cells and two incompatible bases.

**CLEANING RULE**

1. Parse only the presentation sheets by default: `Table1`, `Table2`, `Table3`, `Table4`, `Table-5`.
   Parse `(2)`/`(3)` sheets only into a quarantined table flagged `is_working_sheet = TRUE`.
2. Combine the two header rows: forward-fill the group row across its merged span, then concatenate
   with the measure row. Strip embedded newlines and collapse repeated whitespace.
3. Carry the year label down the month rows (forward-fill) to build `observation_month`.
4. Map Excel errors to `NULL` with `value_status = 'SOURCE_ERROR_REF'`. Never to zero.
5. Record `index_base` from the table title on every row.
6. Install an `.xls` reader (`xlrd`) before cleaning, so March 2026 can be read. If it still cannot be
   read, March 2026 is recorded as **MISSING**, not skipped silently.
7. January 2025 remains MISSING. It is not interpolated from December 2024 and February 2025.
8. Every `cpi_state_index_monthly` row carries
   `comparability_rule = 'LEVEL_NOT_COMPARABLE_ACROSS_STATES'`.

**EXPECTED CLEAN OUTPUT** — `cpi_index_monthly` (national/urban/rural) and `cpi_state_index_monthly`
(state), both long, both carrying base and status.

**VALIDATION CHECK** — Zero `#REF!` values survive as numbers. `Table-5` yields 37 states per period.
`index_base` is non-null on every row. A test asserts every state row carries the comparability flag.
March 2026 either parses or is explicitly MISSING.

---

## 7. CBN exchange rate

**RAW PROBLEM** — Values arrive as JSON **strings**, dates as text `Month-DD-YYYY`. **Six dates appear
twice** (2025-02-03, 2025-02-07, 2025-02-18, 2025-05-12, 2025-05-23, 2025-06-19) — every field
identical apart from CBN's internal `id`. Turnover and interbank deal counts are **absent** in 300 of
425 in-window rows, while `noOfDeals` carries a **literal 0** in 298. 24 weekdays have no observation.

**WHY IT MATTERS** — Duplicate dates break a date primary key. Confusing the blank turnover with the
zero deal count would both invent data and destroy real data in the same step.

**CLEANING RULE**

1. **The raw API JSON is the source of record.** The extracted CSV is a documented derivative and is
   never treated as authoritative; it exists for convenience and audit.
2. Parse `ratedate` with the explicit format `%B-%d-%Y`. Keep the original in `source_date_label`.
3. Cast all numeric fields from string to `DECIMAL`. Never round.
4. **The primary key is `source_id`, CBN's own record identifier — not `observation_date`.**
   This is what allows conflicting same-date records to be stored rather than dropped. Uniqueness of
   the date is enforced as a *rule over a subset*, not as the key:
   **`observation_date` must be unique among rows where `record_status = 'ACTIVE'`.**

5. **Classify every record into `record_status`:**

   | Status | Condition | In the analysis view? |
   |---|---|---|
   | `ACTIVE` | The single record to use for that date | Yes |
   | `EXACT_DUPLICATE` | Shares a date with another record and is identical in **every** field except `id`. Keep the lower `id` as `ACTIVE`; the other becomes `EXACT_DUPLICATE` with `duplicate_of_source_id` pointing at the kept row | No |
   | `DATE_CONFLICT` | Shares a date with another record but **differs in at least one value**. **Every** record in the collision is marked `DATE_CONFLICT`; none is promoted to `ACTIVE` | No — **and validation raises** |

   All six known cases (2025-02-03, 02-07, 02-18, 05-12, 05-23, 06-19) are `EXACT_DUPLICATE`: every
   field matches apart from `id`. No `DATE_CONFLICT` currently exists.

6. **A `DATE_CONFLICT` is never resolved automatically.** Not by taking the lower id, not by taking the
   later one, not by averaging. Both records are retained and the run raises for a human decision. A
   date carrying two different rates is a question about the source, not a de-duplication task.

7. **Blank stays NULL. Literal zero stays 0.** `nfem_deal_count = 0` is a reported count and is
   preserved as zero with status `OK`.

8. **The missing weekdays are not filled.** No interpolation, no carry-forward, no zero. Absence of
   a row means no published observation for that date. The count is snapshot-specific (**24** in the
   2026-09-13 snapshot); validation compares the exact *set* of absent dates, never just the count.

**EXPECTED CLEAN OUTPUT** — `fx_nfem_daily` **physically stores every published record**, keyed on
`source_id`. Nothing is deleted. An analysis view filtered to `record_status = 'ACTIVE'` supplies the
clean one-row-per-trading-day series.

Counts are for the **2026-09-13 acquisition snapshot**, window 2025-01-01 to 2026-09-13. They are
regression expectations for this snapshot, not design invariants.

| Count | Value |
|---|---|
| Physical rows in `fx_nfem_daily` (in-window) | **425** |
| `ACTIVE` | **419** |
| `EXACT_DUPLICATE` | **6** |
| `DATE_CONFLICT` | **0** |
| Active analytical observations | **419** |
| Latest observation | **2026-09-11** |

The six redundant records are **retained and marked**, never removed. "De-duplication" here means
*labelling* the redundant record, not deleting it — the raw API published it, so the clean layer keeps
it and records why it is excluded from analysis.

**VALIDATION CHECK** — Validation is written **structurally first**, so it survives a re-acquisition:

- physical in-window row count **equals** the number of in-window records in the raw API snapshot —
  nothing dropped, nothing invented
- the **set** of in-window raw `source_id` values equals the set of clean `source_id` values, compared
  in both directions, with one physical row per id. Membership in the *whole* snapshot is not enough:
  an out-of-window record must fail
- `ACTIVE` **equals** the number of distinct in-window observation dates
- `EXACT_DUPLICATE` **equals** in-window records − distinct dates
- `DATE_CONFLICT` is **0**, or the run fails and no output is written
- the **exact set** of absent weekdays matches the reference list, in both raw and clean. A matching
  count is not sufficient — dropping one real trading day and inventing one holiday row preserves the
  count
- the raw JSON SHA-256 is identical before processing, after processing, after writing, and against
  the digest recorded at acquisition
- `observation_date` is unique **within `ACTIVE` rows** and deliberately *not* unique across the table
- every `EXACT_DUPLICATE` row has a non-null `duplicate_of_source_id` pointing at an `ACTIVE` row with
  the same `observation_date`
- the five core rate columns are 100% non-null, and no published numeric text is altered

Frozen counts for the 2026-09-13 snapshot are asserted **in addition**, as regression guards: **425**
physical rows, **419** `ACTIVE`, **6** `EXACT_DUPLICATE`, **0** `DATE_CONFLICT`, **298** rows with
`nfem_deal_count = 0`, **300** with NULL turnover, **24** absent weekdays. A changed snapshot fails
loudly for review rather than passing silently.

---

## 8. NERC electricity tariffs — extraction design only

**RAW PROBLEM** — **178 of 217 PDFs are image-only scans** with no text layer, including **all 55 of
the 2026 orders**. Of the 39 text-based files, some are themselves prior OCR output with errors baked
in (`IN THE MAilER OF`, `ORDER/NERC/2025/o03` with a letter *o* for zero, `A- . roved`). Table
extraction quality is uneven: `IE_July_2025_064.pdf` has clean vector tables, `AEDC_February_2025_003.pdf`
has text but no vector table structure. Effective dates are written in prose. Orders are issued per
**DisCo**, whose licence areas do not map one-to-one to states.

**WHY IT MATTERS** — OCR digit errors on a tariff are silent and severe: `225.50` misread as `225.S0`
or `226.50` changes a cost conclusion with no visible sign of failure.

**CLEANING RULE — future workflow, not executed now**

1. **Route by file type.** Detect a text layer first. Use direct text/table extraction for the 39
   text-based orders; OCR only the 134 scans. Record which path was used in `extraction_method`.
2. **Locate the tariff table** by searching for the heading pattern
   `Table 2 … Approved … Tariffs … (₦/kWh)`, expected on page 3 or 4, and record `source_page`.
3. **Extract** `customer_class` (R1, R2, C1, D1, A1, MD1, MD2), `service_band` (A–E) and
   `tariff_ngn_per_kwh`.
4. **OCR safeguards:**
   - retain per-value `ocr_confidence`; anything below a threshold is auto-flagged
   - reject any tariff that fails a numeric sanity range agreed before extraction
   - run two independent OCR passes and compare; disagreement on a digit forces manual review
   - flag values containing characters that are common OCR confusions (`O`/`0`, `S`/`5`, `l`/`1`)
   - compare each DisCo's month-on-month tariff change; an implausible jump is flagged, not accepted
5. **Validation status gate — 100% human validation, no sampling.** Every extracted tariff starts
   `UNVALIDATED`. A value may enter analysis only after a person has compared **that individual value**
   against the original PDF page and set `VALIDATED`. A mismatch sets `REJECTED`.

   **This is deliberately the stricter of the two rules considered.** An earlier draft allowed a
   stratified sample plus 100% of low-confidence values; that is rejected. Sampling is a reasonable
   control when errors are random, but OCR digit errors are neither random nor self-announcing:
   `225.50` read as `226.50` carries high confidence, passes every automated check, and silently
   changes a cost conclusion. A sample that misses it certifies the rest of the batch as sound.

   The automated checks in step 4 are **triage, not substitutes for validation.** They decide what to
   look at first, not what can skip being looked at.

   **Cost, stated honestly:** 217 orders, each with a tariff grid of roughly one row per customer class
   and band. This is a large manual workload and it is the main reason NERC is sequenced last. If that
   workload proves unaffordable, the correct response is to **narrow the scope** — fewer DisCos, or
   fewer months, fully validated — not to lower the bar to sampling. A smaller trustworthy dataset is
   worth more than a complete unverified one.
6. **No state mapping.** `state` is deliberately absent from the NERC schema. Any future DisCo-to-state
   mapping must be a separately authored, separately verified reference table with its own
   documentation — and even then, DisCo areas cross state boundaries, so it can never be exact.

**EXPECTED CLEAN OUTPUT** — `electricity_tariff_disco_monthly` at DisCo × effective month × customer
class × band, with provenance, extraction method, confidence and validation status on every row.

**VALIDATION CHECK** — Every row traceable to a `source_file` and `source_page`. No `VALIDATED` row
without a recorded human check, and **no row enters analysis while `UNVALIDATED`** — the analysis view
filters on `validation_status = 'VALIDATED'`, so an unchecked tariff is invisible to downstream work
rather than quietly included. Coverage reconciles against `docs/acquisition/nerc_myto_coverage.csv`:
217 orders, 12 DisCos, and the 15 known missing DisCo-months stay missing. Aba Power (APLE) has no
order after February 2025 and is absent from every month of the 2026-09-13 extension.

---

## 9. Source anomaly register

Every anomaly below is **corrected in interpretation only**. The raw file keeps the error, and the
clean row records what was done.

| Anomaly | Raw file | Clean-layer handling |
|---|---|---|
| Member filename and title row say 2025 | `PMS_Report_JANUARY_2026.zip` → `PMS_JANUARY_2025.xlsx` | Period taken from datetime headers → 2026-01. `source_anomaly = 'MEMBER_FILENAME_YEAR_WRONG'` |
| Title row says `AUGUST 2025 REPORT` | `PMS Report OCTOBER 2025.zip` | Period from headers → 2025-10. `source_anomaly = 'TITLE_ROW_MONTH_WRONG'` |
| **Zone table moved to columns A/B, below the state table** | `PMS_Report_JANUARY_2026.zip` → `PMS_JANUARY_2025.xlsx` | Blocks located by content, not coordinate (D-22). All six zone rows cleaned normally. `source_anomaly = 'ZONE_BLOCK_BELOW_STATE_BLOCK'` |
| `MAX` / `MIN` cells in columns I/J | `Fuel_Report_July_2025.xlsx` | Derived statistics over the zone averages. Excluded from `petrol_price_monthly` (D-23); raw cells untouched |
| Tied extreme label `Ekiti/Oyo` | `PMS_FEB_2025.xlsx`, lowest-price callout block | Stays in the callout area. Never added to `ref_state_zone`, never split, never a geography value (D-23) |
| Duplicate period header, current month mislabelled | `TRANSPORT_COST_Watch_MAR_2025.xlsx` | Resolve by column position → 2025-03. `source_anomaly = 'DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION'` |
| **Kebbi published as `Taraba` in the 12.5 kg block** | 12 files: all 2025 LPG releases | Corrected to `Kebbi` **only** when all five fingerprint conditions in §4a match. `source_anomaly = 'LPG_12_5KG_KEBBI_LABELLED_TARABA'`; published text kept in `geography_raw_label`. No global Taraba→Kebbi rule. |
| **`SouthWest` zone label with no space** | `AGO JANUARY 2026.xlsx`, diesel | Normalised to the zone `South West`. Never treated as a state. |
| Stale worksheet name `Selected Food Dec 2024` | `selected_food_table_Apr25.xlsx`, `selected_food_table_Mar_25.xlsx` | Sheet name ignored; period from column headers. `source_anomaly = 'STALE_SHEET_NAME'` |
| Column renamed `Item Labels` | `selected_food_table_Feb_25.xlsx` | Accepted as an alias of `Item Label` |
| Legacy `.xls` in a subfolder | `CPI_Report_March_2026.zip` | Requires `xlrd`; if unreadable, recorded MISSING |
| 69,411 `#REF!` cells | 5 CPI workbooks, mostly `Table1 (2)` | `NULL` + `value_status = 'SOURCE_ERROR_REF'`; working sheets quarantined |
| OCR text corruption | 39 text-based NERC PDFs | Flagged, dual-pass compared, human-validated |
| No text layer | 134 NERC PDFs | OCR path with confidence scoring and validation gate |
