# Source Coverage as at the 2026-09-13 Acquisition Cutoff

**`acquisition_cutoff_date = 2026-09-13`**

This document records how far each dataset family actually reaches. It supersedes any earlier
statement that the project runs "January 2025 – May 2026".

---

## The distinction that matters

**The acquisition cutoff is not a dataset endpoint.**

| Term | Meaning |
|---|---|
| `acquisition_cutoff_date` | The date every official source was last checked. One date, project-wide. **2026-09-13.** |
| `latest observation date` | The most recent period a *given publisher* has actually released. One per dataset family. **These differ, legitimately.** |

A single cutoff produced eight different endpoints. That is not an acquisition failure — it is what
the publishers had released by that date. Nothing is padded forward to make the families line up, and
no analysis may assume a rectangular window across all eight.

The spread is mostly explained by NBS's own release schedule: CPI is published around the 15th of the
following month, while the price watches land around the 22nd–29th. A cutoff on the 13th of a month
therefore catches strictly more CPI months than price-watch months, even when NBS is on time.

---

## Coverage by dataset family

| Dataset family | Latest observation | Granularity | Source |
|---|---|---|---|
| CBN NFEM exchange rate | **2026-09-11** | Daily | CBN API |
| NERC electricity tariffs | **September 2026** | Monthly, per DisCo | NERC |
| NBS Consumer Price Index | **July 2026** | Monthly | NBS microdata |
| NBS Selected Food Price Watch | **May 2026** | Monthly | NBS microdata |
| NBS PMS (petrol) Price Watch | **May 2026** | Monthly | NBS microdata |
| NBS AGO (diesel) Price Watch | **May 2026** | Monthly | NBS microdata |
| NBS Transport Fare Watch | **May 2026** | Monthly | NBS microdata |
| NBS LPG (cooking gas) Price Watch | **April 2026** | Monthly | NBS microdata |

Every date above was verified by opening the file, not by reading its filename.

### CBN detail

The snapshot `cbn_api_GetAllNFEM_Rates_snapshot_20260913T120305Z.json` holds 445 records spanning
2024-12-02 to 2026-09-11. Within the project window 2025-01-01 to 2026-09-13:

| Measure | Value |
|---|---|
| Physical rows | 425 |
| `ACTIVE` | 419 |
| `EXACT_DUPLICATE` | 6 |
| `DATE_CONFLICT` | 0 |
| Weekdays with no observation | 24 |
| Earliest / latest observation | 2025-01-02 / 2026-09-11 |

20 records dated 2024-12-02 to 2024-12-31 sit **before** the window start and are deliberately out of
scope. The cutoff 2026-09-13 falls on a Sunday, so no trading day is lost at the boundary. On
2026-09-13 the live CBN API and the exchange-rate page were both byte-identical to the stored
snapshots, confirming CBN had published nothing newer.

### NERC detail

Monthly MYTO orders for **11 DisCos** — Abuja, Benin, Eko, Enugu, Ibadan, Ikeja, Jos, Kaduna, Kano,
Port Harcourt, Yola — complete for June, July, August and September 2026 (44 orders added in this
extension). All are image-only scans with no text layer, so D-12 applies: OCR plus individual human
validation before any tariff is used.

---

## Releases due before the cutoff but not published — 11

These were scheduled on NBS's own Data Release Calendar with a due date on or before 2026-09-13, and
are absent from the relevant microdata catalogue. They are genuinely missing, not merely early.

| Dataset | Reference month | Scheduled release | Catalogue |
|---|---|---|---|
| LPG (cooking gas) | May 2026 | 2026-06-26 | 160 |
| PMS (petrol) | June 2026 | 2026-07-22 | 157 |
| AGO (diesel) | June 2026 | 2026-07-22 | 158 |
| LPG (cooking gas) | June 2026 | 2026-07-27 | 160 |
| Selected food | June 2026 | 2026-07-29 | 162 |
| Transport fare | June 2026 | 2026-07-29 | 161 |
| PMS (petrol) | July 2026 | 2026-08-22 | 157 |
| AGO (diesel) | July 2026 | 2026-08-22 | 158 |
| LPG (cooking gas) | July 2026 | 2026-08-27 | 160 |
| Selected food | July 2026 | 2026-08-29 | 162 |
| Transport fare | July 2026 | 2026-08-29 | 161 |

**None of these is filled, interpolated or carried forward.** Absence is recorded as absence.

CPI is the exception: its June 2026 and July 2026 reports were both due *and* published, and both were
acquired in this extension.

---

## Not yet due at the cutoff — not missing

August 2026 reference months for all six NBS families were scheduled **after** 2026-09-13 and are
therefore correctly absent. They must not be counted as gaps.

| Dataset | Reference month | Scheduled release | Status at cutoff |
|---|---|---|---|
| CPI | August 2026 | 2026-09-15 | Not yet due |
| PMS (petrol) | August 2026 | 2026-09-22 | Not yet due |
| AGO (diesel) | August 2026 | 2026-09-22 | Not yet due |
| LPG (cooking gas) | August 2026 | 2026-09-28 | Not yet due |
| Selected food | August 2026 | 2026-09-29 | Not yet due |
| Transport fare | August 2026 | 2026-09-29 | Not yet due |

> **Rule.** An unpublished release is only called *missing* once its scheduled release date has passed.
> Before that it is *not yet due*. Conflating the two would overstate the gap count by six.

Release dates were read from the official NBS Data Release Calendar, embedded as a JSON event array in
the homepage HTML at `https://nigerianstat.gov.ng/`.

---

## Pre-existing gaps carried forward

Recorded at the original acquisition and still open; unchanged by this extension.

| Dataset | Gap | Note |
|---|---|---|
| NBS CPI | January 2025 | Not released as a standalone report |
| NERC MYTO | March 2025 | No order found for any DisCo |
| NERC MYTO | Aba Power (APLE) | No MYTO order since February 2025; the DisCo is absent from every month in this extension |
| NBS CPI | March 2026 | File is legacy `.xls`; `xlrd` not installed, so unread at profiling time |

---

## Where to look for NBS releases

**Use `microdata.nigerianstat.gov.ng`. Do not rely on the main site's e-library.**

Current NBS releases live in the NADA catalogue:

| Catalogue | Dataset |
|---|---|
| 154 | Consumer Price Index |
| 157 | PMS (petrol) Price Watch |
| 158 | AGO (diesel) Price Watch |
| 160 | LPG (cooking gas) Price Watch |
| 161 | Transport Fare Watch |
| 162 | Selected Food Price Watch |

- Catalogue page: `https://microdata.nigerianstat.gov.ng/index.php/catalog/<catalog_id>`
- Download: `https://microdata.nigerianstat.gov.ng/index.php/catalog/<catalog_id>/download/<resource_id>`
- The filename comes from the `Content-Disposition` header, not from the URL.

**Why this is written down.** On 2026-09-13 the main e-library at `nigerianstat.gov.ng/elibrary`
returned 1,695 entries whose newest item was *Foreign Trade in Goods Statistics Q3 2024*, published
2024-12-06. It listed none of the 2025–2026 files this project already holds. A search there returns a
confident false negative for every dataset in this project. The microdata catalogue is also the host
recorded in `docs/acquisition/source_inventory.csv` for every NBS file ever acquired here.

NERC orders are at `https://nerc.gov.ng/`, with PDFs under
`https://nerc.gov.ng/wp-content/uploads/YYYY/MM/`. The upload month often lags the effective month —
the June 2026 orders sit under `/2026/07/`, and the August 2026 orders under `/2026/09/` — so the path
date must never be read as the tariff's effective date.

---

## Raw file counts at this cutoff

| Measure | Count |
|---|---|
| Original acquisition (manifest `transfer_verification.csv`) | 296 |
| Added in the 2026-09-13 extension (`extension_2026-09-13_verification.csv`) | 46 |
| **Total acquired source files** | **342** |

The 46 new files are 44 NERC MYTO PDFs and 2 NBS CPI archives. Every one has a recorded SHA-256. All
296 original files were re-hashed after the extension and are unchanged; nothing under `data/raw/` was
modified or overwritten, only added to.

`data/raw/` holds 343 files — the extra is `data/raw/README.md`, which is project-authored
documentation, not an acquired source.
