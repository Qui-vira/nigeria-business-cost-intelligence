# Structural Variation Report — NBS, CBN, NERC

Phase 2 profiling. **Observation only.** Nothing was cleaned, changed or extracted permanently.
All figures below were measured from the 296 preserved raw files by reading them read-only;
ZIP members were read in memory and never unpacked to disk.

Scope measured: **118 NBS files → 219 spreadsheet sheets** (218 readable, 1 not),
**5 CBN files**, **173 NERC PDFs** (text-layer scan only, no OCR).

> **Scope note (added 2026-09-13).** This is a Phase 2 profiling record of the **original 296-file
> corpus**, and its figures are kept as the historical measurement. The project was later extended to
> `acquisition_cutoff_date = 2026-09-13`, adding **46 files** (44 NERC MYTO orders, 2 NBS CPI
> archives) that have **not** been profiled. For current coverage and current CBN figures see
> [`docs/acquisition/source_coverage_2026-09-13.md`](../acquisition/source_coverage_2026-09-13.md).

---

## 1. NBS Selected Food Price Watch

**18 files, 34 sheets, 3 schema families, header always on row 1.**

| Question | Finding |
|---|---|
| Same workbook structure across releases? | **Nearly.** 3 families, and the differences are cosmetic rather than layout-level. |
| Which months differ? | **February 2025** renames the first column `Item Label` → **`Item Labels`** (plural). |
| Do sheet names change? | **Yes, every month** (`Selected Food Sept 2025`, `Selected Food May 2026`, …). |
| Do headers move? | **No.** Row 1 in all 34 sheets — the most stable dataset in the set. |
| Columns appear/disappear? | Column *count* varies 7–12, but only because of trailing empty columns. The 8 real columns are stable. |
| Wide/long changes? | No. |
| Combined vs single releases? | The Aug–Sept 2025 ZIP holds **two separate single-month workbooks**, not one merged sheet. Structurally identical to single-month releases. |
| Totals embedded with observations? | **No** — the cleanest dataset in this respect. |

**Every workbook contains two sheets:**
- `Zone All item` — `Item Label` × the 6 geopolitical zones. Same 7 columns in all 17 occurrences.
- `Selected Food <Month Year>` — `Item Label | Average of <year-ago> | Average of <prior month> | Average of <current> | MoM | YoY | Highest | Lowest`.

**Issues that will matter during cleaning:**

1. **There is no state column anywhere in the food spreadsheets.** The only state-level information is
   buried inside the `Highest` and `Lowest` text cells, formatted as `Enugu (356.73)` — a state name and
   a price packed into one string. Even after parsing, that yields only the max and min state per item,
   never all 36. **Nor do the report PDFs rescue this — verified, see below.**

   **Verified against the May 2025, Nov 2025, Jan 2026 and May 2026 report PDFs:** the contents page of
   every one lists *National* followed by the six *zones* — there is no state section. The only
   state-dense page is the same `Highest` / `Lowest` appendix table already present in the spreadsheet.
   The executive summary names states only in that same highest/lowest framing ("Lagos State recorded
   the highest average price for 1kg of tomatoes… Ekiti State the lowest").

   So **a full state × item food price table does not exist in these NBS releases at all** — not in the
   spreadsheet, not in the PDF. NBS collects the underlying prices from every state (the methodology page
   states fieldwork is done by "over 700 NBS Staff in all States") but publishes only national, zone, and
   the highest/lowest state per item. No amount of PDF extraction will produce state-level food prices
   from this source.
2. **Exactly 15 items have no year-ago average** (column 2) and therefore **no YoY** (column 6) —
   in each of the 12 releases 2025-01 … 2025-12, and in **none** of the five 2026 releases, where the
   year-ago column is complete for all 42 items. Verified cell-by-cell: these are genuinely empty cells
   in the correct positions, **not shifted rows**. January 2025 additionally has no prior-month value or
   MoM for the same 15 items, consistent with the rebased series starting. 180 + 15 = 195 blanks in
   total. The count is release-dependent and must never be stated as "per month" (D-34).
3. **Two files carry a stale sheet name.** `selected_food_table_Apr25.xlsx` and
   `selected_food_table_Mar_25.xlsx` both name their sheet `Selected Food Dec 2024`. The column headers
   (`Average of Apr-25`, `Average of Mar-25`) confirm the **data is correct** — only the sheet label is wrong.

---

## 2. NBS PMS (Petrol) Price Watch

**22 files, 17 sheets, 2 schema families — but the header row moves.**

| Question | Finding |
|---|---|
| Same structure? | Column *meaning* is stable; **physical position is not**. |
| Headers move? | **Yes — badly.** Header found on row **1** (7 sheets), **2** (5), **3** (1) and **15** (4). |
| Sheet names change? | Yes, every month; one breaks the pattern entirely (`PMS_OCT_2025` vs `Fuel December 2025`). |
| Columns appear/disappear? | **January 2026 drops the Zone block**, leaving only `State` + 3 date columns. |
| Wide/long changes? | No — WIDE throughout. |
| Totals embedded? | **Yes, in all 17 sheets.** |

**Layout:** `State | <year-ago date> | <prior-month date> | <current-month date> | (blank) | Zone | Average Price`.

**Issues that will matter during cleaning:**

1. **Two different tables share one sheet.** Columns 1–4 are a *state* table; columns 6–7 are a separate
   *zone* table sitting beside it. They have different row meanings and different lengths.
2. **The header row jumps from row 1 to row 15.** Loose `.xlsx` files (Jan–Jun 2025) start at row 1;
   ZIP-era files (Jul 2025 onward) put a report title and a narrative paragraph above the table.
   Any loader that assumes a fixed header row will silently read garbage for one group or the other.
3. **Column headers are real Excel datetimes, not text** (`2025-12-01 00:00:00`), and they encode the
   *period each column measures*. The period is in the header, not in a column.
4. **An `AVERAGE` row sits at the bottom of the state list**, followed by `Year on Year` and
   `Month on Month` footnote rows — national figures physically inside the state data block.
5. **October 2025 has a wrong title row:** the sheet's title reads
   `PREMIUM MOTOR SPIRIT AVERAGE PRICE PER LITRE AUGUST 2025 REPORT` while the narrative and the data
   are October 2025. Label error only.
6. **January 2026 mislabelling** — see §7 below.

---

## 3. NBS AGO (Diesel) Price Watch

**22 files, 17 sheets, 2 schema families. Mirrors petrol, with one extra hazard.**

| Question | Finding |
|---|---|
| Headers move? | **Yes** — rows **1** (7), **2** (3), **3** (2) and **16** (5). |
| Sheet names change? | Yes, and **4 sheets are named the meaningless `Sheet1`**. |
| Columns appear/disappear? | Column count ranges 9–17 (trailing blanks). Core columns stable. |
| Totals embedded? | **Yes, all 17 sheets** — a `NATIONAL` row at the bottom. |

**Layout:** `(blank header) | <3 date columns> | YoY | MoM | (blank) | Zone | value`.

**Issues that will matter during cleaning:**

1. **The geography column has no header at all** — it is an empty string.
2. **Zones and states are interleaved in that same single column.** `NORTH CENTRAL` appears as a row,
   then `Abuja`, `Benue`, `Kogi`… then the next zone. Two different levels of geography stacked in one
   column with nothing but the value itself to tell them apart. Selecting "all states" requires knowing
   the 6 zone names to exclude, plus the `NATIONAL` row.
3. Same side-by-side second table and same moving-header problem as petrol.

---

## 4. NBS LPG (Cooking Gas) Price Watch

**20 files, 16 sheets, 3 schema families. Header consistently on row 2 — but the columns move.**

| Question | Finding |
|---|---|
| Headers move? | **No** — always row 2, under a merged `5KG` / `12.5KG` banner in row 1. |
| Columns appear/disappear? | **Yes.** 2026 releases add a `STATES` header and shift the geography column from **col 1 → col 3** (and col 9 → col 11 for the second table). |
| Do names change? | **Yes** — `MoM`/`YoY` become `MOM`/`YOY` in 2026. Sheet names drift to `Sheet1`. |
| Combined vs single? | Nov–Dec 2025 and Feb–Mar 2026 ZIPs each hold two separate single-month workbooks. |
| Totals embedded? | **Yes, all 16 sheets.** |

**Issues that will matter during cleaning:**

1. **Two products in one sheet, side by side.** Columns 1–6 are the **5 kg** cylinder; columns 9–14 are
   the **12.5 kg** cylinder. The product is identified only by a merged banner cell in row 1.
2. **Three stacked mini-tables per sheet:** the main zone/state table, then an `Average` national row,
   then `STATES WITH THE HIGHEST AVERAGE PRICES` and `STATES WITH THE LOWEST AVERAGE PRICES` blocks,
   each with its own informal layout.
3. **Zones and states share one column**, as in diesel.
4. **Some geography cells hold two states at once** — e.g. `Kebbi/Nasarawa` where two states tie.
5. **The column shift between 2025 and 2026 is silent.** Nothing in the file announces it.

---

## 5. NBS Transport Fare Watch

**14 files, 34 sheets, 3 schema families, header always row 1.**

| Question | Finding |
|---|---|
| Headers move? | **No.** Row 1 throughout. |
| Sheet names change? | The month sheet changes every month; `State Transport` is stable across 17 sheets. |
| Combined vs single? | **The most combined dataset** — May+June+July 2025 (three workbooks in one ZIP), Aug+Sept 2025, Nov+Dec 2025. Each member workbook is still single-month. |
| Totals embedded? | **Yes** — a `Grand Total` row in every `State Transport` sheet. |

**Every workbook contains two sheets:**
- `State Transport` — **genuinely state-level**: `State` × 5 transport modes (air fare, intercity bus,
  intracity bus, okada, water transport). Stable 6 columns.
- `Transport <Month Year>` — headed `Zone`, but it **stacks two different things in one column**:
  first the five transport *modes*, then the six *zones*.

**Issues that will matter during cleaning:**

1. **Column headers are full sentences**, e.g.
   `Bus journey intercity, state route, charg. per person` — long, inconsistently spaced, and they
   change punctuation between months.
2. The month sheet's `Zone` column contains modes *and* zones — the header names only one of them.
3. **State names are upper-case here** (`ABIA`, `AKWA IBOM`) but title-case in petrol (`Abia`) — they
   will not join across datasets without normalisation.

---

## 6. NBS Consumer Price Index and Inflation

**22 files, 101 sheets (100 readable), 12 schema families. By far the most complex.**

| Question | Finding |
|---|---|
| Same structure? | **No.** 12 distinct schema families. |
| Headers move? | **Yes** — rows **2** (65 sheets), **3** (1) and **4** (34). |
| Sheet names change? | 10 distinct names: `Table1`–`Table4`, `Table-5`, plus `(2)` and `(3)` duplicates. |
| Columns appear/disappear? | **Dramatically** — column counts range from **12 to 65**. |
| Wide/long changes? | Every sheet is wide, with periods as rows and measures as columns. |
| Totals embedded? | Weights rows, `Multipling Factor` and `Rereferencing Average` rows sit inside the data. |

**What each sheet is:**
- `Table1` — composite CPI over time (national).
- `Table2` — composite CPI by division/category.
- `Table3` — **urban** CPI. `Table4` — **rural** CPI.
- `Table-5` — **the only state-level table**: `State` (column 2) × 3 periods × (`Food`, `All Items`),
  plus annual and monthly change.
- `Table1 (2)`, `Table2 (2)`, `Table3 (2)`, `Table3 (3)`, `Table4 (2)` — **rebasing working sheets**,
  366–369 rows, carrying both the old 1985 base and the new 2024 base side by side.

**Issues that will matter during cleaning:**

1. **Two-level headers.** In `Table-5` the period (`2026-05-01`) is on row 3 and `Food`/`All Items` on
   row 4, so the same header word repeats six times and means something different each time.
   Reading only one row loses the period; reading only the other loses the measure.
2. **96,857 Excel `#REF!` error cells — every one of them in `Table1 (2)`.**
   *(Corrected during dataset #8: the earlier figure of 69,411 "across 5 workbooks" undercounted and
   mislocated them.)* Measured across all 17 `.xlsx` releases: 13,922 per release in 2025-12 …
   2026-04 and 13,723 in 2026-05 … 2026-07, and **zero** in `Table1`, `Table2`, `Table3`, `Table4`
   and `Table-5`. The broken cells are confined to one rebasing working sheet; the presentation
   tables are clean.
3. **`Table-5` carries NBS's own warning**, printed directly beneath the table:
   > *"Indices may not be used for inter-state price comparison because market baskets differ state to state."*

   This speaks directly to the project question. State CPI levels are **not** comparable between states;
   only each state's *change over time* is. This constraint must survive into the analysis.
4. **March 2026 ships a legacy `.xls`**, nested inside a `March_2026/` subfolder — the only CPI release
   that does both. It could not be opened during profiling because no `.xls` reader was installed.
   *(Resolved in dataset #8: `xlrd` 2.0.2 was installed (D-54) and the file reads correctly. Its
   `Table-5` is structurally identical to the other 17 — 42 × 12, 37 states plus the footnote, three
   index periods, both change columns, `(Base Period: 2024 = 100)` explicit, zero empty cells. The
   only difference is that date cells arrive as Excel serials and are converted.)*

5. **Two verified source defects in `Table-5`**, both found by cross-release comparison in dataset #8
   and both documented rather than corrected:
   - `cpi_1New_February2026.xlsx` labels its year-ago column `2025-02-01` but publishes the **January
     2025** values — 74/74 byte-identical to January, 0/74 to February, with March 2026 as a 74/74
     control (D-51).
   - `cpi_1New_Apr25.xlsx` assigns 67 of 74 state values to the wrong state from Bayelsa down; the
     May 2025 and April 2026 releases both contradict it and agree with each other on 73 of 74
     (D-52).
6. **January 2025 is missing entirely** (documented at acquisition — no such NBS release exists).

---

## 7. The PMS January 2026 anomaly — resolved

`PMS_Report_JANUARY_2026.zip` contains a member named **`PMS_JANUARY_2025.xlsx`**, and that workbook's
own title row also reads `… JANUARY 2025 REPORT`. **The data is January 2026.** Evidence in
§7 of `WHAT_THE_DATA_LOOKS_LIKE.md` and in the final report. Neither the file nor the title row was changed.

---

## 8. CBN NFEM Daily Exchange Rate

**5 files. The only LONG-shaped dataset in the project, and the tidiest.**

- `…_snapshot_….json` — the official raw API response, **445 records**, the source of record.
- `…EXTRACTED-FROM-CBN-WEBPAGE.csv` — our derived extract, **352 in-window rows**.
- `…page_snapshot_….html`, `…script1_….js` — page and script snapshots.
- `PROVENANCE_READ_ME.txt` — provenance note.

One row = one trading day, nationally. **No state dimension at all.**

**Issues that will matter during cleaning:**

1. **6 duplicate rate dates** — 2025-02-03, 2025-02-07, 2025-02-18, 2025-05-12, 2025-05-23, 2025-06-19.
   All six are **exact duplicates**: every value identical, only the internal `id` differs. No conflict.
2. **Two different kinds of "missing" in the same file.** `NFEM Interbank Turnover`,
   `No. of Deals at Interbank` and `NFEM Total Turnover` are **empty** in 300 of 352 rows, while
   `No. of Deals at NFEM` is a **literal `0`** in 297 rows. A zero and a blank are not the same thing
   and must not be treated alike.
3. The five core rate fields (NFEM, highest, lowest, closing, simple average) are **100% complete**.
4. All values arrive as **strings**, not numbers; dates are text in `Month-DD-YYYY` form.
5. 22 weekdays have no observation (listed at acquisition, deliberately not filled).

> Items 2 and 5 were measured against the extracted CSV derivative, which holds the 352 rows that were
> in-window under the original 2026-05-31 cutoff. Under the current 2026-09-13 cutoff the raw JSON
> yields **425** in-window rows, **300** with empty turnover, **298** with a literal `0` deal count,
> and **24** weekdays with no observation. The *kinds* of defect described here are unchanged.

---

## 9. NERC MYTO Orders — the biggest obstacle in the project

**173 PDFs, 12 DisCos, 16 months.** A text-layer scan of every file (no OCR performed) found:

| | Files |
|---|---|
| **Image-only — no extractable text, OCR required** | **134** |
| Text-based — parseable today | **39** |
| **All 55 of the 2026 orders** | **image-only** |

> **Superseded by the dataset #7 build (D-38).** The counts above were taken over 173 files at
> profiling time and measured the wrong thing: whether a *file* has a text layer, not whether its
> *tariff table* does. Re-measured over all 217 files, examining every page carrying a tariff
> heading: **11 complete tariff tables, 27 partial, 1 heading-only, 178 with no tariff text.** 89
> files carry some text layer — including 33 of the 2026 orders, whose one text page is the
> effective-date page, never the tariff table. Routing is per page, not per file.

**Document structure (from the text-based sample: AEDC 2025-01, IE 2025-07, PHED 2025-11,
EKEDP 2026-01, KEDCO 2026-05 — 5 DisCos, 5 months, both years):**

- **Title format:** `ORDER/NERC/<year>/<sequence>`, then
  `IN THE MATTER OF <MONTH YEAR> SUPPLEMENTARY ORDER TO THE MULTI-YEAR TARIFF ORDER 2024 FOR <DISCO>`.
- **Effective period** is stated in prose, not in a field:
  *"This Supplementary Order shall be effective from 1st February 2025"*, and
  *"Approved End-User Tariffs Effective from 1st July 2025"*.
- **Tariff tables are present.** `Table 2 – Approved Allowed Tariffs (₦/kWh)` is the key one, typically
  **page 3 or 4**. A tariff-assumptions table (loss target, Nigerian and US inflation, exchange rate,
  gas price) sits just before it. `Appendix 1` lists customer classifications.
- **Tariff classes** appear as service **Bands A–E** and customer classes `R1`/`R2`/`C1`/`D1`/`A1`/`MD1`/`MD2`.
- **Structure is broadly consistent across DisCos** — same order template, same clause numbering.
  Page counts vary 8–30 because appendices differ.

**Issues that will matter during cleaning:**

1. **77% of the corpus needs OCR before a single number can be read.** This is the dominant cost in the project.
2. **Even some "text-based" files are themselves prior OCR output**, with recognition errors baked in:
   `AEDC_February_2025_003.pdf` contains `IN THE MAilER OF`, `ORDER/NERC/2025/o03` (letter *o* for zero),
   `A- . roved Allowed Tariffs`, and `1”` where `1st` was meant. Text extraction will succeed and still
   return corrupted words.
3. **Table extraction quality is uneven.** `IE_July_2025_064.pdf` has real vector tables that extract
   cleanly; `AEDC_February_2025_003.pdf` has text but **no vector table structure**, so the same code
   will not work on both.
4. Extracted tables carry **merged header cells** — a period spanning several sub-columns, leaving blank
   header cells that must be forward-filled.
5. **One order per DisCo, not per state.** DisCo licence areas do not map one-to-one onto the 36 states,
   so any state-level electricity cost will require a DisCo→state mapping that does not exist in this data.

---

## 10. Cross-cutting problems

1. **Geographic granularity differs by dataset** — the single biggest threat to the project question.

   | Dataset | State-level? |
   |---|---|
   | Petrol | **Yes** — clean `State` column |
   | Transport | **Yes** — `State Transport` sheet |
   | Diesel | **Yes**, but states and zones are mixed in one unlabelled column |
   | Cooking gas | **Yes**, but mixed with zones, and the column moves in 2026 |
   | CPI | **Only in `Table-5`**, and NBS forbids comparing levels between states |
   | Food | **No** — zone-level only; states appear only inside `Highest`/`Lowest` text |
   | CBN FX | **No** — national only |
   | NERC | **No** — DisCo licence areas, not states |

2. **State name formatting is inconsistent** — `ABIA` vs `Abia`, `Abuja` vs `FCT`, `Kebbi/Nasarawa` in one cell.
3. **National and zone totals are embedded inside state data blocks** in petrol, diesel and LPG —
   every one of those 50 sheets. Filter them out and you lose the national figure; leave them and every
   average is double-counted.
4. **The period is stored in the column header, not in a column**, for food, petrol, diesel, LPG and transport.
5. **Header rows are not fixed** — row 1, 2, 3, 4, 15 or 16 depending on dataset and month.
6. **Combined multi-month releases are not structurally different.** In all 8 cases the ZIP simply holds
   one separate workbook per month. This is good news: no special-case parsing is needed.

---

## 11. Known label errors — preserved, not corrected

| File | What is wrong | Verified reality |
|---|---|---|
| `PMS_Report_JANUARY_2026.zip` → `PMS_JANUARY_2025.xlsx` | Member filename and title row say 2025 | Data is **January 2026** |
| `PMS Report OCTOBER 2025.zip` | Title row says `AUGUST 2025 REPORT` | Data is **October 2025** |
| `selected_food_table_Apr25.xlsx` | Sheet named `Selected Food Dec 2024` | Headers confirm **April 2025** |
| `selected_food_table_Mar_25.xlsx` | Sheet named `Selected Food Dec 2024` | Headers confirm **March 2025** |

No file was renamed, repaired or re-saved.
