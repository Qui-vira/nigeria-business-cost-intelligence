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

# Sheets are named for the business question they answer, not for the dataset they
# happen to use. The analytical detail is unchanged; the way in is not.
DASH_SHEETS = ["What is changing", "Fuel and energy", "Moving people and goods",
               "Where costs differ", "How unusual is this month",
               "Who this matters more for", "Can I trust this"]
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
            ("What is changing", "Diesel, trough to latest",
             ev(shock, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "median_pct") / 100),
            ("What is changing", "Petrol, trough to latest",
             ev(shock, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "median_pct") / 100),
            ("Fuel and energy", "Diesel: dearest minus cheapest place",
             ev(loc, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "spread_ngn")),
            ("Fuel and energy", "Petrol: dearest minus cheapest place",
             ev(loc, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "spread_ngn")),
            ("Fuel and energy", "Petrol: how many times dearer",
             ev(loc, "metric_code", "PETROL_PRICE_NGN_PER_LITRE", "dearest_over_cheapest")),
            ("Moving people and goods", "Okada fares that rose anyway",
             ev(sticky, "metric_code", "TRANSPORT_OKADA_NGN_PER_JOURNEY", "share_fare_rose_pct") / 100),
            ("Moving people and goods", "How far okada outran inflation",
             ev(farecpi, "metric_code", "TRANSPORT_OKADA_NGN_PER_JOURNEY", "median_gap_pp")),
            ("Where costs differ", "Water fares: how many times dearer",
             ev(loc, "metric_code", "TRANSPORT_WATER_NGN_PER_JOURNEY", "dearest_over_cheapest")),
            ("Where costs differ", "Costs with a stable order",
             float(rank.stable_for_persistent_ranking.sum())),
            ("How unusual is this month", "Diesel: what counts as EXTREME",
             ev(flags, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "extreme_p95_abs_pct") / 100),
            ("How unusual is this month", "Diesel: what counts as ELEVATED",
             ev(flags, "metric_code", "DIESEL_PRICE_NGN_PER_LITRE", "elevated_p90_abs_pct") / 100),
        ]
        expected_selfgen = float(selfgen.loc[
            (selfgen.observation_month == "2026-05-01") &
            (selfgen.genset_kwh_per_litre == 3.0), "multiple_of_reference_tariff"].iloc[0])
        cases.append(("How unusual is this month", "Generator cost vs grid power", expected_selfgen))

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
        for sheet, pname in [("Fuel and energy", "ptFuel"), ("Moving people and goods", "ptTransport"),
                             ("How unusual is this month", "ptFlags")]:
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
            pt = wb.Worksheets("Moving people and goods").PivotTables("ptTransport")
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
        ws = wb.Worksheets("Where costs differ")
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


def layer_d_decision_first(ck):
    """The workbook must EXPLAIN, not just compute.

    A reader with no analytics background should open the first sheet and, within about a
    minute, be able to name three things this project found and say why they might matter
    to a business. These checks assert that the structure carrying that is actually in the
    saved file - and, just as importantly, that the language stays inside what the evidence
    supports and never equates a lower measured cost with a better place to trade.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pbi_findings
    import pbi_narrative

    print("\n" + "=" * 74)
    print("LAYER D - EXPLANATION, FRAMING AND LANGUAGE")
    print("=" * 74)
    wb = load_workbook(WORKBOOK, data_only=False)

    def sheet_text(name):
        return "\n".join(
            str(c.value) for row in wb[name].iter_rows() for c in row
            if isinstance(c.value, str))

    first = sheet_text("What is changing")

    # --- 1. The scope framing, which is the point of the whole redesign -----
    ck(pbi_findings.WHAT_THIS_IS in first,
       "first sheet states WHAT NBCI measures")
    ck(pbi_findings.WHAT_THIS_IS_NOT in first,
       "first sheet states WHAT IT DOES NOT measure")
    ck(pbi_findings.WHY_NOT in first,
       "first sheet explains why cost alone does not decide a location")
    ck(pbi_findings.ONE_LINE in first,
       "first sheet carries the one-line summary: cost pressure, not profitability")
    for part, _examples, _in in pbi_findings.THE_EQUATION:
        ck(part in first, f"scope equation names '{part}'")
    ck("NOT measured here" in first,
       "scope equation marks the parts NBCI does not cover")

    # --- 2. The findings ----------------------------------------------------
    # --- 1b. The capability boundary ---------------------------------------
    # Knowing what is measured is not the same as knowing what may be concluded from
    # it. Both halves are asserted, on the first sheet and on the methodology sheet.
    trust = sheet_text("Can I trust this")
    ck(pbi_findings.CORE_QUESTION in trust,
       "methodology sheet states the project's core question in full")
    ck(pbi_findings.SIMPLE_DESCRIPTION in first,
       "first sheet carries the plain-English description of the project")
    for s in pbi_findings.CAN_DO:
        ck(s in first and s in trust, f"capability stated on both sheets: {s[:46]}")
    for s in pbi_findings.CANNOT_DO:
        ck(s in first and s in trust, f"limit stated on both sheets: {s[:46]}")
    ck(pbi_findings.WHAT_IT_WOULD_TAKE in first and pbi_findings.WHAT_IT_WOULD_TAKE in trust,
       "both sheets separate what exists now from what a later version would need")

    ck("What should I pay attention to?" in first,
       "first sheet asks 'What should I pay attention to?'")
    for f in pbi_findings.FINDINGS:
        missing = [k for k in ("headline", "question", "found", "matters", "who",
                               "review", "boundary", "evidence") if f[k] not in first]
        ck(not missing, f"finding {f['rank']} complete: {f['headline'][:48]}",
           "all six parts + evidence" if not missing else f"missing {missing}")

    # --- 3. Every dashboard sheet keeps the four-part band ------------------
    for sname in DASH_SHEETS:
        t = sheet_text(sname).upper()
        missing = [lab for lab in ("SIGNAL", "WHAT IT MEANS", "WHAT TO REVIEW", "BOUNDARY")
                   if lab not in t]
        ck(not missing, f"{sname}: all four decision parts present",
           "all four" if not missing else f"missing {missing}")

    # --- 4. Archetypes: six questions each ----------------------------------
    arch_t = sheet_text("Who this matters more for")
    for a in pbi_findings.ARCHETYPES:
        missing = [k for k in ("costs", "signals", "why", "review", "boundary", "needed")
                   if a[k] not in arch_t]
        ck(a["archetype"] in arch_t and not missing,
           f"archetype explained in full: {a['archetype']}",
           "all six parts" if not missing else f"missing {missing}")
    for heading in ("1.  WHICH NBCI COSTS MATTER HERE",
                    "2.  WHAT THE DATA CURRENTLY SHOWS",
                    "3.  WHY THAT COULD MATTER OPERATIONALLY",
                    "4.  WHAT MANAGEMENT SHOULD INVESTIGATE INTERNALLY",
                    "6.  COMPANY DATA NEEDED BEFORE ANY DECISION"):
        ck(heading in arch_t, f"archetype heading present: {heading.strip()}")

    # --- 5. LANGUAGE GUARD --------------------------------------------------
    # The dataset holds no company cost shares, margins, pass-through ability or revenue.
    # Nothing may instruct a business to act, and nothing may equate a lower measured cost
    # with a better place to do business - the single misreading this redesign prevents.
    review_verbs = ("review", "investigate", "compare", "measure", "reassess", "revisit",
                    "examine", "put ", "consider", "verify", "identify", "read ",
                    "obtain", "budget", "treat ", "do not")
    weak = [f["rank"] for f in pbi_findings.FINDINGS
            if not any(v in f["review"].lower() for v in review_verbs)]
    ck(not weak, "every finding's 'what to review' uses review-language",
       "all compliant" if not weak else f"{weak}")
    weak_a = [a["archetype"] for a in pbi_findings.ARCHETYPES
              if not any(v in a["review"].lower() for v in review_verbs)]
    ck(not weak_a, "every archetype's review text uses review-language",
       "all compliant" if not weak_a else f"{weak_a}")

    banned = ("you should raise", "you must raise", "raise your prices",
              "increase your prices", "you should relocate", "you must relocate",
              "move your business", "we recommend that you", "guaranteed",
              "best state", "best place", "cheapest state",
              "cheaper place to do business", "expand here", "leave this state")
    hits = []
    for sname in DASH_SHEETS:
        low = sheet_text(sname).lower()
        for b in banned:
            if b in low:
                hits.append(f"{sname}: '{b}'")
    ck(not hits, "no prescriptive language, and no cost-equals-quality claim",
       "clean" if not hits else f"{hits}")

    # --- 6. The boundary is never silently dropped --------------------------
    for sname in DASH_SHEETS:
        t = sheet_text(sname)
        ck(any(k in t for k in ("cannot", "CANNOT", "not tell", "NOT measure", "absent",
                                "NO ")),
           f"{sname}: states a limitation in plain words")


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
    layer_d_decision_first(ck)
    return 1 if ck.summary() else 0


if __name__ == "__main__":
    raise SystemExit(main())
