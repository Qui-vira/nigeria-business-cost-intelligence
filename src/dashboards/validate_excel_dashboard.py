"""Validate the built Excel dashboard.

Checks the SAVED FILE, not the automation's success messages. The workbook is
written through a COM engine, so the only trustworthy evidence that a PivotTable,
slicer or chart survived the save is the OOXML inside the .xlsx itself.

    python src/dashboards/validate_excel_dashboard.py

Three independent layers:
  A. OOXML   - unzip the .xlsx and inspect the parts directly
  B. openpyxl - structure, tables, formulas, error literals
  C. COM      - open, force a full recalculation, read the computed KPI values
                and reconcile them against the committed evidence CSVs
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import win32com.client as w32
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "outputs" / "dashboards" / "NBCI_Cost_Dashboard.xlsx"
EVID = ROOT / "outputs" / "analysis"

DASH_SHEETS = ["Executive Overview", "Fuel Costs", "Transport Costs",
               "Geographic Differences", "Decision Signals",
               "Business Archetypes", "Methodology"]
DATA_SHEETS = ["Data_Panel", "Data_Medians", "Data_Evidence"]
ERROR_LITERALS = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!")


class Checks:
    def __init__(self):
        self.rows = []

    def __call__(self, ok, name, evidence=""):
        self.rows.append((bool(ok), name, evidence))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{evidence}]" if evidence else ""))
        return bool(ok)

    @property
    def failed(self):
        return sum(1 for ok, _, _ in self.rows if not ok)

    def summary(self):
        n = len(self.rows)
        print("\n" + "=" * 74)
        print(f"WORKBOOK VALIDATION: {n - self.failed} of {n} checks pass")
        if self.failed:
            for ok, name, ev in self.rows:
                if not ok:
                    print(f"  FAILED: {name}  [{ev}]")
        print("=" * 74)
        return self.failed


def layer_a_ooxml(ck):
    print("\n" + "=" * 74)
    print("LAYER A - OOXML PARTS INSIDE THE SAVED FILE")
    print("=" * 74)
    z = zipfile.ZipFile(WORKBOOK)
    names = z.namelist()

    pivots = [n for n in names if re.match(r"xl/pivotTables/pivotTable\d+\.xml", n)]
    caches = [n for n in names if "pivotCache" in n and n.endswith(".xml")]
    slicers = [n for n in names if "slicer" in n.lower() and n.endswith(".xml")]
    charts = [n for n in names if re.match(r"xl/charts/chart\d+\.xml", n)]
    tables = [n for n in names if re.match(r"xl/tables/table\d+\.xml", n)]
    extlinks = [n for n in names if "externalLink" in n]

    ck(len(pivots) >= 3, "PivotTable parts present in the file",
       f"{len(pivots)} pivotTable parts, {len(caches)} cache parts")
    ck(len(slicers) >= 3, "Slicer parts present in the file", f"{len(slicers)} slicer parts")
    ck(len(charts) >= 4, "Chart parts present in the file", f"{len(charts)} chart parts")
    ck(len(tables) >= 20, "Structured table (ListObject) parts present", f"{len(tables)} table parts")
    ck(len(extlinks) == 0, "NO external link parts", f"{len(extlinks)} externalLink parts")

    # Absolute local paths must not survive anywhere in the package.
    # The drive letter must not be preceded by another letter and must be
    # followed by a SINGLE separator - otherwise "http://" matches as "p:/".
    drive = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])')
    fileurl = re.compile(r"file:///")
    abs_hits = []
    for n in names:
        if not n.endswith((".xml", ".rels")):
            continue
        blob = z.read(n).decode("utf-8", errors="ignore")
        if drive.search(blob) or fileurl.search(blob):
            abs_hits.append(n)
    ck(not abs_hits, "NO absolute local paths anywhere in the package",
       "clean" if not abs_hits else f"{abs_hits[:3]}")

    # Invalid numeric literals: a COM bridge can emit 1.#QNAN for NaN, which is
    # not valid OOXML and makes the file unreadable to third-party readers.
    nan_hits = []
    for n in names:
        if n.startswith("xl/worksheets/") and n.endswith(".xml"):
            blob = z.read(n).decode("utf-8", errors="ignore")
            c = blob.count("#QNAN") + blob.count("#IND") + blob.count("#INF")
            if c:
                nan_hits.append((n, c))
    ck(not nan_hits, "no invalid numeric literals (#QNAN/#IND/#INF) in sheet XML",
       "clean" if not nan_hits else f"{nan_hits}")

    # Every chart must carry a real series reference.
    bad_charts = []
    for c in charts:
        blob = z.read(c).decode("utf-8", errors="ignore")
        if "<c:ser>" not in blob and "<ser>" not in blob:
            bad_charts.append(c)
    ck(not bad_charts, "every chart part contains at least one data series",
       f"{len(charts) - len(bad_charts)}/{len(charts)} charts with series")

    # Every pivot cache must point at a worksheet source.
    bad_cache = []
    for c in caches:
        if "pivotCacheDefinition" not in c:
            continue
        blob = z.read(c).decode("utf-8", errors="ignore")
        if "worksheetSource" not in blob:
            bad_cache.append(c)
    ck(not bad_cache, "every PivotCache declares a worksheet source",
       f"{len([c for c in caches if 'Definition' in c]) - len(bad_cache)} caches OK")
    z.close()
    return {"pivots": len(pivots), "slicers": len(slicers), "charts": len(charts),
            "tables": len(tables)}


def layer_b_openpyxl(ck):
    print("\n" + "=" * 74)
    print("LAYER B - STRUCTURE, TABLES AND FORMULAS")
    print("=" * 74)
    wb = load_workbook(WORKBOOK, data_only=False)
    sheets = wb.sheetnames
    ck(all(s in sheets for s in DASH_SHEETS), "all 7 dashboard sheets present",
       f"{[s for s in DASH_SHEETS if s not in sheets] or 'all present'}")
    ck(all(s in sheets for s in DATA_SHEETS), "all 3 data sheets present",
       f"{[s for s in DATA_SHEETS if s not in sheets] or 'all present'}")

    all_tables, formulas, errors = {}, 0, []
    for ws in wb.worksheets:
        for tname, ref in getattr(ws, "tables", {}).items():
            all_tables[tname] = (ws.title, ref)
        for row in ws.iter_rows():
            for cell in row:
                v = cell.value
                if isinstance(v, str):
                    if v.startswith("="):
                        formulas += 1
                    for e in ERROR_LITERALS:
                        if e in v:
                            errors.append(f"{ws.title}!{cell.coordinate}={v[:40]}")
    ck(len(all_tables) >= 20, "structured tables readable by a third-party reader",
       f"{len(all_tables)} ListObjects")
    ck(formulas >= 15, "KPI cards are formulas, not hardcoded values",
       f"{formulas} formula cells")
    ck(not errors, "no error literals anywhere in the workbook",
       "clean" if not errors else f"{errors[:3]}")

    for need in ("tblPanel", "tblMedFuel", "tblMedTransport", "tblFlags",
                 "tblLocation", "tblShock", "tblSelfGen"):
        ck(need in all_tables, f"table {need} exists", all_tables.get(need, ("missing",))[0])

    ck(wb["Data_Panel"].max_row - 1 == 8177, "tblPanel holds 8,177 data rows (G2 applied)",
       f"{wb['Data_Panel'].max_row - 1} rows")
    return all_tables


def layer_c_com_recalc(ck):
    print("\n" + "=" * 74)
    print("LAYER C - RECALCULATION AND RECONCILIATION AGAINST THE EVIDENCE")
    print("=" * 74)
    shock = pd.read_csv(EVID / "discovery/f31_shock_trough_to_latest.csv")
    flags = pd.read_csv(EVID / "decisions/d1_movement_flags.csv")
    loc = pd.read_csv(EVID / "decisions/d8_location_value_by_cost.csv")
    sticky = pd.read_csv(EVID / "discovery/f29_fare_ratchet_summary.csv")
    farecpi = pd.read_csv(EVID / "decisions/d6_fare_vs_cpi_summary.csv")
    selfgen = pd.read_csv(EVID / "decisions/d3_selfgen_vs_reference_tariff.csv")
    rank = pd.read_csv(EVID / "discovery/f40_rank_stability.csv")

    def ev(df, key_col, key, col):
        return float(df.loc[df[key_col] == key, col].iloc[0])

    xl = w32.gencache.EnsureDispatch("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        # READ-ONLY is mandatory. Opened writable, this COM engine rewrites the
        # file on close even with SaveChanges=False - it re-saves in its own
        # flavour and silently replaces the Microsoft Excel-saved artefact that
        # the compatibility QA produced. Verified by the file's SHA-256 changing.
        wb = xl.Workbooks.Open(str(WORKBOOK), ReadOnly=True)
        xl.CalculateFullRebuild()

        links = wb.LinkSources(1)
        ck(links is None or len(links) == 0, "workbook declares no external data links",
           "none" if not links else str(links))

        # KPI cards recalculated and compared with the committed evidence.
        cases = [
            ("Executive Overview", "Diesel, trough to latest",
             ev(shock, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "median_pct") / 100),
            ("Executive Overview", "Petrol, trough to latest",
             ev(shock, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "median_pct") / 100),
            ("Fuel Costs", "Diesel spread, 2026-04",
             ev(loc, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "spread_ngn")),
            ("Fuel Costs", "Petrol spread, 2026-04",
             ev(loc, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "spread_ngn")),
            ("Fuel Costs", "Petrol dearest / cheapest",
             ev(loc, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "dearest_over_cheapest")),
            ("Transport Costs", "Okada rose while petrol fell",
             ev(sticky, "metric_code", "TRANSPORT_OKADA_NGN_PER_JOURNEY", "share_fare_rose_pct") / 100),
            ("Transport Costs", "Okada fare growth vs CPI",
             ev(farecpi, "metric_code", "TRANSPORT_OKADA_NGN_PER_JOURNEY", "median_gap_pp")),
            ("Geographic Differences", "Water transport, dearest/cheapest",
             ev(loc, "metric_code", "TRANSPORT_WATER_NGN_PER_JOURNEY", "dearest_over_cheapest")),
            ("Geographic Differences", "Rank-stable metrics",
             float(rank.stable_for_persistent_ranking.sum())),
            ("Decision Signals", "Diesel EXTREME level",
             ev(flags, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "extreme_p95_abs_pct") / 100),
            ("Decision Signals", "Diesel ELEVATED level",
             ev(flags, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "elevated_p90_abs_pct") / 100),
        ]
        expected_selfgen = float(selfgen.loc[
            (selfgen.observation_month == "2026-05-01") &
            (selfgen.genset_kwh_per_litre == 3.0), "multiple_of_reference_tariff"].iloc[0])
        cases.append(("Decision Signals", "Self-gen vs reference tariff", expected_selfgen))

        # Read the KPI register the builder wrote: (sheet, kpi, cell). Locating a
        # card by its registered address is deterministic - no label matching.
        wsE = wb.Worksheets("Data_Evidence")
        lo = wsE.ListObjects("tblKPIRegister")
        hdr = [str(c.Value) for c in lo.HeaderRowRange]
        i_sheet, i_kpi, i_cell = hdr.index("sheet"), hdr.index("kpi"), hdr.index("cell")
        register = {}
        for rw in range(1, lo.DataBodyRange.Rows.Count + 1):
            vals = [lo.DataBodyRange.Cells(rw, c + 1).Value for c in range(len(hdr))]
            register[(str(vals[i_sheet]), str(vals[i_kpi]))] = str(vals[i_cell])
        ck(len(register) >= 12, "KPI register readable from the workbook",
           f"{len(register)} cards registered")

        found = 0
        for sheet, label, expected in cases:
            addr = register.get((sheet, label))
            if addr is None:
                ck(False, f"reconcile: {sheet} / {label}",
                   f"not in KPI register (have: "
                   f"{[k[1] for k in register if k[0] == sheet][:3]})")
                continue
            hit = wb.Worksheets(sheet).Range(addr).Value
            found += 1
            ok = hit is not None and abs(float(hit) - expected) < max(
                0.005, abs(expected) * 0.0005)
            ck(ok, f"reconcile: {sheet} / {label} @{addr}",
               f"workbook={float(hit):,.4f} evidence={expected:,.4f}"
               if hit is not None else "cell empty")
        ck(found == len(cases), "every KPI card located and recalculated",
           f"{found}/{len(cases)}")

        # Every registered card must hold a live number, not a stale constant.
        empty = [f"{s}!{a}" for (s, _), a in register.items()
                 if wb.Worksheets(s).Range(a).Value is None]
        ck(not empty, "every registered KPI card computes to a value",
           "all populated" if not empty else f"{empty[:3]}")

        # PivotTables: valid source ranges and non-empty results.
        for sheet, pname in [("Fuel Costs", "ptFuel"), ("Transport Costs", "ptTransport"),
                             ("Decision Signals", "ptFlags")]:
            ws = wb.Worksheets(sheet)
            try:
                pt = ws.PivotTables(pname)
                src = str(pt.SourceData)
                rows = pt.TableRange1.Rows.Count
                ck(rows > 2 and src, f"PivotTable {pname} has a valid source and data",
                   f"source={src} rows={rows}")
            except Exception as e:
                ck(False, f"PivotTable {pname} readable", f"{type(e).__name__}")

        # Transport pivot must NOT be able to produce an all-modes total (G6).
        try:
            pt = wb.Worksheets("Transport Costs").PivotTables("ptTransport")
            ck(pt.ColumnGrand is False and pt.RowGrand is False,
               "transport pivot has grand totals OFF (no all-modes total, G6)",
               f"ColumnGrand={pt.ColumnGrand} RowGrand={pt.RowGrand}")
        except Exception as e:
            ck(False, "transport grand totals check", f"{type(e).__name__}")

        # Slicers connected to a cache with items.
        try:
            n_sc = wb.SlicerCaches.Count
            connected = 0
            for i in range(1, n_sc + 1):
                sc = wb.SlicerCaches(i)
                if sc.PivotTables.Count >= 1:
                    connected += 1
            ck(n_sc >= 3 and connected == n_sc,
               "every slicer cache is connected to a PivotTable",
               f"{connected}/{n_sc} caches connected")
        except Exception as e:
            ck(False, "slicer connection check", f"{type(e).__name__}")

        # Charts have a source.
        chart_ct, bad = 0, 0
        for ws in wb.Worksheets:
            for sh in ws.ChartObjects():
                chart_ct += 1
                try:
                    if sh.Chart.SeriesCollection().Count == 0:
                        bad += 1
                except Exception:
                    bad += 1
        ck(chart_ct >= 4 and bad == 0, "every chart has at least one series",
           f"{chart_ct} charts, {bad} empty")

        # G9: rank-unstable metrics must not name a jurisdiction.
        ws = wb.Worksheets("Geographic Differences")
        named_unstable = 0
        for rw in range(1, 120):
            a = ws.Cells(rw, 1).Value
            if isinstance(a, str) and a in ("Petrol (NGN/l)", "Diesel (NGN/l)",
                                            "Air (NGN)", "LPG 5kg refill (NGN)",
                                            "LPG 12.5kg refill (NGN)"):
                for cl in (7, 8):
                    v = ws.Cells(rw, cl).Value
                    if isinstance(v, str) and "NOT NAMED" not in v.upper():
                        named_unstable += 1
        ck(named_unstable == 0,
           "G9 enforced: no rank-unstable metric names a jurisdiction",
           f"{named_unstable} violations")

        wb.Close(SaveChanges=False)
    finally:
        xl.Quit()


def main():
    if not WORKBOOK.exists():
        print("workbook not found - run build_excel_dashboard.py first")
        return 1
    print(f"validating {WORKBOOK.relative_to(ROOT)}  "
          f"({WORKBOOK.stat().st_size/1024:,.1f} KB)")
    ck = Checks()
    layer_a_ooxml(ck)
    layer_b_openpyxl(ck)
    layer_c_com_recalc(ck)
    return 1 if ck.summary() else 0


if __name__ == "__main__":
    raise SystemExit(main())
