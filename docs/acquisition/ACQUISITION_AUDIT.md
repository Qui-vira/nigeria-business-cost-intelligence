# Nigeria Business Cost Intelligence - Source Acquisition Audit

Stage: **DATA ACQUISITION ONLY.** No cleaning, transformation, analysis or calculation performed.
Target period: **2025-01 through 2026-05** (17 months).
Sources used: **NBS microdata catalogue, NERC, CBN only.** No third-party source was used anywhere.

Files acquired: **296** (~1.20 GB). Integrity checks: **296 PASS / 0 FAIL.** Duplicate content: **none.**

> **This document is the record of the FIRST acquisition round and its figures are historical.**
> Every number below — 296 files, the 2025-01..2026-05 target period, 173 NERC orders, the 352-row CBN
> extract, 22 missing weekdays — was true of that round and is deliberately preserved unchanged.
>
> The project was extended on **2026-09-13** (`acquisition_cutoff_date = 2026-09-13`), adding 46 files
> for a total of **342**. The target period no longer ends at 2026-05; coverage is source-specific.
> **For current coverage, current gaps and the current CBN figures, read
> [`source_coverage_2026-09-13.md`](source_coverage_2026-09-13.md)**, and for the extension's hashes
> read [`extension_2026-09-13_verification.csv`](extension_2026-09-13_verification.csv).
>
> The "MISSING" rows in §1 below remain open, except that they are now joined by ten further NBS
> releases that fell due between the two rounds.

---

## 1. Missing months / files

| Dataset | Month | Status |
|---|---|---|
| NBS LPG (Cooking Gas) Price Watch | 2026-05 | **MISSING** - latest official LPG release in catalog 160 is April 2026. Confirms the expectation stated in the brief. |
| NBS Consumer Price Index and Inflation | 2025-01 | **MISSING** - catalog 154 jumps from December 2024 straight to February 2025. |
| NERC MYTO | 2025-03 | **MISSING for all 11 DisCos** - no March 2025 MYTO order published. |
| NERC MYTO | 2025-06 | **JED missing** (other 10 DisCos present). |
| NERC MYTO | 2025-12 | **EKEDP, JED, PHED missing** (other 8 present). |

### CPI January 2025 - detail
Between December 2024 and February 2025 the catalogue instead carries
*"Highlights of 2024 CPI Rebasing Results"*. The CPI was rebased in this window, and no standalone
January 2025 release exists in the official NBS microdata catalogue. Verified by three checks:
catalogue listing, direct page inspection, and a site-wide microdata search (catalog 154 is the only
CPI collection). The rebasing highlights PDF was downloaded and is filed under `nbs/cpi/` with
`months_covered = NOT_APPLICABLE` (methodology reference, not a monthly release).
**Not substituted from any unofficial source.**

### NERC gaps - how they were confirmed
Three independent discovery methods were used before declaring a gap:
1. Paging the entire official MYTO document category (`?doc_publication=myto`, 44 pages, 432 documents).
2. Per-month and per-DisCo title searches, including alias spellings NERC actually uses
   (PHED/PHEDC, EKEDP/EKEDC, JED/JEDC, IE/IKEDC, KAEDC/KAEDCO) and NERC's own title typos
   ("FEBRURAY 2026", "DECECEMBER 2025").
3. Direct probing of the `wp-content/uploads/...` sibling filename patterns. All returned 404.

---

## 2. Combined releases (one official file covering several months)

NBS bundles months together. Each ZIP below was downloaded **once**, preserved unchanged, and its
member list was read to confirm coverage - coverage was **not** inferred from the filename.

| Dataset | File | Months covered |
|---|---|---|
| Selected Food Price Watch | SELECTED_FOOD_PRICES_AUG_SEPT_2025.zip | 2025-08, 2025-09 |
| PMS (Petrol) Price Watch | PMS_Report_AUG_SEPT_2025.zip | 2025-08, 2025-09 |
| AGO (Diesel) Price Watch | AGO_Report_AUGUST_SEPTEMBER_2025.zip | 2025-08, 2025-09 |
| LPG (Cooking Gas) Price Watch | LPG_Nov_Dec_2025.zip | 2025-11, 2025-12 |
| LPG (Cooking Gas) Price Watch | LPG_Report_Feb-March_2026.zip | 2026-02, 2026-03 |
| Transport Fare Watch | Transport_MAY_JUNE_JULY_2025.zip | 2025-05, 2025-06, 2025-07 |
| Transport Fare Watch | Transport_Report_AUG_SEPT_2025.zip | 2025-08, 2025-09 |
| Transport Fare Watch | Transport Fare Watch Report Nov_Dec_2025.zip | 2025-11, 2025-12 |

---

## 3. Months with a spreadsheet but no PDF report

No in-window month is PDF-only. The reverse occurs in five months - spreadsheet exists, no report PDF:

- Selected Food Price Watch: **2025-02, 2025-03**
- Transport Fare Watch: **2025-01, 2025-02, 2025-03**

Methodology/validation material for those months will have to come from an adjacent month's report.

---

## 4. Suspicious date / filename mismatches

1. **`nbs/petrol/PMS_Report_JANUARY_2026.zip`** contains a member named **`PMS_JANUARY_2025.xlsx`**.
   The release is titled "PMS Report January 2026" and is dated accordingly; the **2025** in the inner
   spreadsheet name appears to be an NBS naming error. The file was preserved exactly as published.
   *Confirm the period inside this workbook before use.*
2. **`nbs/cpi/CPI_Report_March_2026.zip`** contains a legacy **`.xls`** workbook
   (`March_2026/cpi_1New_March2026.xls`) where every other CPI month ships `.xlsx`, and it is the only
   CPI archive that nests its members inside a subfolder.
3. **NERC December 2025 orders** are served from `wp-content/uploads/**2026/04**/` while their listed
   publication date is 1 December 2025 - i.e. re-uploaded roughly four months later.

---

## 5. NERC publication lag

**66 orders carry a website publication date later than the month they take effect**, concentrated in
2025-01 and 2025-07 through 2025-11 (11 DisCos each). Several 2025 months were published in a single
catch-up batch on 7 December 2025. Per the brief, `nerc_myto_coverage.csv` keys on the **effective
month** taken from the official release title; the website publication date is recorded separately in
the `notes` column and flagged where it is later than the effective month.

---

## 6. An extra DisCo found

**APLE (Aba Power Limited Electric)** has one MYTO order in the window (**2025-02**). It is not part of
NERC's regular monthly MYTO cycle for this period, so it is listed in `nerc_myto_coverage.csv` only for
the month where an order actually exists, with an explanatory note - rather than as 16 false gaps.
The 11 DisCos named in the brief are all present and all carry full 17-month rows.

---

## 7. CBN acquisition method and open questions

CBN publishes **no server-side historical download** for the NFEM table; the page's "Export to Excel"
button builds a file **client-side in the browser** from a JSON feed. What was preserved:

1. The unmodified raw JSON from the official same-origin endpoint `cbn.gov.ng/api/GetAllNFEM_Rates`
   - **the primary source of record** (445 records, 2024-12-02 to 2026-09-11; NFEM began 2024-12-02).
2. A raw HTML snapshot of the official page, plus its `script1.js`, retained as evidence of the
   JSON-field to column-header mapping.
3. A CSV of the 352 in-window rows, filename-labelled `EXTRACTED-FROM-CBN-WEBPAGE`, values copied
   verbatim - no rounding, reformatting, interpolation, weekend/holiday filling or aggregation.
   Dates are left in CBN's own `Month-DD-YYYY` format.

**22 weekdays in the window carry no CBN observation.** They are listed individually in
`cbn/exchange_rate/PROVENANCE_READ_ME.txt` and were **not** filled. They are expected to be Nigerian
public holidays or non-trading days, but that has **not been verified** at this stage and remains an
open question for the analysis step.

---

## 8. Failed downloads and duplicates

- **Failed downloads: none.** 118/118 NBS, 173/173 NERC, all CBN captures succeeded.
- **Duplicate files: none.** Every one of the 296 files has a distinct SHA-256.

---

## 9. Reading the coverage matrix

`coverage_matrix.csv` carries one NERC row, `NERC Electricity MYTO Orders (any DisCo in month)`,
marked FOUND when at least one official order exists for that month. Because NERC publishes per DisCo
rather than one national file, a month can read FOUND there while individual DisCos are still missing
(2025-06 and 2025-12). **`nerc_myto_coverage.csv` is the authoritative per-DisCo record** - use it,
not the summary row, when assessing electricity coverage.


---

## 10. Post-transfer cleanup - 20 pre-existing extracted duplicates removed (2026-09-13)

Before the verified transfer ran, `data/raw/` already contained **20 loose files in 10 folders**,
created earlier the same day. They were extracted contents of five NBS Selected Food Price Watch
releases (January-May 2026), duplicated under two parallel naming schemes
(`january_2026/` and `Selected_Food_Report_Jan26/`, and so on for each month).

**All 20 were removed**, along with their 10 now-empty parent folders, after SHA-256 verification
confirmed every one was **byte-identical to a member of a preserved official NBS ZIP archive** in
`data/raw/nbs/food/`. The 20 files represented only 10 distinct payloads (5 months x report PDF +
spreadsheet), each held twice. **No unique data existed in them**, and all five corresponding official
ZIPs were confirmed present before anything was deleted.

Post-cleanup verification: official raw source count **296** (unchanged), integrity checks
**296 PASS / 0 FAIL**, **60 official ZIP archives** intact, and **0 of 296** file hashes changed when
compared against the transfer baseline. `data/raw/` now contains only `README.md`, `nbs/`, `nerc/`
and `cbn/`.

No official source file was deleted, renamed, extracted or modified. The acquisition CSVs
(`source_inventory.csv`, `coverage_matrix.csv`, `nerc_myto_coverage.csv`,
`download_verification.csv`, `transfer_verification.csv`) were **not** altered.

*Note for future re-verification:* this file has been appended to since the transfer, so its own
SHA-256 no longer matches the value recorded for it in `transfer_verification.csv`. That row covers
documentation, not raw source data; all 296 raw source hashes remain exactly as recorded.
