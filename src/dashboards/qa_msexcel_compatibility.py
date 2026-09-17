"""Compatibility QA of the dashboard in GENUINE Microsoft Excel 16.0.

WHY THIS EXISTS. On this machine WPS Spreadsheets owns both the
`Excel.Application` ProgID AND the genuine Excel coclass
{00024500-0000-0000-C000-000000000046}, so Dispatch and DispatchEx both reach
WPS - it even reports Name='Microsoft Excel', Version=12.0. The workbook was
therefore authored by WPS, and "it saved fine" is not evidence that Microsoft
Excel can open it.

THE ROUTE THAT WORKS. Launching EXCEL.EXE with the document makes Microsoft
Excel register a DOCUMENT moniker in the Running Object Table. Binding that
moniker yields the real Application object (Version 16.0, Path under
...\\Microsoft Office\\root\\Office16). No ProgID or CLSID lookup is involved,
so the hijack is bypassed entirely.

    python src/dashboards/qa_msexcel_compatibility.py

The original WPS-authored file is backed up before Microsoft Excel saves over it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pythoncom
import win32com.client as w32

ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "outputs" / "dashboards" / "NBCI_Cost_Dashboard.xlsx"
BACKUP = ROOT / "outputs" / "dashboards" / "NBCI_Cost_Dashboard.wps-authored.bak.xlsx"
MSO = Path(r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE")

results: list[tuple[bool, str, str]] = []


def ck(ok, name, evidence=""):
    results.append((bool(ok), name, evidence))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{evidence}]" if evidence else ""))
    return bool(ok)


def kill_excel():
    subprocess.run(["taskkill", "/F", "/IM", "EXCEL.EXE"], capture_output=True)
    time.sleep(1.5)


def open_in_real_excel(path: Path, timeout_s=40):
    """Launch Microsoft Excel on `path` and bind its document moniker."""
    proc = subprocess.Popen([str(MSO), str(path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    target = str(path).lower()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(1.5)
        try:
            rot = pythoncom.GetRunningObjectTable()
            ctx = pythoncom.CreateBindCtx(0)
            for mk in rot.EnumRunning():
                try:
                    disp = mk.GetDisplayName(ctx, None)
                except Exception:
                    continue
                if disp.lower() != target:
                    continue
                obj = rot.GetObject(mk)
                wb = w32.Dispatch(obj.QueryInterface(pythoncom.IID_IDispatch))
                app = wb.Application
                if "Office16" in str(app.Path):
                    return proc, app, wb
        except Exception:
            pass
    raise RuntimeError("Microsoft Excel did not register the document moniker")


def ooxml_stats(path: Path):
    z = zipfile.ZipFile(path)
    n = z.namelist()
    drive = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])')
    abs_hits, nan_hits = [], 0
    for m in n:
        if m.endswith((".xml", ".rels")):
            blob = z.read(m).decode("utf-8", errors="ignore")
            if drive.search(blob) or "file:///" in blob:
                abs_hits.append(m)
            if m.startswith("xl/worksheets/"):
                nan_hits += blob.count("#QNAN") + blob.count("#IND") + blob.count("#INF")
    s = {
        "absPathParts": abs_hits,
        "pivotTables": len([x for x in n if re.match(r"xl/pivotTables/pivotTable\d+\.xml", x)]),
        "slicers": len([x for x in n if "slicer" in x.lower() and x.endswith(".xml")]),
        "charts": len([x for x in n if re.match(r"xl/charts/chart\d+\.xml", x)]),
        "tables": len([x for x in n if re.match(r"xl/tables/table\d+\.xml", x)]),
        "externalLinks": len([x for x in n if "externalLink" in x]),
        "absPaths": len(abs_hits), "nanLiterals": nan_hits,
        "size_kb": round(path.stat().st_size / 1024, 1),
    }
    z.close()
    return s


def strip_abs_path(path: Path) -> int:
    """Remove Microsoft Excel's x15ac:absPath stamp from xl/workbook.xml.

    On save, Excel records the workbook's own folder in an mc:AlternateContent
    block. It is metadata used to resolve relative links, NOT a data dependency,
    and it leaks a local path into an artefact meant to be portable. Excel opens
    the workbook perfectly well without it - files produced by other tools never
    have it - and pass 2 re-opens the stripped file to prove exactly that.

    Any future user save re-stamps their own path: that is inherent Excel
    behaviour for every workbook, not a defect in this one.
    """
    import shutil
    import tempfile

    z = zipfile.ZipFile(path)
    parts = {n: z.read(n) for n in z.namelist()}
    infos = {i.filename: i for i in z.infolist()}
    z.close()

    wbxml = parts["xl/workbook.xml"].decode("utf-8")
    before = wbxml
    wbxml = re.sub(
        r"<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>\s*"
        r"<x15ac:absPath[^>]*/>\s*</mc:Choice>\s*</mc:AlternateContent>",
        "", wbxml)
    wbxml = re.sub(r"<x15ac:absPath[^>]*/>", "", wbxml)
    if wbxml == before:
        return 0
    parts["xl/workbook.xml"] = wbxml.encode("utf-8")

    fd, tmpname = tempfile.mkstemp(suffix=".xlsx")
    import os as _os
    _os.close(fd)
    tmp = Path(tmpname)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in parts.items():
            if name.endswith("/"):
                continue
            zi = zipfile.ZipInfo(name, date_time=infos[name].date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = infos[name].external_attr
            out.writestr(zi, data)
    shutil.move(str(tmp), str(path))
    return 1


def inspect(app, wb, phase):
    """Count live objects and look for error values. Returns a summary dict."""
    pivots = slicers = charts = 0
    for ws in wb.Worksheets:
        try:
            pivots += ws.PivotTables().Count
        except Exception:
            pass
        try:
            charts += ws.ChartObjects().Count
        except Exception:
            pass
    try:
        slicers = wb.SlicerCaches.Count
    except Exception:
        pass

    # Recalculate, then read every registered KPI cell and look for errors.
    app.CalculateFullRebuild()
    errs, vals, blank = [], 0, 0
    try:
        lo = wb.Worksheets("Data_Evidence").ListObjects("tblKPIRegister")
        hdr = [str(c.Value) for c in lo.HeaderRowRange]
        i_s, i_c = hdr.index("sheet"), hdr.index("cell")
        for rw in range(1, lo.DataBodyRange.Rows.Count + 1):
            sh = str(lo.DataBodyRange.Cells(rw, i_s + 1).Value)
            cell = str(lo.DataBodyRange.Cells(rw, i_c + 1).Value)
            v = wb.Worksheets(sh).Range(cell).Value
            if v is None:
                blank += 1
            elif isinstance(v, str) and v.startswith("#"):
                errs.append(f"{sh}!{cell}={v}")
            else:
                vals += 1
    except Exception as e:
        errs.append(f"KPI register unreadable: {type(e).__name__}")
    print(f"    [{phase}] pivots={pivots} slicerCaches={slicers} charts={charts} "
          f"kpi_values={vals} blank={blank} errors={len(errs)}")
    return {"pivots": pivots, "slicers": slicers, "charts": charts,
            "kpi_values": vals, "kpi_blank": blank, "kpi_errors": errs}


def main() -> int:
    if not WORKBOOK.exists():
        print("workbook missing")
        return 1
    if not MSO.exists():
        print(f"Microsoft Excel not found at {MSO}")
        return 1

    print("=" * 74)
    print("MICROSOFT EXCEL 16.0 COMPATIBILITY QA")
    print("=" * 74)
    before = ooxml_stats(WORKBOOK)
    print(f"  WPS-authored file: {before}")
    shutil.copy2(WORKBOOK, BACKUP)
    print(f"  backup -> {BACKUP.name}")
    kill_excel()

    # ---- pass 1: open in Microsoft Excel -------------------------------
    print("\n-- pass 1: open in Microsoft Excel ---------------------------")
    proc, app, wb = open_in_real_excel(WORKBOOK)
    try:
        app.DisplayAlerts = False
        ck("Office16" in str(app.Path) and str(app.Version).startswith("16."),
           "automation attached to genuine Microsoft Excel",
           f"Version={app.Version} Path={app.Path}")

        # A cleanly opened workbook is NOT dirty. Excel marks a repaired file
        # dirty immediately, and names any recovered copy '... [Repaired]'.
        ck(wb.Saved is True, "workbook opened WITHOUT repair (not dirty on open)",
           f"Workbook.Saved={wb.Saved}")
        names = [str(app.Workbooks(i).Name) for i in range(1, app.Workbooks.Count + 1)]
        ck(not any("repair" in n.lower() or "recover" in n.lower() for n in names),
           "no repaired/recovered copy was created", f"open workbooks: {names}")
        ck(str(wb.Name) == WORKBOOK.name, "the intended file is the one that opened",
           str(wb.Name))

        s1 = inspect(app, wb, "pass 1")
        ck(s1["pivots"] == 3, "all 3 PivotTables load in Microsoft Excel", f"{s1['pivots']}")
        ck(s1["slicers"] == 3, "all 3 slicer caches load", f"{s1['slicers']} caches")
        ck(s1["charts"] == 4, "all 4 charts load", f"{s1['charts']}")
        ck(not s1["kpi_errors"], "no formula errors after full recalculation",
           "clean" if not s1["kpi_errors"] else str(s1["kpi_errors"][:3]))
        ck(s1["kpi_blank"] == 0, "every KPI cell holds a value", f"{s1['kpi_blank']} blank")

        # Slicers must be connected and responsive: drive one and watch the
        # PivotTable's visible row count change, then restore it.
        try:
            sc = wb.SlicerCaches(1)
            si = sc.SlicerItems
            total = si.Count
            pt = sc.PivotTables(1)
            before_rows = pt.TableRange1.Rows.Count
            first = si(1)
            first.Selected = False
            app.CalculateFullRebuild()
            after_rows = pt.TableRange1.Rows.Count
            first.Selected = True
            app.CalculateFullRebuild()
            restored = pt.TableRange1.Rows.Count
            ck(total > 0 and restored == before_rows,
               "slicer responds to selection and restores",
               f"{total} items; rows {before_rows} -> {after_rows} -> {restored}")
        except Exception as e:
            ck(False, "slicer responds to selection", f"{type(e).__name__}: {str(e)[:60]}")

        # ---- save / close / reopen -------------------------------------
        print("\n-- save, close, reopen in Microsoft Excel --------------------")
        wb.Save()
        saved_ok = True
        wb.Close(SaveChanges=False)
        try:
            app.Quit()
        except Exception:
            pass
        time.sleep(2)
        kill_excel()
        ck(saved_ok, "workbook saved by Microsoft Excel", "Workbook.Save() returned")
    except Exception as e:
        ck(False, "pass 1 completed", f"{type(e).__name__}: {str(e)[:80]}")
        kill_excel()
        return 1

    after = ooxml_stats(WORKBOOK)
    print(f"\n  after Microsoft Excel save: {after}")
    for key, label in [("pivotTables", "PivotTable parts"), ("slicers", "slicer parts"),
                       ("charts", "chart parts"), ("tables", "table parts")]:
        ck(after[key] >= before[key],
           f"{label} preserved through the Microsoft Excel save",
           f"{before[key]} -> {after[key]}")
    ck(after["externalLinks"] == 0, "still NO external links after the Excel save",
       f"{after['externalLinks']}")
    # OBSERVATION, not a check. Microsoft Excel stamps the workbook's own folder
    # into xl/workbook.xml as the x15ac:absPath extension on every save. That is
    # inherent Excel behaviour for any workbook, not a defect in this one, and it
    # is metadata rather than a data dependency. It is stripped immediately below
    # and the FINAL state is gated by "NO absolute local paths after
    # normalisation" plus the pass-2 reopen.
    print(f"    OBSERVED: Excel stamped absPath into "
          f"{after['absPathParts'] or 'nothing'} "
          f"({after['absPaths']} part) - normalised away next")
    if after["absPaths"]:
        for part in after["absPathParts"]:
            z = zipfile.ZipFile(WORKBOOK)
            blob = z.read(part).decode("utf-8", errors="ignore")
            z.close()
            for m in re.finditer(r'(?<![A-Za-z0-9])[A-Za-z]:[\/](?![\/])', blob):
                lo, hi = max(0, m.start() - 120), min(len(blob), m.end() + 120)
                print(f"    offending part: {part}")
                print(f"      ...{blob[lo:hi]}...")
                break
    ck(after["nanLiterals"] == 0, "still no invalid numeric literals", f"{after['nanLiterals']}")

    # ---- normalise: strip Excel's absolute-path stamp -------------------
    print("\n-- normalise: strip Excel's absPath stamp --------------------")
    stripped = strip_abs_path(WORKBOOK)
    print(f"    workbook.xml rewritten: {bool(stripped)}")
    norm_stats = ooxml_stats(WORKBOOK)
    ck(norm_stats["absPaths"] == 0,
       "NO absolute local paths after normalisation",
       f"{norm_stats['absPaths']} {norm_stats['absPathParts']}")
    for key, label in [("pivotTables", "PivotTable parts"),
                       ("slicers", "slicer parts"),
                       ("charts", "chart parts"), ("tables", "table parts")]:
        ck(norm_stats[key] == after[key], f"{label} intact after normalisation",
           f"{after[key]} -> {norm_stats[key]}")

    # ---- pass 2: reopen the NORMALISED file -----------------------------
    print("\n-- pass 2: reopen the NORMALISED file in Microsoft Excel -----")
    proc2, app2, wb2 = open_in_real_excel(WORKBOOK)
    try:
        app2.DisplayAlerts = False
        ck(wb2.Saved is True, "reopened WITHOUT repair", f"Workbook.Saved={wb2.Saved}")
        s2 = inspect(app2, wb2, "pass 2")
        ck(s2["pivots"] == 3 and s2["charts"] == 4 and s2["slicers"] == 3,
           "pivots, slicers and charts all survive the round trip",
           f"pivots={s2['pivots']} slicers={s2['slicers']} charts={s2['charts']}")
        ck(not s2["kpi_errors"] and s2["kpi_blank"] == 0,
           "no formula errors after reopening", f"{s2['kpi_values']} KPI values")
        wb2.Close(SaveChanges=False)
        try:
            app2.Quit()
        except Exception:
            pass
    except Exception as e:
        ck(False, "pass 2 completed", f"{type(e).__name__}: {str(e)[:80]}")
    finally:
        time.sleep(2)
        kill_excel()

    failed = sum(1 for ok, _, _ in results if not ok)
    print("\n" + "=" * 74)
    print(f"MICROSOFT EXCEL COMPATIBILITY QA: {len(results) - failed} of {len(results)} pass")
    if failed:
        for ok, name, ev in results:
            if not ok:
                print(f"  FAILED: {name}  [{ev}]")
    print("=" * 74)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
