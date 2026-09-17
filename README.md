# Nigeria Business Cost Intelligence

NBCI shows how important external business costs are changing across Nigeria, which types of
businesses those costs are likely to matter more for, and what managers should investigate to
protect their margins.
It is built from eight official Nigerian government datasets, and it is explicit about what the
data can and cannot support.

**Status:** acquisition, cleaning, the PostgreSQL layer, the analysis and two dashboards (Excel and
Power BI) are complete and validated. Tableau and Cognos are not built. Nothing below is claimed as
finished unless the status table says so.

---

## Project overview

**Central question**

> **How are key external business cost pressures changing across Nigeria, how do they differ by
> location where the data supports it, which types of businesses are they likely to matter more
> for, and what should managers monitor or investigate in response?**

A business in Nigeria pays for stock, fuel, power, transport and imported goods. Each of those costs
is measured by a different government agency, published on a different schedule, in a different file
format, and — critically — at a different level of geographic detail.

This project acquires those sources, preserves them unchanged, documents exactly what is in them, and
builds a clean data model that integrates them **without inventing geographic detail the sources do
not provide.**

### What this can and cannot tell you

This distinction is deliberate and it is enforced in the code, not just written down here. Both
dashboards carry the list below as data, and both builds fail if a page ever claims otherwise.

| It can | It cannot |
|---|---|
| Track selected external business cost pressures | Determine whether a specific company is profitable |
| Show how those pressures change over time | Predict whether a company will lose money |
| Compare locations where the source data supports geographic comparison | Identify the universally best jurisdiction to operate in |
| Identify which types of business a particular cost pressure is likely to matter more for | Claim that a cheaper jurisdiction is a better business location |
| Explain why a cost movement may matter to day-to-day operations | Calculate the effect of a cost change on a specific company's margin |
| Show what management should monitor, measure, compare or investigate | Prescribe company-specific actions without financial and market data from that company |
| Provide evidence for further business analysis | |

**What this delivers today is external cost intelligence, business exposure and guidance on what to
investigate.** Turning that into company-specific decision support would need things this project
does not hold: a company's own financial data, its market assumptions, and scenario modelling built
on both. That is a possible later version, not something this one does.

**An earlier version of this README asked how the *cost of doing business* was changing and what
businesses should *do* about it.** That asked more than the data can carry, for three reasons. It
measures nine bought-in costs, not a whole cost base — there is no rent, no wages, no land, no taxes
and no stock in it. Not every source is state-level, so location comparison is valid for some costs
and not others. And telling one company what to do would need that company's own cost shares,
margins and market position, none of which is here.

---

## Why this project matters

Nigerian businesses are absorbing simultaneous pressure from food prices, petrol and diesel, cooking
gas, transport fares, electricity tariffs, inflation and the naira exchange rate. Each of those is
published separately. Nobody publishes the combined picture.

The obvious approach — download everything, join it on state and month, build a dashboard — produces a
confident-looking answer that is partly fabricated. Three of the eight sources do not publish
state-level values at all. Forcing them into a state table means inventing numbers.

The harder and more honest approach, taken here, is to integrate what genuinely joins, keep the rest at
the level it was actually published, and label every measure with its true geographic grain. The
limitations are documented as findings rather than hidden.

---

## Official data sources

**Official government sources only.** No Kaggle, no mirrors, no aggregators, no news sites. Where an
official file does not exist, the gap is recorded rather than filled.

| Agency | What it provides |
|---|---|
| **National Bureau of Statistics (NBS)** | Food, petrol, diesel, cooking gas and transport price watches; Consumer Price Index |
| **Central Bank of Nigeria (CBN)** | NFEM daily naira/US dollar exchange rate |
| **Nigerian Electricity Regulatory Commission (NERC)** | MYTO supplementary electricity tariff orders |

**342 source files, approximately 1.6 GB**, each verified by SHA-256 hash.

The project's `acquisition_cutoff_date` is **2026-09-13** — the date every official source was last
checked. That is **not** an end date for the data. Coverage is source-specific and the families
legitimately stop at different points, from April 2026 (cooking gas) to September 2026 (electricity
tariffs), with the daily exchange rate running to 2026-09-11. The full picture, including which
absences are real gaps and which are simply not yet due, is in
[`docs/acquisition/source_coverage_2026-09-13.md`](docs/acquisition/source_coverage_2026-09-13.md).

---

## Datasets

| # | Dataset family | Source | Files | Published level |
|---|---|---|---|---|
| 1 | Selected Food Price Watch | NBS | 18 | National + zone |
| 2 | Petrol (PMS) Price Watch | NBS | 22 | State + zone + national |
| 3 | Diesel (AGO) Price Watch | NBS | 22 | State + zone + national |
| 4 | Cooking Gas (LPG) Price Watch | NBS | 20 | State + zone + national |
| 5 | Transport Fare Watch | NBS | 14 | State + zone + national |
| 6 | Consumer Price Index (CPI) | NBS | 24 | National, urban, rural + state |
| 7 | NFEM exchange rate | CBN | 5 | National |
| 8 | Electricity tariffs (MYTO) | NERC | 217 | DisCo |

---

## Current project status

| Stage | Status |
|---|---|
| Business problem definition | ✅ Complete |
| Official source acquisition | ✅ Complete |
| Raw-data preservation | ✅ Complete |
| SHA-256 verification | ✅ Complete |
| Source inventory | ✅ Complete |
| Data profiling | ✅ Complete |
| Structural anomaly investigation | ✅ Complete |
| Canonical schema design | ✅ Complete |
| Cleaning-rule design | ✅ Complete |
| Decision log | ✅ Complete |
| Git version control | ✅ Complete |
| Cleaning pipelines (all 8 datasets) | ✅ Complete |
| Processed datasets | ✅ Complete |
| PostgreSQL analytical layer | ✅ Complete — audited 245/245 |
| Analysis discovery + source verification | ✅ Complete — 64/64 and 19/19 |
| Business decision analysis | ✅ Complete — 27/27 |
| Dashboard specification | ✅ Complete |
| Excel dashboard | ✅ Complete — 105/105 structural + 25/25 Microsoft Excel compatibility |
| Power BI dashboard | ✅ Complete — 89/89, all pages inspected rendered |
| Tableau dashboard | ⬜ Not started |
| IBM Cognos work | ⬜ Not started — gated on environment access |
| Business recommendations | ⬜ Not started — gated on review |

---

## Key data challenges discovered

These were found by systematically profiling **219 spreadsheet sheets** and **173 PDFs** before writing
any transformation code. Each one would silently corrupt a naive pipeline.

| Problem | Why it matters |
|---|---|
| **NBS header rows move between files** — found on rows 1, 2, 3, 4, 15 and 16 | Code assuming "row 1 is the header" reads a title sentence as column names for some months and works for others. It fails silently. |
| **Datasets sit at four different geographic levels** | State, zone, national and DisCo cannot be joined as if they were the same thing. |
| **Food Price Watch publishes no complete state-level prices** | Verified in both the spreadsheets and four report PDFs. States appear only in "highest/lowest" callouts. |
| **Petrol holds two side-by-side tables in one sheet** | Columns 1–4 are a state table; columns 6–7 are a separate zone table with different row meanings. |
| **Diesel mixes states, zones and a NATIONAL row in one unnamed column** | Selecting "all rows" returns three geographic levels at once. |
| **Cooking gas has two cylinder-size tables with identical headers** | 5 kg and 12.5 kg can only be told apart by column position, not by name — and the columns moved in 2026. |
| **Transport March 2025 has a duplicated period header** | Two columns are both labelled `Average of Mar-24`; the second is really March 2025, proven by cross-checking the April release. |
| **CPI state index levels cannot rank states by cost** | NBS prints the restriction directly beneath the table: market baskets differ state to state. |
| **CPI contains 96,857 `#REF!` cells** | Every one in a single rebasing working sheet, `Table1 (2)`; the presentation tables contain zero. Processed CPI is the state table only. |
| **CBN has six exact duplicate dates, and blanks that are not zeros** | One column is blank where data is absent; another holds a literal `0`. They mean different things. |
| **Only 11 of 217 NERC orders have a complete, extractable tariff table** | 27 are partial, 1 heading-only, 178 have no tariff text. Processed NERC coverage is a July 2025 cross-section, not a tariff history. A partial table is the real hazard: it looks complete. |
| **DisCo territories are not states** | Licence areas cross state boundaries, so electricity cannot honestly be mapped to states without a separate verified approximation. |

---

## Geographic model

The project deliberately preserves four levels rather than flattening everything into one state table:

| Level | Used by |
|---|---|
| **STATE** | Petrol, diesel, cooking gas, transport, CPI (one table) |
| **ZONE** | Food, and the zone breakdowns of the fuel and transport datasets |
| **NATIONAL** | CBN exchange rate, CPI headline, published national aggregates |
| **DISCO** | NERC electricity tariffs |

**This is not one giant state-level dataset, and it should not be presented as one.** Every measure
carries its true geographic grain so that a chart can never imply detail the source never published.

**Location is one factor here, not the point of the project.** The geographic analysis answers *how
does the external cost environment differ between locations?* It never answers *where is the best
location to run a business?* A cheaper jurisdiction is not a better one, a dearer jurisdiction is not
a worse one, and a dearer jurisdiction does not mean a business loses money there. Whether a business
does well somewhere also depends on revenue opportunity, customer demand, purchasing power, market
size, competition, rent, wages, supplier access, infrastructure and the company's own operating
model — none of which is in this dataset.

---

## Methodology

| # | Step | Status |
|---|---|---|
| 1 | Acquire official source files | ✅ Done |
| 2 | Preserve raw files unchanged | ✅ Done |
| 3 | Verify files using SHA-256 hashes | ✅ Done |
| 4 | Profile workbook and PDF structures | ✅ Done |
| 5 | Document structural differences and source defects | ✅ Done |
| 6 | Design canonical long-format schemas | ✅ Done |
| 7 | Define cleaning and validation rules before transformation | ✅ Done |
| 8 | Build reproducible Python cleaning pipelines | ✅ Done — all 8 datasets |
| 9 | Load clean data into PostgreSQL | ✅ Done — 29,032 fact rows, audit 245/245 |
| 10 | Analyse using SQL and Python | ✅ Done — 3 passes, 110/110 checks |
| 11 | Build dashboards | 🟨 Specification in progress |
| 12 | Produce business recommendations | ⬜ Not started |

**Steps 1–10 are complete and documented in this repository.** Step 11 is at the specification
stage: the dashboard spec is written against the validated analysis before any tool is opened.
Step 12 is deliberately gated — see *Important limitations*.

The sequence is deliberate: the cleaning rules were designed *after* profiling the real files and
*before* writing transformation code, so the rules respond to defects that actually exist rather than
to assumptions about what government spreadsheets usually look like.

---

## Data quality and analytical safeguards

Designed in `docs/data_design/cleaning_rulebook.md` and enforced when the pipeline is built:

- **Raw files are never edited.** Source errors are corrected downstream and documented; the raw file
  keeps the error.
- **Blanks are never automatically converted to zero.** Five distinct states are represented:
  `OK`, `MISSING`, `NOT_REPORTED`, `NOT_APPLICABLE`, `SOURCE_ERROR_REF`. `NOT_APPLICABLE` claims a
  value could not exist and requires an official source; an unexplained blank is `NOT_REPORTED`.
- **National and zone aggregates are explicitly flagged**, never silently averaged in with states.
- **Source errors are corrected only downstream, with provenance** — the wrong label is preserved
  alongside the corrected value.
- **Every cleaned spreadsheet value will be traceable to its original source cell**, via file, sheet,
  row, column index and A1-style cell reference.
- **Repeated NBS observations retain release information.** The same month is restated by several
  releases; `release_month` keeps them distinguishable and enables a free correctness cross-check.
- **CBN exact duplicates remain auditable** — marked, not deleted, so the clean layer still reconciles
  row-for-row against the raw source.
- **NERC tariffs require human validation before analysis.** Every extracted value, not a sample,
  because an OCR digit error is a well-formed number that passes every automated check.

---

## Important limitations

Stated plainly, because they shape what the finished analysis can honestly claim:

- **Complete state-level food prices are not published** in this NBS source — not in the spreadsheets
  and not in the report PDFs. This is a source ceiling, not a workload problem.
- **CPI state index levels cannot be used to say one state is absolutely more expensive than another.**
  Each state's index is re-based to 100 and weights a different basket. Comparing *rates of change* is
  valid; comparing levels is not.
- **CBN exchange rate is national.** It is not apportioned to states.
- **Electricity tariffs are DisCo-level.** They are not converted to states.
- **A DisCo-to-state mapping would require a separate verified approximation**, and even then would
  remain an approximation, because licence areas cross state boundaries.
- **Source gaps are not interpolated or invented.** Missing releases stay missing and are documented:
  eleven NBS releases that were due before the cutoff but never published (LPG May–July 2026; petrol,
  diesel, food and transport for June and July 2026), plus CPI January 2025, NERC March 2025 (all
  DisCos), Aba Power since February 2025, and three further DisCo-months.
- **"Not yet due" is not the same as "missing."** The August 2026 NBS releases were scheduled after the
  2026-09-13 cutoff, so their absence is expected and is not counted as a gap.

---

## Repository structure

```text
Nigeria Business Cost Intelligence/
├── README.md
├── .gitignore
├── data/
│   └── raw/                        # 342 official source files (not committed)
│       ├── README.md               # rules governing the raw layer (committed)
│       ├── nbs/                    # food, petrol, diesel, cooking_gas, transport, cpi
│       ├── nerc/                   # electricity_myto
│       └── cbn/                    # exchange_rate
├── data/
│   ├── processed/                   # 12 cleaned fact CSVs (committed)
│   └── reference/                   # 5 reference tables (committed)
├── src/
│   ├── cleaning/                    # 8 dataset pipelines
│   ├── database/                    # load, audit, restatement simulation
│   └── analysis/                    # a01 discovery, a02 verification, a03 decision inputs
├── sql/                             # 11 build scripts, schemas → grants
├── outputs/
│   └── analysis/                    # curated evidence: discovery, verification, decisions
└── docs/
    ├── acquisition/                # inventory, coverage, verification, audit
    ├── profiling/                  # structure summary, column inventory, data guide
    ├── data_design/                # canonical schemas, rulebook, decision log, schema design
    ├── validation/                 # per-dataset validation reports (8)
    └── analysis/                   # discovery report, business decision analysis report
```

Dashboard artefacts will be added under a `dashboards/` folder once the specification is approved.

### Documentation index

| File | Contents |
|---|---|
| `docs/acquisition/source_inventory.csv` | One row per acquired official release |
| `docs/acquisition/coverage_matrix.csv` | Month-by-month coverage per dataset |
| `docs/acquisition/nerc_myto_coverage.csv` | Per-DisCo, per-month MYTO order coverage |
| `docs/acquisition/download_verification.csv` | Integrity check of every downloaded file |
| `docs/acquisition/transfer_verification.csv` | SHA-256 source-to-destination transfer proof |
| `docs/acquisition/ACQUISITION_AUDIT.md` | Documented gaps, anomalies and limitations |
| `docs/profiling/dataset_structure_summary.csv` | Structure of every release and sheet |
| `docs/profiling/column_inventory.csv` | Every column observed, with inferred role |
| `docs/profiling/structural_variations.md` | How structure differs between months and datasets |
| `docs/profiling/WHAT_THE_DATA_LOOKS_LIKE.md` | Plain-English guide to the data |
| `docs/data_design/canonical_schemas.md` | 13 clean tables with primary keys and examples |
| `docs/data_design/cleaning_rulebook.md` | Evidence-based cleaning and validation rules |
| `docs/data_design/data_dictionary.csv` | 202 column definitions |
| `docs/data_design/decision_log.md` | 16 design decisions with supporting evidence |
| `docs/data_design/postgres_schema_design.md` | Warehouse design: schemas, constraints, mart layer |
| `docs/validation/*.md` | Per-dataset validation reports, one per source (8) |
| `docs/analysis/analysis_discovery_report.md` | Discovery + source verification evidence (Revision 4) |
| `docs/analysis/business_decision_analysis_report.md` | Decision frameworks across six business archetypes |

---

## Reproducibility

The raw source files are **deliberately excluded from Git** — approximately 1.2 GB of government ZIPs,
spreadsheets and PDFs. Committing them would bloat the repository without adding analytical value, and
they are preserved locally instead.

What the repository provides in their place:

| Available now | Still outstanding |
|---|---|
| Source inventory with official download URLs | Environment / dependency manifest |
| Provenance records for every file | Dashboard artefacts |
| SHA-256 hashes for all 342 files | |
| Full methodology and profiling evidence | |
| Cleaning rules and canonical schemas | |
| **Python cleaning code, all 8 datasets** | |
| **11 SQL build scripts and the warehouse design** | |
| **Automated validation — 245 audit assertions, 110 analysis checks** | |
| **Cleaned fact and reference CSVs** | |

Because every file is recorded with its official source URL and its SHA-256 hash, anyone can
re-download the sources and verify they obtained byte-identical files.

**Rerun order.** Build with `python src/database/load_postgres.py`, then verify with
`python src/database/audit_database.py` (245 assertions) and
`python src/database/simulate_restatement.py` (15 checks, rolled back). Reproduce the analysis
with `a01_discovery.py`, `a02_source_verification.py` and `a03_decision_inputs.py` under
`src/analysis/`. Every output is byte-reproducible from a clean state — the PostgreSQL layer was
re-verified by a clean-room rebuild into an empty throwaway database using only the committed
scripts and tracked CSVs, and it reproduced the primary database exactly.

The project has **no dependency manifest yet**; `psycopg` 3.3.4 and `xlrd` 2.0.2 are required.

---

## Planned portfolio outputs

The finished repository is intended to include the following. Items marked ⬜ are **not yet built**.

| Output | Status |
|---|---|
| Data dictionary | ✅ Complete |
| Cleaning decision log | ✅ Complete |
| Methodology documentation | ✅ Complete |
| Source inventory | ✅ Complete |
| Python / pandas cleaning code | ✅ Complete — 8 pipelines |
| PostgreSQL schema | ✅ Complete — audited 245/245 |
| SQL analysis queries | ✅ Complete — 11 build scripts, 28 mart views |
| Automated validation checks | ✅ Complete — 110/110 analysis, 245/245 audit |
| Analysis evidence reports | ✅ Complete — discovery + business decision analysis |
| Reproducibility instructions | ✅ Complete — see *Reproducibility* |
| Dashboard specification | ✅ Complete |
| Excel workbook | ✅ Complete — 7 question-led sheets + 3 data sheets, validated |
| Power BI dashboard | ✅ Complete — PBIP project, 7 pages, 98 visuals, validated |
| Tableau dashboard | ⬜ Planned |
| IBM Cognos work | ⬜ Planned |
| Dashboard screenshots | ⬜ Planned |
| Business recommendations | ⬜ Planned — gated on review |

---

## Skills demonstrated

**Already demonstrated in this repository**

- **Data acquisition** — sourcing 342 files from three government agencies, including discovering a
  JSON API behind a JavaScript-rendered page and paging a document library to build a complete index
- **Data profiling** — systematic structural analysis of 219 spreadsheet sheets and 173 PDFs
- **Data validation** — SHA-256 verification of every file at download, transfer and after each phase
- **Source verification** — proving a mislabelled file's true period by cross-checking 33 states'
  values against an adjacent release
- **Data modelling** — 13 canonical long-format tables with justified primary keys across four
  geographic grains
- **Data-quality investigation** — identifying moving headers, stacked tables, duplicate column
  labels, embedded aggregates and OCR risk *before* writing transformation code
- **Documentation** — acquisition audit, profiling reports, cleaning rulebook, decision log
- **Git / version control** — staged commits with a verified baseline
- **AI-assisted analytical workflow** — using AI tooling for systematic investigation while
  independently verifying every claim against the source files

- **Analytical communication** — every dashboard page states its conclusion in plain English before
  any chart is shown, with the exact figures, method and limits kept on a second layer for analysts
- **Dashboard engineering** — an Excel workbook and a Power BI PBIP project built and validated by
  script, with the analysis rules enforced structurally rather than by convention

**To be demonstrated in later stages**

- Tableau · IBM Cognos

---

## Raw data policy

**`data/raw/` is not committed to Git.**

The 342 official government files are preserved locally and protected by SHA-256 verification recorded
in `docs/acquisition/`. They are never edited, renamed, re-saved or extracted in place. ZIP archives
stay zipped; the raw layer mirrors exactly what each agency published, including its errors.

Every file is documented with its official source URL, file size and hash, so the raw layer can be
reconstructed from the original government sources and verified against the recorded hashes.

---

*Independent portfolio project. Not affiliated with NBS, CBN or NERC. All data is published by those
agencies and used here for analysis.*
