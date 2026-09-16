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

**Decision.** `electricity_tariff_disco_period` has no `state` column. None will be derived in the
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
- *Delete them.* Loses the published national figure, which is authoritative and is what NBS
  actually published — including any revision, rounding or defect it carries.
- *Leave them untyped.* `AVG(price)` would then average the national figure together with the states.
  The query succeeds and the answer is wrong, with nothing to signal the error.

**Consequence.** Both the detail and the published aggregate remain available, and cannot be confused.
A validation check compares the published national value against the aggregate of the geographies
beneath it, using the relationship **established for that dataset** — see D-37. For petrol, diesel,
transport and food that relationship is an unweighted mean of the 37 states, and an exact match is the
expected result, not a suspicion.

---

## D-06 — Missing is never automatically zero

**Decision.** Five distinct states are represented: `OK`, `MISSING`, `NOT_REPORTED`,
`NOT_APPLICABLE`, `SOURCE_ERROR_REF`. No blank is ever filled — not with zero, not by interpolation,
not by carrying a value forward. `NOT_APPLICABLE` asserts that a value could not exist and needs an
official source saying so; where the reason for a blank is unknown the status is `NOT_REPORTED`
(D-34).

**Evidence.**
- CBN publishes a **literal 0** in `noOfDeals` for 298 in-window rows, while turnover fields are
  **blank** in 300 (2026-09-13 snapshot; 297 and 300 under the earlier 2026-05-31 window). Two
  different absences in the same file, one of which is a real measurement.
- Food has 15 items with no year-ago average, and therefore no YoY, in each of the 12 releases
  2025-01 … 2025-12 — and none in any 2026 release, because the items entered the basket in January
  2025. The count is **per release, not per month**. Their status is `NOT_REPORTED`, not
  `NOT_APPLICABLE`: the basket explanation is inferred, not stated by NBS (D-34).
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

**Evidence.** *(counts corrected during the dataset #7 build - see D-38)*
- Measured across every page carrying a tariff heading: **11** orders have a complete tariff table in
  the text layer, **27** are partial, **1** is heading-only and **178** have no tariff text at all.
  89 files carry *some* text layer, but a text layer is not a tariff table.
- Several text layers are themselves prior OCR output with errors already baked in:
  `IN THE MAilER OF`, `ORDER/NERC/2025/o03` (letter *o* for zero), `A- . roved Allowed Tariffs`.
- Quality is uneven even within one file: `AEDC_AUG_2025_MYTO.pdf` has 33 KB of text, an image-only
  tariff page, and fully text feeder appendices.

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
  slash-splitting rule stays restricted to the callout fields. A slash in a main petrol geography
  column still raises.
  *(Update, Food: that scope narrowed again. All 1,428 food callout cells name exactly one state, so
  no splitting rule is implemented for food and §0.2 now covers `cooking_gas_extreme_callout` alone —
  D-35. The conclusion for petrol is unchanged.)*

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

## D-26 — LPG cylinder blocks are identified by order, never by banner

**Decision.** The two cooking-gas product tables are located by finding the columns that hold runs of
recognisable geography, then assigned by **left-to-right order**: the left block is 5 kg, the right is
12.5 kg. The row-1 banner is kept as published text and is never used to locate or size a block. If a
release ever yields other than exactly two geography blocks, the run stops.

**Evidence.** Across the 16 releases the banner is unreliable in three separate ways:

- its column drifts **0, +1 or +2** away from the block's geography column, so "the block under the
  banner" is not a well-defined column range;
- **January 2026's right-hand banner reads `12KG`, not `12.5KG`** — a cleaner matching the literal
  text would fail to identify the block, or would invent a third cylinder product;
- the geography columns themselves move from **1/9 to 3/11 beginning in February 2026** (not January,
  as an earlier version of the rulebook stated), so fixed positions fail too.

Order, by contrast, held in **all 16 verified releases**: the leftmost geography block is 5 kg every
time. It is also the property the source is least likely to change silently, because swapping the two
products would be visible to any reader of the published report.

**Rejected alternative.** Parsing the banner text for a number. It works for `5KG` and `12.5KG`, and
turns `12KG` into a fourth product that does not exist. The published banner is retained as
provenance so the `12KG` oddity stays visible.

**Consequence.** `cylinder_size_kg` is 5.0 or 12.5 and never NULL. The verified structure is uniform:
44 geographies × 3 periods × 2 sizes × 16 releases = **4,224** main rows, plus **193** callout rows.

---

## D-27 — `Average` and `Grand Total` are both the national row

**Decision.** Both labels resolve to `geography_type = NATIONAL`, `geography_name = Nigeria`. The main
table ends at the first row that *classifies* as national, not at a row matching a particular word.

**Evidence.** The national row is labelled `Average` in the 13 releases 2025-01 … 2026-01 and
**`Grand Total`** in 2026-02, 2026-03 and 2026-04. An earlier version of the rulebook said to "parse
the main table until the `Average` row"; in those three releases there is no such row, so the parse
would run past the national aggregate and into the callout blocks — pulling callout states into the
price table as if they were extra observations.

Both labels were already in §0.2's `NATIONAL` set, so content-based classification handled this
correctly the whole time. The defect was in the *instruction*, not in the classifier.

**Consequence.** This is the third dataset where a rule written around a literal string was falsified
by a later release (petrol's zone block, diesel's period day, now LPG's national label). The pattern
is consistent enough to state as a habit: **terminate a block on what a row *is*, never on what it
says.**

---

## D-28 — Transport's release month comes from the sheet name, cross-checked, never from the current-month header

**Decision.** `release_month` is parsed from the zone sheet's name (`Transport March 2025`) and
cross-checked against column 3's label plus one month. If the two disagree, the run stops. The
current-month header (column 4) is never used to derive the release month.

**Evidence.** Across the 17 releases the sheet name is correct **17/17** and column 3 + 1 month is
correct **17/17**, and the two agree with each other everywhere. Column 4's label is correct only
**16/17**: `TRANSPORT_COST_Watch_MAR_2025.xlsx` prints `Average of Mar-24` in both column 2 **and**
column 4. Taking the maximum parsed header there yields 2025-02 — a whole release filed under the
wrong month, silently.

That column 4 really is March 2025 was verified numerically, not assumed: its 35 values match the
April 2025 release's `Average of Mar-25` column **35/35**, while column 2 matches it **0/35** and sits
at the same magnitude as April's `Average of Apr-24`. Column 3 matches the February release's own
month **35/35**.

**Rejected alternative.** Trusting the sheet name alone. It is right in all 17 here, but three
datasets in this project have already had a name or title falsified by a later release — petrol's
member filename, petrol's title row, diesel's period day. A second independent signal costs nothing
and converts a trusted string into a checked one.

**Consequence.** This is the fourth dataset where a rule written around a literal label was falsified
by the source. The habit now generalises across the project: **derive a period from position and
structure, corroborate it with a second signal, and keep the published text as provenance.**

---

## D-29 — The two Transport sheets are reconciled against each other as a hard check

**Decision.** For every release and transport mode, the zone sheet's `NATIONAL` current-month fare
must equal the `State Transport` `Grand Total` within a relative tolerance of **1e-12**. A breach
fails the run.

**Evidence.** The two sheets are parsed by entirely separate code paths — one walks nested mode blocks
down a single column, the other unpivots five mode columns across state rows — yet they publish the
same national figure. Across all 85 comparisons (5 modes × 17 releases): **45 byte-identical, 40
precision-only, 0 substantive**, with a largest relative difference of **6.6e-16**, one or two units
in the last place of a double.

**Rejected alternative.** Exact equality. It would fail on 40 of 85 comparisons for differences of a
few parts in 10^16 — a rendering artefact of double precision, not disagreement. Rejecting the check
entirely would be worse: it is the only place in this project where two independently parsed tables
assert the same number, and it would catch a mode mis-mapping, a block-boundary error or a column
mix-up in either sheet.

**Consequence.** A structural error in either parser is caught by the other. The tolerance is the same
1e-12 already used for diesel and LPG, so "substantive" means the same thing across the project.

---

## D-30 — Food's period comes from three agreeing header signals; the worksheet name is evidence only

**Decision.** For every food release the observation months are derived from the three period headers,
by column position, and the release month must be confirmed by **all three independently**: the
current-month header, the prior-month header plus one month, and the year-ago header plus twelve. The
file name is required to agree as a fourth. Any disagreement stops the run. The worksheet **name** is
recorded and drives nothing.

**Evidence.** Two of 17 releases carry a stale worksheet name: `selected_food_table_Mar_25.xlsx` and
`selected_food_table_Apr25.xlsx` both name their main sheet `Selected Food Dec 2024`, four and five
months adrift. The three header signals agree in all 17 releases, and the file name agrees in all 17.

**Rejected alternative.** Transport's rule (D-28) — sheet name cross-checked against the prior-month
header. It is the right rule for Transport, where the *header* is the unreliable signal in one
release. In Food the reverse is true: the headers are sound and the sheet name is not. The general
principle from D-28 still holds and is what produced this rule: derive from structure, corroborate
with a second signal, keep the published text as provenance.

**Consequence.** Food is the fourth dataset in which a rule written around a literal string in the
file would have been falsified by a later release.

---

## D-31 — Food's zone sheet is proved to publish the release month, arithmetically

**Decision.** The `Zone All item` sheet is assigned the release month, and this is asserted as a hard
check rather than assumed:

```
national  =  sum(zone_average x states_in_zone) / 37
weights: North Central 7, North East 6, North West 7, South East 5, South South 6, South West 6
```

must hold within a relative tolerance of **1e-9** for **713 of 714** item-releases.

**Evidence.** The zone sheet carries no period label of any kind — no month in its name, no header, no
cell. Run against the main sheet's current-month column the identity matches **713 of 714**
item-releases; run against the prior-month column it matches **0 of 714**. The relationship is not a
coincidence of this corpus: NBS states it on the methodology page of every report — *"The average of
all these prices is reported for each state and the total average for the states is the average for
the country."* It is corroborated a third way by the four cross-release revisions, whose deltas are
exact multiples of 1/37 (+₦4,860, −₦990, −₦10, −₦10 in a single state).

**Rejected alternative.** Assuming the zone sheet describes the release month because it ships in the
release. That is probably true, but it is an assumption, and this dataset has already shown that the
obvious label can be wrong (D-30). The arithmetic turns the assumption into a test that would fail if
NBS ever shipped a stale zone sheet.

**Consequence.** Food gains the cross-table hard check that Transport has (D-29), through a different
mechanism. It also corrected a general rule: see D-37.

---

## D-32 — The March 2025 crate-of-eggs national average is preserved, not recalculated

**Decision.** `selected_food_table_Mar_25.xlsx` sheet `Selected Food Dec 2024` cell **D3 =
7670.559190085271** is written out byte-exact and flagged `NATIONAL_ABOVE_ALL_ZONES`. It is the single
documented exception to the D-31 identity. Every row that carries the value — three of them — is
flagged.

**Evidence.** Every zone average on that row is lower (5808.93 – 6985.22); the identity implies
6211.10, so the published figure is 19.03 % above it. An average over states cannot exceed every
regional average of those same states. The series around it reads 5878.14 → 5976.12 → **7670.56** →
6150.18: a one-month spike and revert. NBS never corrected it — the value is restated identically in
`selected_food_table_Apr25.xlsx` C3 and `selected food table Mar26.xlsx` B3, and both the March MoM
(+28.35 %) and the April MoM (−19.82 %) consume it.

**Rejected alternative.** Substituting the implied 6211.10, or nulling the cell. Either would publish a
number NBS never published and would break the audit trail from the clean row back to the cell. The
defect is in the source; the clean layer's job is to make it visible, not to hide or to fix it.

**Consequence.** Any analysis of egg prices must decide for itself what to do with March 2025. The flag
makes that decision possible instead of invisible.

---

## D-33 — The four July 2025 zone/callout conflicts are published unresolved

**Decision.** In `selected_food_table_July-25.xlsx`, four items have a zone average above the published
state maximum. Both the zone value and the callout are written out unchanged; every offending zone
cell is flagged `ZONE_ABOVE_STATE_MAXIMUM`. The exception set is counted at item-release grain — 710 of
714 pass — and flagged at zone-cell grain, where those four items put **six** zone averages outside the
bracket.

| Item | Zone(s) outside | `Lowest` | `Highest` |
|---|---|---|---|
| Agric hen eggs, crate | South East | Gombe (4900) | Ogun (6816.2) |
| Cray fish small white | South West | Bayelsa (7444.27) | Ekiti (11847.17) |
| Three Crown Milk 160g | South East, South South, South West | Jigawa (799.99) | Rivers (939.26) |
| Yam Tuber | South South | Bauchi (1650) | Rivers (3073.95) |

**Evidence.** These are the only four such item-releases in 714. In three of the four, the offending
zone contains the very state named as the national maximum, so the zone average exceeds its own member
state's price. The D-31 identity holds 42/42 in that release, so the zone and national columns agree
with each other; each offending zone value is also a one-month spike that reverts in August. Against
that, July 2025 has **43 of 84 callout strings byte-identical to June's**, by far the highest of the 16
consecutive pairs (the others run 1–21) — though the offending cells are mostly not among them, so the
carry-over is a separate observation, not the explanation.

**Rejected alternative.** Deciding that the callouts are wrong because the identity holds. The identity
would hold even if both the national and the zone figures came from the same faulty pivot, so it cannot
adjudicate between them. **We do not know which published component is wrong, and the clean layer does
not pretend to.**

**Consequence.** A fifth item-release, or a seventh zone cell, fails the run and forces inspection.

---

## D-34 — An unexplained blank is `NOT_REPORTED`, never `NOT_APPLICABLE`

**Decision.** Food's 195 blank national prices carry `value_status = 'NOT_REPORTED'`. `NOT_APPLICABLE`
is reserved for blanks an official source explicitly explains, and is not used in this dataset.

**Evidence.** Exactly 15 items carry a blank year-ago average in each of the 12 releases 2025-01 …
2025-12, and the same 15 carry a blank prior-month average in 2025-01 only — 180 + 15 = 195. From
2026-01 the year-ago column is complete for all 42 items. The pattern is entirely consistent with those
15 items entering the basket in January 2025, and the October 2025 report does mention a rebased
basket — but no NBS source states that these particular cells could not exist.

**Rejected alternative.** `NOT_APPLICABLE`, inferred from the regularity of the pattern. That labels the
world, not the sheet: it asserts the value *could not* exist, which is a stronger claim than the
evidence supports. A very regular pattern is still a pattern, not a statement.

**Consequence.** This corrected an approved validation check that read *"exactly 15 items per month
carry a NULL year-ago average"*. Written that way it fails on all five 2026 releases. Absence counts
are now asserted **per release**, never per month.

---

## D-35 — Food callout ties are not implemented, because Food has none

**Decision.** `food_price_extreme_callout` parses only the verified `State (number)` structure. A slash,
a comma before the bracket, or any second state is a **hard failure that stops the run**. It is never
split. `is_shared_extreme` stays in the schema for consistency with `cooking_gas_extreme_callout` and
is `FALSE` on every food row, asserted by a check.

**Evidence.** All **1,428** food callout cells match `State (number)` exactly. Zero contain a slash;
zero name more than one state; zero are blank or malformed. The tie machinery the approved design
carried over from LPG has nothing to act on.

**Rejected alternative.** Implementing splitting anyway, for symmetry with LPG. Untested code between
the source and the output is a liability, and a future slash would be silently interpreted by logic no
release has ever exercised. Failing loudly puts a human in front of the first one.

**Consequence.** The §0.2 slash-splitting rule is now scoped to `cooking_gas_extreme_callout` alone.

---

## D-36 — Food items resolve through a reference table, and units are never inferred

**Decision.** `data/reference/ref_food_item.csv` assigns each of the 42 items a stable `item_code`, a
canonical `item_label` taken from the main sheet, its observed raw aliases, and a `unit` /
`unit_source` / `unit_evidence` triple. A label that does not resolve stops the run. `item_label_raw`
preserves whatever each sheet printed.

**A unit is recorded only when the spreadsheet label states it, or an official NBS report PDF states it
for that exact item.** Where neither does, `unit` is NULL. 23 of 42 items have a unit — 11 from the
label, 12 from a report PDF; **19 are NULL**.

**Evidence.** Two raw variants need reconciling: `Agric hen eggs` without its comma in the January 2025
main sheet, and `Smoked fish` on the zone sheet against `Smoked fish (Mackerel)` on the main sheet in
all 17 releases. For units, each PDF claim was tied to its item by matching the naira figure the
sentence quotes against that release's published cell — for example *"Ginger Fresh (1kg) stood at
₦5,906.82"* against D18 of the May 2026 workbook.

That anchoring is not ceremony. The January 2025 report says *"the average price of 1kg of small white
crayfish was ₦6,202.36"*, but ₦6,202.36 is the published figure for **Goat Meat Bone in**; crayfish that
month is ₦6,227.04. The sentence is wrong, so it was discarded for both items, and crayfish took its
unit from two other releases instead. Goat meat has no unit anywhere and is left NULL.

**Rejected alternative.** Filling the 19 gaps with "1 kg" because most loose commodities are priced that
way and the surrounding prices look consistent with it. That is exactly the inference the rule forbids —
plausible, unsourced, and indistinguishable in the output from a sourced fact.

**Consequence.** A consumer of this data can tell which units are documented and which are simply
unknown, which is not true of a table where every row is confidently filled.

---

## D-37 — Aggregation relationships are established per dataset, never assumed globally

**Decision.** `cleaning_rulebook.md` §0.3 no longer says that a published national figure is expected to
differ from an unweighted mean of states, nor that an exact match is suspicious. The rule is now: the
relationship is **established from the dataset's own structure and official methodology, then validated
dataset by dataset**. Where established it becomes a hard check with a documented tolerance and
exception set; where not established, nothing is asserted.

**Evidence.** The old rule was falsified by this project's own committed data. Testing every state-level
table built so far:

| Table | National vs unweighted mean of the 37 states |
|---|---|
| `petrol_price_monthly` | 51 / 51 exact |
| `diesel_price_monthly` | 51 / 51 exact |
| `transport_fare_state_monthly` | 85 / 85 exact |
| `food_price_national_monthly` | 713 / 714 within 1e-9, via the zone weights (D-31) |

NBS says so in its own methodology: *"the total average for the states is the average for the country."*

**Rejected alternative.** Leaving the rule and treating Food as a special case. The rule was stated
generally, so it would have kept misfiring — it turns the single strongest check available in four
datasets into a reason for suspicion.

**Consequence.** No already-processed petrol, diesel or transport output changes: the rule text was
wrong, the data was not. Discovered during Food inspection and corrected before the Food cleaner was
written.

---

## D-38 — NERC extraction routes per page, never per file

**Decision.** The tariff table is located by caption and the *page* carrying it is then tested for
extractable text. A file-level character count, text-layer flag or producer string never decides
whether an order can be processed.

**Evidence.** `AEDC_AUG_2025_MYTO.pdf` carries 33 KB of text and would pass any file-level test — but
pages 1–8, including Table 2, are image-only and leak nothing but stray `₦` glyphs, while pages 9–25
(feeder appendices) are full text. The reverse also occurs: 33 of the 2026 orders carry a one-page
text layer, and that page is always the effective-date page, never the tariff table.

**Rejected alternative.** The earlier approved rule, *"Route by file type. Detect a text layer first.
Use direct extraction for the 39 text-based orders; OCR only the 134 scans."* Both counts were wrong
and the unit of routing was wrong. 89 files carry some text; only 11 carry a usable tariff table.

**Consequence.** The measured corpus classification is 11 complete / 27 partial / 1 heading-only /
178 no tariff text, and the cleaner re-measures it on every run so processed coverage cannot be
quietly overstated.

---

## D-39 — The effective date comes only from the commencement clause

**Decision.** `order_effective_date` is read from the `COMMENCEMENT AND TERMINATION` clause and
nowhere else. The filename month, `nerc_myto_coverage.csv`'s `effective_date`, the website
publication date and any other `effective from` in the document are all rejected as sources. If the
clause cannot be resolved, the order fails.

**Evidence.** `effective from` occurs three or more times in a typical order, meaning different
things: `AEDC_July_2025_059.pdf` says *"MYTO–2024 effective from 1st January 2024"* (the base order),
*"effective May 2025"* (a transmission-fund provision), then *"effective 1st July 2025"*. A
first-match regex takes 2024. Separately, `nerc_myto_coverage.csv` sets `effective_date = month` on
all 232 rows — that column is the acquisition step's inference from the filename, not a value read
from any PDF, and it is not evidence.

Three dates exist and none equals another: the 11 processed orders take effect **2025-07-01**, and
NERC published them on its website on **2025-08-28**, two months later.

**Rejected alternative.** Using the coverage CSV's `effective_date`, which is already computed and
agrees with the filename. It agrees because both come from the same guess.

**Consequence.** `order_effective_date`, `order_signed_date` and `website_publication_date` are three
separate columns and are never conflated. A check asserts the first two differ from the third.

---

## D-40 — A partial tariff table fails the order; it is never published as partial records

**Decision.** An order is processed only if its Table 2 matches the DisCo's expected class structure
exactly: every class present, no unexpected class, every class carrying exactly three values, no
blanked cell. Anything less fails that order. Five orders previously believed complete are rejected
by name.

**Evidence.** The five were classified complete by counting regex row-hits (≥13). Checked properly:

| Order | Defect |
|---|---|
| `AEDC_February_2025_003.pdf` | `Life-line` has no values; `B - MD2` has 2 of 3 |
| `IE_February-2025_008.pdf` | `Life-line` blanked to underscores; `C - MD1` has 2 of 3 |
| `AEDC-MYTO-APR-2025.pdf` | `A - MD1`, `B - MD1` labels absent and merged; `Life-line` 2 of 3 |
| `EEDC-MYTO-APR-2025.pdf` | `E - MD1` label absent and merged |
| `IE-MYTO-APR-2025.pdf` | `E - MD1` absent and merged; `A - MD1`, `A - MD2 Special` 2 of 3 |

The April failures are the decisive ones. **Where a class label is lost its values are not** — they
merge into the row above. `AEDC-MYTO-APR-2025.pdf` p4 prints
`A - Non-MD 225.00 206.80 209.50 225.00 206.80 209.50`: its own triple followed by `A - MD1`'s. An
extractor taking the first three numbers after each label emits a complete-looking 15-row table with
two classes silently deleted and nothing to notice.

**Rejected alternatives.** *Emit the surviving classes, flagged.* The merged rows mean surviving
values may belong to a different class than the label above them; a flag does not fix a wrong
attribution. *Hand-transcribe the five.* Defensible — every row is human-validated anyway — but it
was not authorised, and mixing transcription into an automated build makes the provenance of
individual values harder to audit, not easier.

**Consequence.** The processed dataset covers 11 of 217 orders and says so in its own header. It is
*"a validated July 2025 cross-section of complete text-extractable NERC MYTO tariff tables"* and is
never described as a 2025–2026 tariff history.

---

## D-41 — The excluded tables are excluded by proof, not by assumption

**Decision.** The cleaner locates the Table 1 and Table 3 captions, asserts both sit on pages other
than the tariff page, and records the Table 2 caption verbatim on every output row.

**Evidence.** Table 1 (`Key Tariff Review Indices`) publishes `Weighted Average Cost Reflective
Tariff` and `Weighted Average Allowed Tariff` **in ₦/kWh** — the same unit as a real tariff, on a
neighbouring page, in a table whose caption also contains the word "Tariff". IE's July order gives
114.7 ₦/kWh there, a plausible-looking number that belongs to no customer class. Table 3 is
₦'Million. Being a number in the right unit is not evidence of being a tariff.

**Rejected alternative.** Excluding by page number. The tariff table sits on page 3 in the February
and April orders and page 4 in the July orders, so a fixed page would be wrong a third of the time
even inside the small set examined.

**Consequence.** Fault injection confirms that a Table 1 weighted average or a Table 3 remittance
figure inserted into the output is caught, and that an order whose tariff page also carries an
excluded caption is refused rather than guessed at.

---

## D-42 — All three published period columns are kept, and none is a monthly tariff change

**Decision.** Table 2's three columns (`Apr 2024`, `May – Jun 2024`, `Jul 2024 – Jul 2025`) are all
extracted, each with a parsed `period_start`/`period_end`, the published header preserved in
`period_label_raw`, and `is_current_period` marking the column whose end month equals the order's
effective month. Repeated historical columns are never counted as new tariff changes.

**Evidence.** Table 2 is a history table, not a current-rate table: rows are classes, columns are
period ranges, and the third column's end month tracks the order's own month (`Jul 2024 – Jul 2025`
in a July order, `Jul 2024 - May 2025` in a May order). Across the 175 processed classes, **140
publish the same tariff in all three periods** and **35 change** — every one of them in Band A, and
every one following the same path, 225.00 -> 206.80 -> 209.50.
That is consistent with the orders' own statement that *"the allowed tariffs for Bands B—E customer
categories shall remain frozen at the rates payable since December 2022"*.

**Rejected alternative.** Keeping only the current column. It would discard the Apr 2024 and
May–Jun 2024 rates, which appear nowhere else in the corpus, and would turn a three-period history
into a single undated number.

**Consequence.** 175 classes × 3 periods = 525 records, of which 175 are current. The en dash and the
hyphen both appear in the same header position across orders, so periods are parsed structurally and
the published text is kept verbatim.

---

## D-43 — VAT is recorded as UNSTATED, because the orders are silent

**Decision.** `vat_treatment = 'UNSTATED'` on every row. Neither inclusion nor exclusion is inferred,
and the build is not blocked to research it elsewhere.

**Evidence.** Every text-bearing order in the corpus was searched for `VAT`, `tax`, `exclusive`,
`inclusive`, `levy`, `surcharge` and `net of`. The only hits are a 0.5 % **gas** levy, NBET invoice
netting, and a feeder literally named `EXCLUSIVE STORES`. The orders approve tariffs in ₦/kWh and say
nothing about VAT.

**Rejected alternative.** Recording `EXCLUSIVE` on the general understanding that Nigerian regulated
tariffs are quoted before VAT. That may well be right, and it is exactly the kind of plausible,
unsourced claim that becomes indistinguishable from a sourced one once it is in a column.

**Consequence.** Anyone computing an electricity cost from this table knows they still have to
establish the VAT treatment themselves.

---

## D-44 — DisCos resolve through a reference table and are never mapped to states

**Decision.** `data/reference/ref_disco.csv` maps all 23 observed filename tokens to 12 canonical
DisCo codes, carries each DisCo's official name as printed on its own order title page, and sets
`state_mapping = 'NOT_MAPPED'` for every one. `disco_raw_label` preserves the token the source used.

**Evidence.** One DisCo appears under up to three tokens: `EKEDP`, `EKEDC` (April 2025 filenames
only) and `EKO` (June 2025 only). The June 2025 batch alone uses full city names — `ABUJA`, `BENIN`,
`ENUGU`, `IBADAN`, `IKEJA`, `KADUNA`, `KANO`, `PORTHARCOURT`, `YOLA` — where every other month uses
abbreviations. Official names were read from the orders rather than assumed: IE's title page reads
*IKEJA ELECTRICITY DISTRIBUTION PLC* while its own body calls it *Ikeja Electric Plc*.

**Rejected alternative.** A DisCo-to-state column. Licence areas cross state boundaries — AEDC alone
serves the FCT and parts of Niger, Kogi and Nasarawa — so any single-state mapping would be wrong,
and a wrong join is worse than an absent one.

**Consequence.** Electricity cost cannot be joined to the state-level datasets in this project, and
that limitation is explicit rather than hidden behind an approximate mapping.

---

## D-45 — Files whose document type cannot be read from their own content are not ingested

**Decision.** The 22 files named `*_HOLDCO_YSS_*` (August and September 2026) are recorded
`DOCUMENT_TYPE_UNVERIFIED` and never ingested. A check asserts none appears in the output.

**Evidence.** All 22 are image-only with zero extractable text, so nothing in the document itself
says what instrument it is. `HOLDCO` and `YSS` appear in no other filename in the corpus.
`nerc_myto_coverage.csv` titles them "AEDC MYTO AUGUST 2026" and so on, but that title was written by
the acquisition step, not read from the PDF.

**Rejected alternative.** Treating them as MYTO orders because the acquisition metadata says so. That
is the same class of error as trusting the coverage CSV's `effective_date` (D-39): a label the
project generated about a source is not evidence about that source.

**Consequence.** 10 % of the corpus is held in an explicitly unverified state rather than silently
counted as tariff orders. Resolving it needs someone to open one and read it.

---


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
11. **Cooking gas is the only dataset with a canonical extreme-callout table.** Petrol and diesel
   deliberately have none (D-23, D-25), so their callout structures are documented but unextracted. If
   state-level extremes are ever wanted across fuels, the three would need reconciling.
12. **Seven 2025 months would lose Kebbi entirely from 12.5 kg without the §4a correction** — the
   state is absent from both the main table and the callouts in 2025-06 … 2025-12.
13. ~~**Transport is the only dataset whose two tables reconcile against each other** (D-29).~~
   **PARTLY DONE.** Food now has one too, by a different mechanism: its national column reconciles
   against its zone sheet through the state-count weights (D-31), 713 of 714 item-releases within
   1e-9. CPI still has no cross-table check; worth considering when it is cleaned.
14. **`NASSARAWA` has now been observed in CPI, diesel, petrol and transport.** The alias was
   harvested from the raw files rather than authored, which is why each new appearance resolves
   without a code change.
15. **Technical debt - the fault-injection harness re-hashes the whole raw corpus per case.** Each
   injected case calls the full validator, whose final check SHA-256s all 342 acquired raw files
   (~1.6 GB). With 17 cases that is roughly 27 GB of hashing per run, and the Transport suite takes
   several minutes as a result. The fix is to verify raw integrity **once per run** in a shared
   harness and let individual cases reuse that verified result, except where a case deliberately
   targets raw-integrity logic and must re-run it. Noted during Transport; **not implemented in that
   commit** so the change is reviewed on its own rather than mixed into a dataset delivery.
   **Update (Food).** The Food fault-injection harness now does exactly this — it memoises
   `sha256_file` for the duration of the run and verifies the corpus once before the first case and
   once after the last, which is what makes a 40-case suite practical. The change lives in the
   scratch harness only; **the pipeline is untouched** and the shared-harness refactor is still open.

16. **Nineteen of the 42 food items have no documented unit** (D-36) — including `Beans white`,
   `Garri Yellow`, `Goat Meat Bone in`, both plantains, `Local Rice (Broken)`, `Sweet potatoes` and
   every fish except crayfish. Neither the spreadsheet label nor any of the 15 report PDFs states one.
   They are NULL and must stay NULL until an official source is found; a future NBS methodology annex
   or basket definition would be the place to look.

17. **The July 2025 food conflict is unresolved, not closed** (D-33). Four item-releases publish a
   zone average above the published state maximum, and nothing in the corpus establishes which side is
   wrong. If NBS ever republishes July 2025, or if a state-level food source appears, it should be
   re-examined rather than left flagged forever.

18. **Two food items are near-duplicates that may or may not be the same product.**
   `Local Rice (Broken)` and `Rice Local, short-Grained` both exist in the basket, and the report
   prose says only "Rice local (1kg)" / "locally produced rice (1kg)". Price anchoring resolved every
   such sentence to `Rice Local, short-Grained`, so that item carries the unit and the other does not.
   Whether the two are genuinely distinct products is a question for NBS, not for the cleaner.
