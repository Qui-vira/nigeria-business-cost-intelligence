# Excel Dashboard — Build and Validation Report

**Deliverable:** `outputs/dashboards/NBCI_Cost_Dashboard.xlsx` (521.6 KB, Microsoft Excel-saved)
**SHA-256:** `3a8b9f33b4b3af8baae1386f6dc2c7e87b38ba99fecbb6cb353a245f4d841ada`
**Built by:** [`src/dashboards/build_excel_dashboard.py`](../../src/dashboards/build_excel_dashboard.py)
**Validated by:** [`src/dashboards/validate_excel_dashboard.py`](../../src/dashboards/validate_excel_dashboard.py)
**QA'd in:** [`src/dashboards/qa_msexcel_compatibility.py`](../../src/dashboards/qa_msexcel_compatibility.py)
**Result: 70 of 70 checks pass** — 45 structural/reconciliation + 25 Microsoft Excel compatibility
**Status:** built, validated and confirmed in genuine Microsoft Excel 16.0. Nothing committed.

---

## 1. What was built

Ten sheets — seven dashboard, three data.

| Sheet | Contents |
|---|---|
| **Executive Overview** | 5 KPI cards, window-change table with data bars, bar chart |
| **Fuel Costs** | 4 KPI cards, PivotTable + PivotChart + slicer, rank-stability and coverage notices |
| **Transport Costs** | 4 KPI cards, PivotTable + PivotChart + slicer, mode / air / freight notices |
| **Geographic Differences** | 4 KPI cards, location-value table, local-mobility persistence, zone food premium |
| **Decision Signals** | 4 KPI cards, flag-level table, EXTREME flag PivotTable + chart + slicer, self-generation table |
| **Business Archetypes** | Exposure sensitivity table + all six archetypes with boundary panels |
| **Methodology** | 14 sections covering every required topic |
| `Data_Panel` | `tblPanel`, 8,177 rows |
| `Data_Medians` | `tblMedFuel` 66, `tblMedTransport` 85, `tblMedCPI` 70 |
| `Data_Evidence` | 18 committed evidence tables + `tblKPIRegister` |

**Objects:** 3 PivotTables · 6 slicer parts · 4 charts · 30 structured tables · 7 conditional-format
ranges · 21 KPI cards, **all formula-driven**.

**Self-contained.** No PostgreSQL, no add-in, no network, no external links. Every figure is embedded.

---

## 2. Two design decisions worth knowing

**Medians are pre-aggregated.** Excel PivotTables cannot compute a median — they offer only
Sum/Count/Average/Max/Min/StdDev/Var. Every headline in the committed analysis is a **median across
37 jurisdictions**, so a pivot using Average would have silently printed a *different number from the
published evidence*. The builder pre-computes medians into family-scoped tables and the pivots
aggregate a single row each, so the figures reconcile exactly.

**CPI index codes are excluded from the workbook's data layer.** Rule G2 forbids comparing CPI index
levels across jurisdictions. Leaving them in the pivot source would let any user break that rule by
dragging a field, so the two INDEX metric codes are dropped: **9,435 database rows become 8,177 in the
workbook**. The full 9,435 remain in the database. Stated on the Methodology sheet.

---

## 3. Analytical rules enforced structurally, not by convention

| Rule | How the workbook enforces it |
|---|---|
| **G2** CPI index levels never compared | The two INDEX codes are absent from `tblPanel` — the rule cannot be broken by dragging a field |
| **G6** transport modes never combined | Each pivot reads a **family-scoped source**, and the transport pivot has **grand totals switched off** — no "all modes" figure can be produced at all |
| **G7** air is not local mobility | Local-mobility persistence tables contain okada, intracity bus and water only; air and intercity bus are labelled inter-regional |
| **G8** LPG cylinder sizes never averaged | Separate metric codes, separate series, no cross-size total |
| **G9** rank stability | The location table prints `NOT NAMED — order unstable over time` for all five unstable metrics, with grey italic conditional formatting; validator confirms **0 violations** |
| **G4** NERC fixed reference | Self-generation compared against the **fixed July 2025 Band A ₦209.50/kWh** benchmark, with the ten-month gap and the efficiency assumption stated on-page |
| **G12** no composite index | No cost is summed or weighted against another anywhere |
| **G13** flags are descriptive | ELEVATED/EXTREME defined on-page as historical flags, explicitly *not* action triggers |
| Pharmacy boundary | Archetype panel states profitability **cannot be calculated or inferred** |

---

## 4. Validation — 45 of 45

Three independent layers. The workbook is written through a COM automation bridge, so the
automation's own success messages are not evidence; the file itself was inspected.

### Layer A — raw OOXML (8 checks)
Unzips the `.xlsx` and reads the XML parts directly, independent of any spreadsheet application.

| Check | Result |
|---|---|
| PivotTable parts present | 3 pivotTable parts, 6 cache parts |
| Slicer parts present | 6 slicer parts |
| Chart parts present | 4 chart parts |
| Structured table parts present | 30 table parts |
| No external link parts | 0 |
| No absolute local paths anywhere | clean |
| No invalid numeric literals (`#QNAN`/`#IND`/`#INF`) | clean |
| Every chart part contains a data series | 4/4 |
| Every PivotCache declares a worksheet source | 3/3 |

### Layer B — openpyxl, a third-party reader (13 checks)
Proves the file is readable by something other than the engine that wrote it.

All 7 dashboard sheets and 3 data sheets present · 29 ListObjects readable · **21 formula cells**
(KPI cards are formulas, not hardcoded) · **no error literals** anywhere · the seven critical tables
exist · `tblPanel` holds exactly 8,177 rows.

### Layer C — recalculation and reconciliation (24 checks)
Opens the workbook, forces a **full rebuild recalculation**, then reads each KPI at the address
recorded in `tblKPIRegister` and compares it with the committed evidence CSV.

| KPI | Workbook | Evidence | Source |
|---|---:|---:|---|
| Diesel, trough → latest | 1.5816 | 1.5816 | `f31` |
| Petrol, trough → latest | 0.6535 | 0.6535 | `f31` |
| Diesel spread, 2026-04 | 638.66 | 638.66 | `d8` |
| Petrol spread, 2026-04 | 195.16 | 195.16 | `d8` |
| Petrol dearest / cheapest | 1.1400 | 1.1400 | `d8` |
| Okada rose while petrol fell | 1.0000 | 1.0000 | `f29` |
| Okada fare growth vs CPI | 35.6362 | 35.6362 | `d6` |
| Water transport, dearest/cheapest | 6.9100 | 6.9100 | `d8` |
| Rank-stable metrics | 4.0000 | 4.0000 | `f40` |
| Diesel EXTREME level | 0.5204 | 0.5204 | `d1` |
| Diesel ELEVATED level | 0.2603 | 0.2603 | `d1` |
| Self-gen vs reference tariff | 5.1700 | 5.1700 | `d3` |

**12 of 12 reconcile exactly.** Also verified: no external data links · all 21 registered cards
compute to a value · all 3 PivotTables have valid sources with data · transport grand totals OFF ·
3/3 slicer caches connected to a PivotTable · 4 charts, 0 empty · G9 zero violations.

---

## 5. Two defects the validation caught and the build fixed

**Invalid `#QNAN` literals — 20 of them.** NaN values were reaching the sheet as the literal
`1.#QNAN`, which is **not valid OOXML**. `DataFrame.where(notna, None)` does not work on float
columns — a float column cannot hold `None`, so NaN survives. openpyxl refused to open the file.
Fixed by sanitising values after `.tolist()`. This is exactly why the file is validated rather than
the build log.

**A false positive in my own check.** The absolute-path scan matched `p:/` inside `http://`. The
pattern now requires a drive letter not preceded by an alphanumeric and followed by a single
separator. The file was always clean; the check was wrong.

---

## 6. Microsoft Excel 16.0 compatibility QA — 25 of 25

**The ProgID hijack was bypassed.** WPS owns both `Excel.Application` *and* the genuine Excel
coclass `{00024500-0000-0000-C000-000000000046}` — `Dispatch` and `DispatchEx` both reach WPS, which
reports `Name='Microsoft Excel', Version=12.0`. The route that works: **launch `EXCEL.EXE` with the
document, then bind the document moniker from the Running Object Table.** No ProgID or CLSID lookup
is involved, so the hijack does not apply. That yields the real application — `Version=16.0`,
`Path=C:\Program Files\Microsoft Office
oot\Office16`.

| Check | Result |
|---|---|
| Attached to genuine Microsoft Excel | Version 16.0, Office16 path |
| Opens **without repair** | `Workbook.Saved=True` on open; no `[Repaired]`/recovered copy created |
| All 3 PivotTables load | 3 |
| All 3 slicer caches load | 3 |
| All 4 charts load | 4 |
| No formula errors after `CalculateFullRebuild` | 21 KPI values, 0 blank, 0 errors |
| **Slicer responds and restores** | 9 items; PivotTable rows 11 → 10 → 11 |
| Saved by Microsoft Excel | `Workbook.Save()` |
| Parts preserved through the Excel save | pivots 3→3, slicers 6→6, charts 4→4, tables 30→30 |
| No external links after the Excel save | 0 |
| No invalid numeric literals after the Excel save | 0 |
| **Reopened without repair after save** | `Workbook.Saved=True` |
| Pivots, slicers, charts survive the round trip | 3 / 3 / 4 |

**One issue found and corrected.** Microsoft Excel's save stamps the workbook's own folder into
`xl/workbook.xml` as the `x15ac:absPath` extension — an absolute local path in an artefact meant to
be portable. It is metadata used to resolve relative links, **not a data dependency**. The QA now
strips it and **re-opens the stripped file in Microsoft Excel to prove Excel is content without it**
(files produced by other tools never carry it). Note that *any* future user save will re-stamp their
own path: that is inherent Excel behaviour for every workbook, not a defect in this one.

## 7. Remaining limitations of this validation

1. **Rendering was not inspected visually.** Automation confirms the objects load, recalculate and
   respond — a slicer click genuinely changed the PivotTable row count — but nobody has *looked* at
   the workbook. Fonts, colours, chart proportions and slicer styling are unverified by eye.
2. **openpyxl drops three extensions on read** — slicer list, a conditional-formatting extension and
   one unknown extension. These are warnings from *openpyxl's* reader, not defects in the file; the
   corresponding parts are present in the OOXML (Layer A).
3. **Recalculation now verified in both engines.** Formulas were recalculated by WPS during the
   45-check validation and again by Microsoft Excel 16.0 during the compatibility QA, with no errors
   in either.
4. **The extract is a manual snapshot**, per the specification's decided cadence. The generation
   timestamp is printed on the Executive Overview and the Methodology sheet.

---

## 8. Files produced

| Path | Size |
|---|---|
| `outputs/dashboards/NBCI_Cost_Dashboard.xlsx` | 521.6 KB |
| `outputs/dashboards/extracts/extract_manifest.csv` | 314 B — provenance record, committed |
| `outputs/dashboards/extracts/ext_state_cost_panel.csv` | 1,083 KB — **gitignored**, regenerable; its rows are already embedded in the workbook |
| `outputs/dashboards/extracts/ext_metric_medians.csv` | 41 KB — **gitignored**, regenerable |
| `src/dashboards/build_excel_dashboard.py` | builder |
| `src/dashboards/validate_excel_dashboard.py` | validator |
| `docs/dashboards/excel_workbook_validation.md` | this report |

Nothing in `data/`, `sql/` or the database was modified — the extract step reads
the mart layer through the read-only connection helper.

---

*Stop point: the Excel workbook is built and validated. Power BI, Tableau and Cognos remain
unstarted, per the specification's build order.*
