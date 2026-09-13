# Nigeria Business Cost Intelligence

## Project question

> **How are the costs of doing business changing across Nigerian states, and what should
> different businesses do about it?**

## Current status

| Phase | Description | Status |
|---|---|---|
| 1 | Business problem defined | **COMPLETE** |
| 2 | Official data acquisition | **COMPLETE** |
| 3 | Raw-data preservation and verification | **COMPLETE** |
| 4 | Raw-data profiling | **COMPLETE** |
| 5 | Data dictionary and cleaning-rule design | **NOT STARTED** |

No cleaning, transformation or analysis has been performed.

## Official sources

All data comes from first-party official sources only:

- **National Bureau of Statistics (NBS)** — food, petrol (PMS), diesel (AGO), cooking gas (LPG)
  and transport fare price watches, and the Consumer Price Index
- **Nigerian Electricity Regulatory Commission (NERC)** — MYTO supplementary tariff orders
- **Central Bank of Nigeria (CBN)** — NFEM daily naira/US dollar exchange rate

No third-party mirror, aggregator or republisher was used. Where an official file does not exist,
the gap is recorded rather than filled.

## Raw-source note

The raw files are intentionally excluded from Git because they are large source artifacts
(296 files, approximately 1.2 GB). They remain on disk under `data/raw/` and are never edited.
Their provenance and integrity are documented under `docs/acquisition/`, including SHA-256
verification of every file.

## Repository layout

```
data/raw/          296 official source files (not tracked by Git; see .gitignore)
  README.md        rules governing the raw layer (tracked)
docs/acquisition/  source inventory, coverage matrices, download and transfer
                   verification with SHA-256 hashes, acquisition audit
docs/profiling/    dataset structure summary, column inventory, structural
                   variation report, plain-English data guide
```

## Documentation index

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

Known data gaps and known source-label errors are recorded in
`docs/acquisition/ACQUISITION_AUDIT.md` and `docs/profiling/structural_variations.md`.
They are preserved, not corrected, so the raw layer reflects exactly what each agency published.
