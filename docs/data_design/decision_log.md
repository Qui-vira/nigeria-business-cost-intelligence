# Design Decision Log

Major decisions taken during Phase 5 (data dictionary and cleaning-rule design), each with the
evidence behind it. Recorded so the reasoning survives after the details are forgotten, and so any
decision can be challenged against the evidence rather than re-argued from memory.

Nothing in this phase touched `data/raw/`.

---

## D-01 — Food cannot provide complete state-level prices

**Decision.** The food layer publishes national and zone series plus a highest/lowest callout table.
No complete state-level food price dataset will be built, planned, or described as achievable from
this source.

**Evidence.**
- The spreadsheets have no state column. Every food workbook contains exactly two sheets:
  `Zone All item` (item × 6 zones) and `Selected Food <month>` (item × national averages). Verified
  across all 18 food files in `docs/profiling/dataset_structure_summary.csv`.
- State names occur only inside `Highest` / `Lowest` cells as packed text (`Oyo (1941.78)`), giving at
  most two states per item-month.
- The report PDFs were checked directly for May 2025, Nov 2025, Jan 2026 and May 2026. Every contents
  page lists *National* followed by the six zones. **There is no state section.** The only state-dense
  page is the same Highest/Lowest appendix already present in the spreadsheet.
- The methodology page states fieldwork is done by "over 700 NBS Staff in all States" — NBS collects
  state-level prices but does not publish them.

**Correction recorded.** An earlier draft of `structural_variations.md` stated that full state-level
food prices "exist only in the report PDFs." That was an inference, never tested, and it was wrong.
It implied the data was recoverable with more effort. It is not. Both profiling documents were
corrected on 2026-09-13.

**Consequence.** This is a **source limitation, not a cleaning problem**. Food answers the project
question at zone level. Any dashboard element showing food must be labelled ZONE or NATIONAL.

---

## D-02 — Exchange rate remains national

**Decision.** `fx_nfem_daily` carries `geography_type = 'NATIONAL'` and is never apportioned to states.

**Evidence.** The CBN NFEM feed publishes one set of rates per trading day for the whole country.
There is no state dimension in the source — no field, no breakdown, no supplementary table.

**Rejected alternative.** Attaching the national rate to each state to make FX "joinable" at state
level. This would create 37 identical rows per day, which adds no information and actively misleads:
a reader would reasonably infer that the rate varies by state.

**Consequence.** FX joins to other datasets **on date only**. In analysis it is an economy-wide driver
— useful for explaining why costs moved everywhere at once, not for explaining why one state differs
from another.

---

## D-03 — CPI index levels cannot rank states by cost

**Decision.** Every row of `cpi_state_index_monthly` carries
`comparability_rule = 'LEVEL_NOT_COMPARABLE_ACROSS_STATES'`. Ranking states by index level is
prohibited in the design, not merely discouraged in a document.

**Evidence.** NBS prints the restriction directly beneath Table-5:

> *"Indices may not be used for inter-state price comparison because market baskets differ state to state."*

**Why this is true, in two parts.**
1. **Re-basing destroys the level.** Each state's index is set to 100 at its own base period. Two
   states with very different absolute price levels both start at 100, and the difference is gone by
   construction. This alone makes level comparison impossible, regardless of baskets.
2. **Different baskets.** Each state's index weights a different bundle of goods, so even the growth
   rates measure slightly different things.

**What remains valid.**

| Comparison | Verdict |
|---|---|
| One state's index level vs another's | **Invalid** — destroyed by re-basing |
| One state's % change vs another's | **Valid with a caveat** — baskets differ |
| One state now vs the same state a year ago | **Valid** — the intended use |

**Consequence.** The flag is a column, not a footnote, so it travels into SQL, the BI model and the
dashboard. A future analyst who never reads this file still cannot lose the restriction.

---

## D-04 — NERC stays at DisCo level

**Decision.** `electricity_tariff_disco_monthly` has no `state` column. None will be derived in the
cleaning phase.

**Evidence.** NERC issues one MYTO supplementary order per **distribution company**, confirmed across
all 217 acquired orders in `docs/acquisition/nerc_myto_coverage.csv`. DisCo licence areas do not
align with state boundaries — several serve parts of multiple states.

**Rejected alternative.** Assigning each DisCo to its "main" state to force electricity into a state
table. This would silently discard the parts of each licence area that fall in other states, and would
assign one tariff to states served by two DisCos.

**Consequence.** Electricity is reported at DisCo level. If a state view is ever required, it needs a
separately authored, separately verified DisCo-to-state mapping with its own documentation — and even
then it would be an approximation that must be labelled as one.

---

## D-05 — Aggregate rows are typed, not deleted

**Decision.** `AVERAGE`, `NATIONAL` and `Grand Total` rows are kept, marked
`is_aggregate = TRUE` with `geography_type` set accordingly, and excluded from state analysis by filter.

**Evidence.** All 50 petrol, diesel and cooking gas sheets embed a national row inside the state block;
every `State Transport` sheet ends with `Grand Total`. Recorded in `structural_variations.md` §10.

**Rejected alternatives.**
- *Delete them.* Loses the published national figure, which is authoritative and not reproducible by
  averaging states — NBS weights its national average.
- *Leave them untyped.* `AVG(price)` would then average the national figure together with the states.
  The query succeeds and the answer is wrong, with nothing to signal the error.

**Consequence.** Both the detail and the published aggregate remain available, and cannot be confused.
A validation check compares the published national value against the unweighted state mean; they are
expected to **differ**, and an exact match is treated as a suspected mis-classification.

---

## D-06 — Missing is never automatically zero

**Decision.** Four distinct states are represented: `OK`, `MISSING`, `NOT_APPLICABLE`,
`SOURCE_ERROR_REF`. No blank is ever filled — not with zero, not by interpolation, not by carrying a
value forward.

**Evidence.**
- CBN publishes a **literal 0** in `noOfDeals` for 298 in-window rows, while turnover fields are
  **blank** in 300 (2026-09-13 snapshot; 297 and 300 under the earlier 2026-05-31 window). Two
  different absences in the same file, one of which is a real measurement.
- Food has exactly 15 items per month with no year-ago average, and therefore no YoY. These items were
  added to the basket; a year-ago price cannot exist.
- CPI contains 69,411 `#REF!` cells — spreadsheet errors, not values.

**Consequence.** Every measure column is paired with a status column, making absence queryable and its
reason explicit. Filling blanks with zero would simultaneously invent transactions that never happened
and erase the fact that CBN reported genuinely zero deals.

---

## D-07 — Source errors are corrected downstream, never in raw

**Decision.** Verified source-labelling errors are corrected in the clean layer and recorded in a
`source_anomaly` column. The raw file keeps the error.

**Evidence — four verified cases.**

| Anomaly | Proof it is an error |
|---|---|
| `PMS_JANUARY_2025.xlsx` inside the January 2026 release, title row also says 2025 | The datetime header reads `2026-01-01`, and all 33 states' prior-month values match the December 2025 release exactly |
| October 2025 petrol title row reads `AUGUST 2025 REPORT` | The narrative text and all data columns are October 2025 |
| `TRANSPORT_COST_Watch_MAR_2025.xlsx` labels columns 2 and 4 identically as `Average of Mar-24` | Column 4's value `128432.80177064867` appears as `Average of Mar-25` in the April 2025 release; column 3 matches February 2025's current month |
| Two food files name their sheet `Selected Food Dec 2024` | Their column headers read `Average of Apr-25` and `Average of Mar-25` |

**Consequence.** `data/raw/` remains a faithful record of what each agency actually published — which
is the point of a raw layer. The clean layer is correct **and** states what was corrected and why, so
the correction is auditable rather than invisible. The wrong label is preserved verbatim in
`source_period_label` alongside the corrected `observation_month`.

---

## D-08 — Multiple geographic levels are preserved deliberately

**Decision.** Four levels — STATE, ZONE, NATIONAL, DISCO — coexist across thirteen tables. The data is
**not** flattened into a single state-level table.

**Evidence.** The eight sources genuinely publish at different levels:

| Dataset | Published level |
|---|---|
| Petrol, Transport | State |
| Diesel, Cooking gas | State and zone mixed in one column |
| CPI | State in Table-5 only, with a comparability restriction |
| Food | Zone and national only |
| CBN FX | National only |
| NERC | DisCo |

**Rejected alternative.** Building one wide `state × month` fact table with a column per cost driver.
It would require inventing state-level food prices (impossible — D-01), duplicating the national FX
rate 37 times (misleading — D-02), and mapping DisCos onto states (unsupportable — D-04). Three of
eight columns would be fabricated.

**Consequence.** Any dashboard must label the geographic level of each measure. The honest headline is
not "here is the cost of business in Lagos" but "here is what is measured at state level, what is only
available by zone, and what is national." That limitation is the analytical contribution, not a
shortfall — it is what distinguishes an integration of eight real government sources from a single
downloaded CSV.

---

## D-09 — Header rows are detected, never assumed

**Decision.** Every parser detects its header row using content anchors and fails loudly when no
anchor is found. No global `header=0` assumption.

**Evidence.** Header rows were observed at 1, 2, 3, 4, 15 and 16 across the six NBS datasets
(`dataset_structure_summary.csv`). Petrol and diesel move because later releases add a title and a
commentary paragraph above the table.

**Consequence.** A fixed-row assumption would corrupt one group of months while appearing to work on
the other — the most dangerous class of data bug, because it produces plausible numbers and no error.
The detected row is recorded per sheet and reconciled against the profiling output as a regression test.

---

## D-10 — Overlapping release periods are retained, keyed on `release_month`

**Decision.** All extracted rows are kept, tagged with both `release_month` and `observation_month`.
**`release_month` is part of the primary key on every table built from an overlapping release.**
`is_primary_release` (`observation_month = release_month`) survives only as a convenience flag.

**Which tables overlap — stated exactly, because an earlier draft over-generalised.** It is *not* true
that every NBS release publishes three periods.

| Overlapping (three periods per release) | Release month only (no overlap) |
|---|---|
| `food_price_national_monthly` | `food_price_zone_monthly` |
| `petrol_price_monthly` | `food_price_extreme_callout` |
| `diesel_price_monthly` | `transport_fare_state_monthly` |
| `cooking_gas_price_monthly` | `cooking_gas_extreme_callout` |
| `transport_fare_zone_monthly` | |
| `cpi_state_index_monthly` | |
| `cpi_index_monthly` — restates the **whole historical series**, not three periods | |

**Evidence.** Consecutive releases restate the same month — confirmed exactly in the petrol
cross-check, where the January 2026 release's prior-month column matched the December 2025 release's
current-month column for all 33 comparable states. Conversely, `Zone All item` and `State Transport`
carry a single period with no comparison columns at all
(`docs/profiling/dataset_structure_summary.csv`).

**Why `is_primary_release` cannot carry row identity.** A given month can be published by three or
more releases — for `cpi_index_monthly`, by all 21. A boolean separates the first publication from
"everything else"; it cannot distinguish the February restatement from the March one. Using it in a
key would collapse those rows and lose data. `release_month` names the actual release and scales to
any number of restatements.

**Rejected alternative.** Keeping only the current month from each release. Simpler, but discards a
free and powerful correctness check.

**Consequence.** Where two releases publish the same month, the values are compared automatically. A
match confirms the extraction is correct; a mismatch means NBS revised the figure and is reported
rather than silently resolved.

---

## D-11 — The raw CBN API JSON is the source of record

**Decision.** `fx_nfem_daily` is built from the raw API JSON snapshot. The extracted CSV is a
documented derivative, never treated as authoritative.

**Evidence.** CBN publishes no server-side historical download; the page's "Export to Excel" button
builds a file client-side in the browser. The JSON captured from `cbn.gov.ng/api/GetAllNFEM_Rates` is
the closest thing to an official file, holds all 445 records, and was preserved unmodified. The CSV
covers only the 352 rows that were in-window under the original 2026-05-31 cutoff and was produced by
us; it was **not** regenerated when the cutoff moved to 2026-09-13, so it now understates the window
by 73 records. That is another reason it is not authoritative.

**Consequence.** If the two ever disagree, the JSON wins. The CSV remains for convenience and as
evidence of what was extracted at acquisition time.

---

## D-12 — NERC extraction is gated behind 100% human validation

**Decision.** Every extracted tariff starts `UNVALIDATED` and may not be used in analysis until a
person has compared **that individual value** against the original PDF page. **Every value, not a
sample.**

**Contradiction resolved.** An earlier draft stated both "every tariff must be validated" and
"validate a stratified sample plus all low-confidence values." Those cannot both hold. The stricter
rule is adopted, and the sampling language has been removed from the rulebook.

**Why sampling was rejected.** Sampling controls error rates when errors are random and independent.
OCR digit errors are neither. A misread `225.50` as `226.50` is a well-formed number that carries high
OCR confidence, passes range checks, passes month-on-month plausibility, and is indistinguishable from
a real tariff — while silently changing a cost conclusion. Worse, a clean sample actively certifies
the unexamined remainder. The automated checks are **triage** that decides what to inspect first, not
a filter that decides what can skip inspection.

**Cost, acknowledged.** 217 orders each carry a tariff grid across customer classes and service bands.
This is a substantial manual workload and is the main reason NERC is sequenced last. If it proves
unaffordable, the correct response is to **narrow scope** — fewer DisCos or fewer months, fully
validated — rather than to lower the bar. A smaller trustworthy dataset is worth more than a complete
unverified one, particularly in a portfolio project whose value is its defensibility.

**Evidence.**
- 178 of 217 orders are image-only scans requiring OCR, including every 2026 order.
- Of the 39 text-based orders, several are themselves prior OCR output with errors already baked in:
  `IN THE MAilER OF`, `ORDER/NERC/2025/o03` (letter *o* for zero), `A- . roved Allowed Tariffs`.
- Table extraction quality is uneven even among text-based files: `IE_July_2025_064.pdf` has clean
  vector tables; `AEDC_February_2025_003.pdf` has text but no table structure.

**Consequence.** An OCR digit error in a tariff is silent and severe — `225.50` misread as `226.50`
changes a cost conclusion with nothing to signal the failure. Dual-pass OCR comparison, confidence
thresholds, plausibility range checks, month-on-month change checks and a human validation gate are
all specified before any tariff enters analysis.

---

## D-13 — CBN is keyed on `source_id`, not on the date

**Decision.** `fx_nfem_daily` uses CBN's own `source_id` as its primary key. Uniqueness of
`observation_date` is enforced as a rule over a subset — unique **among `record_status = 'ACTIVE'`
rows** — rather than as the key itself.

**Contradiction resolved.** An earlier draft set the primary key to `observation_date` while also
requiring that two records sharing a date but differing in value must both be retained. Those are
mutually exclusive: the key would reject the second record outright.

**Design.** Three statuses: `ACTIVE` (the record to use), `EXACT_DUPLICATE` (identical to another
except `id` — the lower `id` stays `ACTIVE`, the other points at it via `duplicate_of_source_id`), and
`DATE_CONFLICT` (shares a date but differs in value — **all** colliding records are marked, none is
promoted, and validation raises).

**Evidence.** All six known duplicates are exact: every field matches apart from `id`. No
`DATE_CONFLICT` exists today. The design nonetheless has to accommodate one, because the rule that
conflicting records must be investigated rather than discarded is a correctness rule, not a
hypothetical.

**Storage decision — records are marked, not deleted.** All in-window records are physically retained
in `fx_nfem_daily`. For the **2026-09-13 acquisition snapshot** that is **425** records: **419**
`ACTIVE`, **6** `EXACT_DUPLICATE`, **0** `DATE_CONFLICT`. Analytical queries read the `ACTIVE` subset,
giving **419** observations. These counts are regression expectations for this snapshot; the standing
rules are structural — `ACTIVE` equals the number of distinct in-window dates, and `EXACT_DUPLICATE`
equals in-window records minus distinct dates.

**Rejected alternative.** Physically deleting the six redundant records to make the table 419 rows.
Simpler to query, but it breaks the raw-to-clean audit trail: the clean table would no longer
reconcile row-for-row against the raw API snapshot, and the fact that CBN published a given record
twice would survive nowhere. Keeping the record and labelling it costs six rows and preserves the
evidence.

**Consequence.** Every record CBN published is stored and auditable; the analysis view still yields a
clean one-row-per-day series — **419** rows in the 2026-09-13 snapshot. Reconciliation against the raw
snapshot becomes a validation check rather than an impossibility, and it is done by comparing the full
**set** of in-window `source_id` values in both directions, not by comparing counts alone. A future date conflict fails loudly instead of
being silently resolved by whichever record happened to sort first.

---

## D-14 — Provenance resolves to an exact cell

**Decision.** Every spreadsheet-derived row carries `source_column_index` and
`source_cell_reference` (A1-style) in addition to `source_row`.

**Evidence.** `TRANSPORT_COST_Watch_MAR_2025.xlsx` sheet `Transport March 2025` has **two columns with
the identical header** `Average of Mar-24` — column B is genuinely March 2024, column D is March 2025
mislabelled. A clean row citing only `source_row` and `source_period_label` cannot say which cell it
came from, and the two hold different years.

**Consequence.** Provenance that cannot resolve to one cell is not provenance. Both the 1% re-read
check and the human validation of anomalies depend on being able to reopen the exact cell.

**The rule runs one way only.** Every clean row must point at exactly one source cell. The reverse —
that every source cell yields exactly one clean row — is **not** required, because it is not true.
A tied state callout such as `Kebbi/Nasarawa (6500)` is a single cell that cleaning deliberately
expands into one row for Kebbi and one for Nasarawa. Both rows cite that same cell, correctly.

A uniqueness check on `(source_file, source_member, source_sheet, source_cell_reference)` therefore
applies to every table **except** the two extreme-callout tables, where controlled expansion is
expected and is validated instead by tie-group consistency (identical price and raw text, distinct
states, group size matching the number of `/`-separated parts). Outside those two tables, two rows
claiming one cell remains a parser bug.

---

## D-15 — A normalised alias resolves to exactly one state

**Decision.** `ref_state_zone` is keyed on `alias_normalised` (lower-cased, with whitespace,
punctuation and hyphens removed). Loading fails if one normalised alias points at two different states.

**Evidence.** Sources disagree on casing and naming: transport prints `AKWA IBOM`, petrol prints
`Akwa Ibom`, and the capital appears as both `FCT` and `Abuja`.

**The rule in both directions.** Many aliases may map to one state — `FCT` and `Abuja` both resolve to
`Abuja`, which is correct and necessary. But one alias may never map to two states, because that makes
resolution non-deterministic: the same raw label would land in different states depending on row order
or dictionary iteration.

**Consequence.** State resolution is deterministic and testable, and raw files are never edited to
achieve it.

---

## D-16 — Slash-splitting is restricted to extreme callouts

**Decision.** A geography label containing `/` is split into multiple rows **only** in the
extreme-callout fields, and **only** when every resulting part resolves to a known state. Everywhere
else a `/` is an unrecognised value that raises.

**Evidence.** NBS uses `Kebbi/Nasarawa` in the LPG extremes block to record a genuine tie between two
states at the same price. That is a real and meaningful pattern — in that field.

**Why the general rule was wrong.** An earlier draft split *any* geography cell containing `/`. Applied
to a main geography column, that would manufacture two state rows out of a single malformed or
unexpected cell, duplicating its value across both and inflating state counts — a silent fabrication.
Outside the callout fields there is no evidence NBS ever uses `/` to mean a tie.

**Consequence.** The tie pattern is handled where it genuinely occurs, and an unexpected slash
anywhere else surfaces as a question instead of becoming invented data.

---

## D-17 — The LPG 12.5 kg "Taraba" rows are corrected only on an exact fingerprint

**Decision.** In the 12.5 kg block of the 2025 LPG releases, the row in Kebbi's North West position is
reinterpreted as `Kebbi` — but **only** when five conditions all hold simultaneously. There is no
global rule converting `Taraba` to `Kebbi`.

**Evidence.** Read-only inspection of all 20 cooking-gas files found that in **12 files — every 2025
monthly release — the 12.5 kg block prints `Taraba` where `Kebbi` belongs**. Taraba appears twice in
that block (correctly under North East, incorrectly under North West between Katsina and Sokoto), and
Kebbi is absent from the main table, appearing only in the "lowest prices" callout. The 5 kg block in
the same workbooks is correct, and the 2026 releases are unaffected.

**Why this needed a fingerprint rather than a substitution.** Taraba is a real state with legitimate
rows everywhere, including the North East position of this same block. A blanket `Taraba → Kebbi`
replacement would destroy real Taraba data across six datasets. The five conditions — 12.5 kg block,
2025 release, North West position between Katsina and Sokoto, Taraba also present in North East,
Kebbi absent — identify this specific defect and nothing else. If any condition fails, no correction
is applied and the run raises.

**Why a row count would not have caught it.** Each affected block still contains exactly 37 state
rows. Only a per-zone completeness check reveals that North West holds Taraba instead of Kebbi. That
check is now mandated in the rulebook for every zone-grouped dataset.

**Consequence.** Without the rule, every 2025 month of 12.5 kg data would carry two differently-priced
Taraba rows and no Kebbi. With it, the correction is conditional, auditable, and the published text
survives in `geography_raw_label`.

---

## D-18 — The state reference is split into a unique lookup plus a provenance table

**Decision.** `ref_state_zone.csv` holds **exactly one row per unique `alias_normalised`** (39 rows,
39 keys, 37 canonical entities). Raw spellings live in an `observed_aliases` column and in a separate
`ref_state_alias_observed.csv` (77 rows, one per raw spelling).

**Problem this fixes.** The first build emitted one row per *raw* spelling — 77 rows over 39 distinct
keys, because `ABIA` and `Abia` both normalise to `abia`. `alias_normalised` is the join key, so a
lookup on it would have returned **two rows for most states**, silently doubling every joined
observation. A correct-looking reference table would have corrupted every downstream count.

**Proof.** A simulated join of all observed labels against the lookup: **3,823 source observations in,
3,823 rows out**, with a maximum of **1** row returned for any single label.

**Consequence.** Cleaning joins on `alias_normalised` with a guaranteed one-to-one result, while every
raw spelling is still recoverable for audit. The general principle: a lookup table's key must be
unique in the lookup, and provenance with many-to-one cardinality belongs in a separate table.

---

## D-19 — Zone labels are normalised, and never become state aliases

**Decision.** Zone labels pass through the same trim → collapse-whitespace → casefold normalisation as
states, then match the six controlled values with internal spaces removed.

**Evidence.** `AGO JANUARY 2026.xlsx` prints **`SouthWest`** with no space, where every other file
writes `South West`. Harvested from the data, not anticipated.

**Consequence.** `SouthWest` resolves to the zone `South West`. It is explicitly excluded from
`ref_state_zone`, and a validation asserts that no zone label in any spelling ever appears as a state
alias — otherwise a zone aggregate could be counted as a 38th state.

---

## D-20 — The acquisition cutoff is a date sources were checked, not a dataset endpoint

**Decision.** The project records a single `acquisition_cutoff_date = 2026-09-13`, and **separately**
records a latest observation date per dataset family. The two are never conflated. No document may
state or imply a shared end date across datasets.

**Evidence.** Re-checking every official source on 2026-09-13 produced eight different endpoints from
one cutoff: CBN NFEM to 2026-09-11 (daily), NERC to September 2026, CPI to July 2026, petrol, diesel,
transport and food to May 2026, and LPG to April 2026. The spread is real and publisher-driven — NBS
releases CPI around the 15th of the following month but the price watches around the 22nd–29th, so a
mid-September cutoff catches more CPI than price-watch months. Full evidence in
`docs/acquisition/source_coverage_2026-09-13.md`.

**Consequence.** The earlier framing "January 2025 – May 2026" is retired as a project-wide statement;
it was only ever true because the first acquisition happened to stop there. Any cross-dataset analysis
must state the window it actually uses and handle families that end earlier, rather than assuming a
rectangle. Row counts in the design documents are labelled as regression expectations for a named
snapshot, and validation is written structurally so that a re-acquisition fails loudly rather than
silently disagreeing with a hardcoded number.

---

## D-21 — Current NBS releases come from `microdata.nigerianstat.gov.ng`, not the main e-library

**Decision.** NBS acquisition targets the NADA catalogue at `microdata.nigerianstat.gov.ng`. The main
site's e-library at `nigerianstat.gov.ng/elibrary` is not sufficient for current releases and must not
be used to conclude that a release does not exist.

**Evidence.** On 2026-09-13 the e-library listing contained 1,695 entries whose newest item was
*Foreign Trade in Goods Statistics Q3 2024*, published 2024-12-06. It lists **none** of the 2025–2026
files the project already holds, so a "not found" there is meaningless. The same six datasets were
found immediately in the microdata catalogue, which is also the host recorded in
`docs/acquisition/source_inventory.csv` for every NBS file acquired. Catalogue ids:
**154** CPI, **157** PMS (petrol), **158** AGO (diesel), **160** LPG (cooking gas), **161** transport
fare, **162** selected food. Download URLs take the form
`https://microdata.nigerianstat.gov.ng/index.php/catalog/<catalog_id>/download/<resource_id>`, and the
filename comes from the `Content-Disposition` header rather than the URL.

**Consequence.** A dataset is only declared missing after checking the relevant microdata catalogue
page. This is recorded because a search of the wrong host returned a confident false negative for all
six NBS datasets during the 2026-09-13 extension.

---

## D-22 — Petrol tables are located by content, never by coordinate

**Decision.** The petrol cleaner finds each table by scanning the whole sheet for its header token —
`State` for the state block, `Zone` for the zone block — and ends each block at the first row whose
label stops classifying as that block's own geography type. No fixed row, no fixed column, no
per-release special case.

**Evidence.** Across the 17 spreadsheet releases the header row sits on row **1, 2, 3 or 15**, and the
zone table sits in **columns F/G in 16 releases but in columns A/B in January 2026**, beneath the state
table and behind its own second `Zone` header on row 44. A coordinate-based extractor silently returns
zero zone rows for January 2026. A column-pair extractor that reads F/G to the end of the sheet ingests
the six `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES` rows as zones — roughly 96 fabricated `ZONE`
rows across the corpus, each one a state wearing a zone's label.

The terminate-on-type rule removes four different problems with one mechanism: the `Year on Year` and
`Month on Month` footnotes, the two callout headings, the callout state rows, and July 2025's `MAX` /
`MIN` cells all fail to classify and therefore end their block. None of them is named in code.

**Rejected alternative.** Special-casing January 2026 by coordinate. It would work today and break at
the next layout change, and it encodes a fact about one file into logic that is supposed to describe a
dataset.

**Consequence.** `cleaning_rulebook.md` §2 was rewritten. Its previous claim that January 2026
*"drops the zone block entirely"* is retracted: the release is complete — 37 states, a national
`AVERAGE`, and all six zones — and its zone rows are cleaned like any other release's.

---

## D-23 — Petrol extreme callouts and derived statistics are documented, not ingested

**Decision.** Four petrol structures are deliberately excluded from `petrol_price_monthly`:
the `STATES WITH THE HIGHEST AVERAGE PRICES` block, the `STATES WITH THE LOWEST AVERAGE PRICES` block,
the `Year on Year` / `Month on Month` footnotes, and July 2025's `MAX` / `MIN` cells.

**Evidence.**
- The callout blocks restate three states already present in the state block, at the same price. They
  are a reporting highlight, not an additional observation, and petrol has no canonical extreme-callout
  table in `canonical_schemas.md` (unlike food and cooking gas, which do).
- `Fuel_Report_July_2025.xlsx` is the only petrol workbook with any content past column G: `MAX` in
  I2/J2 and `MIN` in I5/J5, computed across the six zone averages. Recomputable from rows the clean
  table already holds.
- The February 2025 lowest-price block carries the tied label **`Ekiti/Oyo`**. It is a callout tie, so
  it never reaches a geography field. `Ekiti/Oyo` is **not** added to `ref_state_zone`, and §0.2's
  slash-splitting rule stays restricted to the food and cooking-gas callout fields. A slash in a main
  petrol geography column still raises.

**Consequence.** Ingesting the callouts would double-count six states per release and, read as part of
the zone block, would classify states as zones. Ingesting `MAX` / `MIN` would create price rows
belonging to no geography. Excluding them costs nothing recoverable: every excluded number is either
already in the table or derivable from it. The structures are described in `cleaning_rulebook.md` §2 so
that a later decision to build a petrol callout table has the evidence it needs, and the raw cells are
left untouched.

---

## D-24 — A published period date is truncated, never corrected

**Decision.** `observation_month` is the published Excel date truncated to month start. The
day-of-month is never validated, never assumed and never rewritten. The published value is kept
verbatim in `source_period_label`.

**Evidence.** An earlier version of `cleaning_rulebook.md` §3 and §0.4 stated that diesel period
headers are "datetimes dated the **14th** of the month". Inspection of all 17 diesel releases on
2026-09-15 found **51 period headers: 50 on day 14, and one on day 25** —
`AGO_REPORT_NOV_2025.zip` member `DIESEL_NOV_2025.xlsx` prints `2025-10-25` for its middle period.

Truncation gives `2025-10-01`, which is the correct month, so the *rule* was sound while the *claim*
was false. That is the whole point: a rule that only reads the month cannot be broken by a wrong day,
whereas a rule that asserted "day must be 14" would have failed on a file whose data is fine.

**Rejected alternative.** Normalising the date to the expected 14th. It would produce the same
`observation_month`, and it would erase the evidence that NBS published something unusual — the next
person would have no way to see it without reopening the workbook.

**Consequence.** `source_period_label` carries `2025-10-25` into the clean table, the row is flagged
`PERIOD_HEADER_DAY_NOT_14`, and validation asserts both that the anomaly maps to `2025-10-01` and that
the original text survives. No other release may acquire the flag.

---

## D-25 — Diesel reads one unnamed column and ignores four parallel areas

**Decision.** `diesel_price_monthly` is built from the **main geography column only** — column A,
which has no header — taking the three datetime columns as prices. The duplicate side zone table, the
`YoY` / `MoM` columns, the highest/lowest callout blocks and July 2025's stray `MAX` / `MIN` cells are
documented and excluded.

**Evidence.**
- The main column is nested: each zone heads a section of its own states, and `NATIONAL` closes the
  table. Verified across all 17 releases — the pattern is identical in every one, there are no blank
  rows inside the block, and **every state sits under the zone `ref_state_zone.csv` assigns it, with
  0 mismatches.** A dataset that did not build the reference table independently reproduces it.
- The side table in columns H/I repeats the six zone current-month values. Compared against the main
  column across all 17 releases: **0 value mismatches.** It is a duplicate, so it is corroboration,
  not input — ingesting it would emit a second row for every zone and collide on the primary key.
- `YoY` and `MoM` are percentages sitting in columns E and F. Filing them as prices would record
  `-6.40` as a naira-per-litre observation. Note they are *columns* here and *footer rows* in petrol,
  which is why a shared "skip the footer" rule would not have caught them.
- `Diesel_Report_July_2025.xlsx` is the only diesel workbook with content past column I: unlabelled
  values at **K1 and L1** equal to that month's South South maximum and South West minimum zone
  averages. The July 2025 *petrol* file carries the same artefact.

**Consequence.** Diesel yields **44 geographies × 3 periods × 17 releases = 2,244 rows**, more per
release than petrol (132 vs 120) because diesel's zone rows carry all three periods while petrol's
zone table carries one. The tied callout labels `Adamawa/Plateau` and `Kogi/Zamfara` never reach a
geography field and are not added to `ref_state_zone` — the same treatment as petrol's `Ekiti/Oyo`
under D-23. `SouthWest` occurs only at H7 of `AGO JANUARY 2026.xlsx`, inside the excluded side table,
so the canonical path never meets it; the §0.2 normalisation remains as a safety rule.

---

## Open items carried into Phase 6

1. **`xlrd` is not installed**, so `CPI_Report_March_2026.zip` (legacy `.xls`) could not be read during
   profiling. It must be installed before cleaning, or March 2026 CPI is recorded MISSING.
2. ~~`ref_state_zone` has not been authored yet.~~ **DONE.** Built at
   `data/reference/ref_state_zone.csv` (39 unique keys, 37 canonical entities) with provenance in
   `data/reference/ref_state_alias_observed.csv` (77 raw spellings). Aliases were harvested from the
   raw files, which is how `Nassarawa` was found. Not yet committed.
3. ~~The transport mode lookup has not been authored yet.~~ **DONE.** Built at
   `data/reference/ref_transport_mode.csv` — 6 observed raw labels mapping to the 5 canonical modes,
   validated as unambiguous. NBS truncates these headers at exactly 50 characters, which is why
   `WATER` has two variants (`...transportat` and `...transportation`). Not yet committed.
4. **OCR engine not yet chosen**, and the numeric plausibility range for tariffs not yet agreed. Both
   are needed before NERC extraction begins.
5. **No decision yet on whether the project repository will be made public**, which affects whether
   raw source files are ever redistributed.
6. **Eleven NBS releases were due before the 2026-09-13 cutoff but are not published** — LPG May,
   June and July 2026, plus petrol, diesel, food and transport for June and July 2026. They are
   recorded as *due but unpublished* in `docs/acquisition/source_coverage_2026-09-13.md`. They must be
   re-checked before analysis, and never filled.
7. **The 44 new NERC orders (June–September 2026) are image-only scans**, like the existing corpus, so
   D-12 applies to them unchanged.
8. **Petrol has no canonical extreme-callout table.** The highest/lowest blocks are documented in
   `cleaning_rulebook.md` §2 but not extracted (D-23). If state-level extremes are wanted later, a
   `petrol_price_extreme_callout` table would need designing, including a rule for the tied
   `Ekiti/Oyo` label.
9. **Diesel has no canonical extreme-callout table either.** Its highest/lowest blocks are documented
   in `cleaning_rulebook.md` §3 but not extracted (D-25), and they carry two tied labels
   (`Adamawa/Plateau`, `Kogi/Zamfara`). Any future callout table must cover petrol and diesel together.
10. **The July 2025 stray `MAX` / `MIN` artefact appears in both the petrol and the diesel release.**
   Worth a glance at the other July 2025 NBS products before they are cleaned.
