# What The Data Actually Looks Like

A plain-English tour of the 296 source files, written before any cleaning has started.
Nothing here is a solution — this is just an honest description of what we are dealing with.

> **Scope note (added 2026-09-13).** This is a Phase 2 profiling record of the **original 296-file
> corpus**, and its figures are kept as the historical measurement. The project was later extended to
> `acquisition_cutoff_date = 2026-09-13`, adding **46 files** (44 NERC MYTO orders, 2 NBS CPI
> archives) that have **not** been profiled. For current coverage and current CBN figures see
> [`docs/acquisition/source_coverage_2026-09-13.md`](../acquisition/source_coverage_2026-09-13.md).

**A few words explained up front**, because they are used throughout:

- **Row / column** — a spreadsheet line, and a spreadsheet field. A *row* is usually one thing you
  measured; a *column* is usually one fact about it.
- **Header row** — the line that names the columns. Usually the first line, but in this data it is
  often not.
- **Wide vs long** — see §3.
- **Zone** — Nigeria's 6 *geopolitical zones* (North Central, North East, North West, South East,
  South South, South West). Each zone groups several states. Zone-level data is **less detailed**
  than state-level.
- **DisCo** — an electricity **Dis**tribution **Co**mpany. There are 11 main ones. Their territories
  do **not** line up neatly with the 36 states.
- **OCR** — Optical Character Recognition: software that reads text out of a *picture* of a page.
  Needed when a PDF is a scan rather than real text.
- **CPI** — Consumer Price Index, the standard measure of how prices change over time.

---

## 1. What each dataset contains

| Dataset | Files | What it measures |
|---|---|---|
| **Food Price Watch** | 18 | Average retail prices of ~42 food items (rice, yam, eggs, vegetable oil…) |
| **Petrol (PMS) Price Watch** | 22 | Average price per litre of petrol |
| **Diesel (AGO) Price Watch** | 22 | Average price per litre of diesel |
| **Cooking Gas (LPG) Price Watch** | 20 | Average price to refill a 5 kg and a 12.5 kg gas cylinder |
| **Transport Fare Watch** | 14 | Typical fares: air, intercity bus, city bus, okada, boat |
| **Consumer Price Index (CPI)** | 22 | Official inflation — how fast prices are rising overall |
| **CBN exchange rate** | 5 | The daily official naira-to-dollar rate |
| **NERC electricity orders** | 173 | Approved electricity tariffs, one document per DisCo per month |

Together these cover most of what it costs to run a business in Nigeria: stock, fuel, power,
transport, and the exchange rate that drives the price of anything imported.

---

## 2. What one row represents

This is the most important question to ask of any dataset, and **the answer is different in every one.**

| Dataset | One row is… |
|---|---|
| **Food** | one **food item**, with its price averaged across a zone or nationally |
| **Petrol** | one **state**, with its average petrol price |
| **Diesel** | one **state *or* one zone** — mixed together in the same column |
| **Cooking gas** | one **state or zone**, for two cylinder sizes side by side |
| **Transport** (`State Transport` sheet) | one **state**, with five different fares across the columns |
| **Transport** (month sheet) | one **transport mode**, then further down, one **zone** |
| **CPI** (`Table1`–`Table4`) | one **month** |
| **CPI** (`Table-5`) | one **state** |
| **CBN** | one **trading day**, for the whole country |
| **NERC** | not a row at all — each file is a **legal document** about one DisCo for one month |

Notice that only petrol, transport and CPI `Table-5` give you a clean "one row = one state" shape.
That matters, because the project question is about differences **between states**.

---

## 3. Which datasets are wide, and which are long

**Wide** means a period or category is spread across the *columns*. Example — this is wide:

| State | Jan 2025 | Dec 2025 | Jan 2026 |
|---|---|---|---|
| Abia | 1308 | 1032 | 1054 |

**Long** (sometimes called "tidy") means each row carries its own period, and there is one value column:

| State | Month | Price |
|---|---|---|
| Abia | 2025-01 | 1308 |
| Abia | 2025-12 | 1032 |

Long is what you want for analysis — it is easy to filter, group and chart. Wide is what you usually get.

| Dataset | Shape |
|---|---|
| Food, Petrol, Diesel, Cooking gas, Transport | **Wide** — the month is the column heading |
| CPI | **Wide**, and with two stacked heading rows |
| CBN exchange rate | **Long** — already the right shape |
| NERC | Not a table at all |

So **seven of the eight datasets are wide**, and only the CBN file arrives in the shape we eventually want.

---

## 4. Which datasets look easiest to clean

**1. CBN exchange rate — clearly the easiest.** It is already long. Every row is a date and a set of
numbers. The five main rate columns have no gaps at all. There are only two things to notice: six days
appear twice (as exact copies, so nothing conflicts), and the "turnover" and "number of deals" columns
are mostly empty.

**2. Transport — easiest of the NBS spreadsheets.** The `State Transport` sheet is genuinely
one row per state, the header is always on row 1, and it is the same in all 17 months. Its flaws are
mild: very long column names, and a `Grand Total` row at the bottom.

**3. Food — structurally stable, but limited.** Header always on row 1, no totals mixed into the data.
The catch is not messiness, it is **coverage**: the spreadsheets only go down to zone level.

---

## 5. Which datasets look hardest to clean

**1. NERC electricity — by a wide margin.** 134 of the 173 documents are **scans**: pictures of pages
with no readable text inside. Every single 2026 order is a scan. Before we can read one tariff number
from those, they have to go through OCR. And some of the files that *do* have text turn out to be
somebody else's OCR output, with mistakes already baked in — one file literally contains
`IN THE MAilER OF` instead of `IN THE MATTER OF`. On top of that, these are legal documents, so the
effective date is written in a sentence rather than stored in a field.

**2. CPI — the most complicated spreadsheet.** Ten different sheets per workbook, headers on row 2, 3
or 4 depending on the sheet, and column counts ranging from 12 to 65. It uses **two stacked header
rows**, so the word `Food` appears six times across the top and means a different period each time.
There are also 96,857 Excel `#REF!` error cells — although, reassuringly, **every single one** sits in
one behind-the-scenes rebasing sheet, and the presentation tables are completely clean. (An earlier
count of 69,411 "across 5 workbooks" was corrected when the whole corpus was measured sheet by sheet.)

**3. Cooking gas — deceptively messy.** Each sheet is really **three tables stacked on top of each
other**, plus a **fourth sitting beside it**: the 5 kg table on the left, the 12.5 kg table on the
right, then a national average row, then "states with the highest prices" and "states with the lowest
prices" blocks underneath. And in 2026 the columns quietly shifted two places to the right.

**4. Diesel — one specific trap.** The column holding the geography has **no name at all**, and it
mixes zones and states together in the same list.

---

## 6. The biggest structural problems discovered

**1. The datasets do not agree on geography — and the project question is about states.**
Petrol and transport give clean state data. CPI gives state data in one sheet only. Diesel and cooking
gas give state data tangled with zone data. But **food gives no state data at all** — only zones — and
the exchange rate is a single national number.

On food this is a hard ceiling, not a workload problem. The report PDFs were checked across four
months: every one is organised as National + the six zones, with no state section. State names appear
only in the "highest / lowest price per item" summary — the same table that's already in the
spreadsheet. NBS collects prices in all 36 states but does not publish them state by state. So
state-level food prices are **unavailable from this source at any effort level**. NERC is organised by DisCo, and DisCo areas do not match
state boundaries. So "cost of doing business by state" cannot be assembled at the same level of detail
from every source.

**2. NBS itself warns against comparing states on CPI.** Printed under CPI `Table-5`:
> *"Indices may not be used for inter-state price comparison because market baskets differ state to state."*

That is the statistical agency saying the state indices measure different shopping baskets, so a higher
index in one state does **not** mean it is more expensive. We can compare how fast prices *changed* in
each state; we cannot rank states by price level using this table. This will shape what the project can
honestly claim.

**3. Totals are hidden inside the data.** In every petrol, diesel and cooking gas sheet, rows called
`AVERAGE`, `NATIONAL` or `Grand Total` sit in the same column as the states. If you average the column
without removing them, you count the national figure as if it were another state.

**4. The header row moves.** Row 1 in food and transport, row 2 in cooking gas, rows 2–4 in CPI, and in
petrol and diesel it jumps between row 1 and **row 15 or 16** depending on the month, because later
releases put a title and a paragraph of commentary above the table.

**5. The month is in the column heading, not in a column.** For five of the six NBS datasets, the only
place the period is recorded is the header text, like `Average of Apr-25`.

**6. State names are written inconsistently** — `ABIA` in transport, `Abia` in petrol, and one cooking
gas cell reads `Kebbi/Nasarawa` because two states tied.

**7. Some labels are simply wrong** — and we left them exactly as NBS published them:
a January 2026 petrol file named 2025, an October 2025 petrol sheet titled "AUGUST 2025", and two food
files whose sheet is named "Selected Food Dec 2024". In each case we checked the actual numbers and
confirmed the data is fine; only the label lies.

**8. Two kinds of "missing" appear in the same file.** In the CBN data one column is blank where data is
absent, while another contains a literal `0`. A zero is a measurement; a blank is the absence of one.
Treating them the same would be a real error.

---

## 7. Concepts worth understanding before cleaning begins

1. **Wide vs long, and reshaping between them.** Most of this work is turning wide tables into long
   ones. The general term is *unpivoting* or *melting*.
2. **What a "primary key" is** — the combination of columns that uniquely identifies a row
   (here it will usually be *state + month + product*). Once you know your key, duplicates and gaps
   become obvious.
3. **Header rows vs data rows**, and why a file with a title above the table breaks naive loaders.
4. **Multi-level (stacked) headers** and why two header rows have to be combined into one before the
   table makes sense.
5. **The difference between zero, blank, and "not applicable."** They look similar and mean very
   different things.
6. **Aggregates hidden in detail rows** — why `NATIONAL` sitting among the states is dangerous.
7. **Levels of geography** — state, zone, DisCo, national — and why you can always roll detail *up*
   but can never split an average back *down*.
8. **Index numbers vs prices.** A price is naira. An index is a number relative to a base year
   (here 2024 = 100). Indexes describe *change*, and different indexes are not always comparable —
   which is exactly what the NBS warning is about.
9. **Text vs scanned PDFs, and what OCR can and cannot do.** OCR guesses; it makes mistakes on digits,
   which matters a lot when the digits are tariffs.
10. **Provenance and reproducibility** — keeping the raw layer untouched and writing down every
    decision, so any number can be traced back to the official file it came from.

---

*Profiling only. No values were changed, no files were modified, no ZIP was permanently extracted,
and no PDF was OCR'd.*
