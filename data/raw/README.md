# Raw Data - Original Source Material

This directory holds **original source material exactly as published**. It is the project's
system of record.

## Sources

All files come from first-party official sources only:

- **NBS** - National Bureau of Statistics (`microdata.nigerianstat.gov.ng`) - food, petrol, diesel,
  cooking gas, transport and CPI price watches.
- **NERC** - Nigerian Electricity Regulatory Commission (`nerc.gov.ng`) - MYTO supplementary orders per DisCo.
- **CBN** - Central Bank of Nigeria (`cbn.gov.ng`) - NFEM daily exchange rates.

No third-party mirror, aggregator or republisher was used.

## Rules

- **Never edit these files by hand.** No renaming, re-saving, re-encoding or repacking.
- **ZIP files stay zipped.** Several NBS releases bundle two or more months, and some bundle both a
  report PDF and a spreadsheet. Read from the archive; do not extract in place.
- **Cleaning happens in a separate layer**, created later. Nothing in this directory is ever the
  output of a transformation.
- **Documented missing periods must not be silently filled** - not by interpolation, not by
  substitution, not from an unofficial source. Known gaps as at `acquisition_cutoff_date =
  2026-09-13`: NBS CPI 2025-01; NBS LPG 2026-05, 2026-06, 2026-07; NBS petrol, diesel, food and
  transport 2026-06 and 2026-07; NERC 2025-03 (all DisCos), NERC 2025-06 (JED), NERC 2025-12
  (EKEDP, JED, PHED), and Aba Power (APLE) in every month after 2025-02.
- **"Not yet due" is not a gap.** The August 2026 NBS releases were scheduled after the cutoff
  (2026-09-15 to 2026-09-29) and are correctly absent. Only a release whose scheduled date has passed
  counts as missing. Full detail in `docs/acquisition/source_coverage_2026-09-13.md`.

## Known source anomaly - preserved deliberately

`nbs/petrol/PMS_Report_JANUARY_2026.zip` contains a member named **`PMS_JANUARY_2025.xlsx`**. The
release is titled and dated January 2026; the 2025 in the inner filename appears to be an NBS naming
error. It has **not** been renamed or repacked. Confirm the period inside that workbook before use.

## Documentation

Acquisition and transfer records live in `docs/acquisition`: source inventory, coverage matrix,
per-DisCo NERC coverage, download verification, SHA-256 transfer verification, and the acquisition audit.
