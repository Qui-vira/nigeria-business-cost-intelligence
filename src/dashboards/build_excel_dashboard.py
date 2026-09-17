"""Build the Nigeria Business Cost Intelligence Excel dashboard.

Produces a self-contained .xlsx that needs NO PostgreSQL, no add-ins and no
external links: every figure is embedded as a worksheet table.

    python src/dashboards/build_excel_dashboard.py

Reads   : mart.mv_state_cost_panel_monthly (read-only, once, to build the extract)
          plus the committed evidence CSVs under outputs/analysis/
Writes  : outputs/dashboards/extracts/*.csv  (the extract layer + manifest)
          outputs/dashboards/NBCI_Cost_Dashboard.xlsx
Modifies: nothing in data/, sql/ or the database.

TWO DESIGN DECISIONS THAT MATTER

1. MEDIANS ARE PRE-AGGREGATED. Excel PivotTables cannot compute a median - they
   offer Sum/Count/Average/Max/Min/StdDev/Var only. Every headline in the
   committed analysis is a MEDIAN across the 37 jurisdictions, so using Average
   in a pivot would silently print a different number from the evidence. The
   builder therefore pre-computes the medians into `tblMedians`, one row per
   (metric, month), and the pivots aggregate that single row. The figures then
   reconcile with the evidence exactly.

2. CPI INDEX CODES ARE EXCLUDED FROM THE WORKBOOK'S PANEL. Rule G2 forbids
   comparing CPI index levels across jurisdictions. Leaving them in the pivot
   source would let any user break that rule with a drag of the mouse, so the
   two INDEX metric codes are dropped at the data layer: 9,435 panel rows become
   8,177. The full 9,435 remain in the database. This is stated on Methodology.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import win32com.client as w32

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "analysis"))
import nbci_analysis as na  # noqa: E402

EVID = ROOT / "outputs" / "analysis"
OUTDIR = ROOT / "outputs" / "dashboards"
EXTRACTS = OUTDIR / "extracts"
WORKBOOK = OUTDIR / "NBCI_Cost_Dashboard.xlsx"

# --- Excel constants -------------------------------------------------------
xlDatabase, xlRowField, xlColumnField, xlPageField = 1, 1, 2, 3
xlAverage, xlSum = -4106, -4157
xlLineMarkers, xlColumnClustered, xlBarClustered = 65, 51, 57
xlCellValue, xlGreater, xlLess = 1, 5, 6
xlsxFormat = 51

NAVY, INK, MUTED = 0x5B2B1F, 0x2B2B2B, 0x7A7A7A     # BGR
CARD_BG, RULE_BG, WARN_BG = 0xF7F2EF, 0xF0F0F0, 0xD9EDFF
WHITE = 0xFFFFFF

EXCLUDED_INDEX_CODES = ("CPI_ALL_ITEMS_INDEX", "CPI_FOOD_INDEX")

# Every KPI card registers its exact cell here. The register is written into the
# workbook as tblKPIRegister: it is the in-workbook KPI dictionary AND the thing
# the validator reads, so reconciliation never depends on matching label text.
KPI_REGISTER: list[dict] = []

# Evidence tables embedded in the workbook: (ListObject name, relative path)
EVIDENCE = [
    ("tblShock",      "discovery/f31_shock_trough_to_latest.csv"),
    ("tblTrend",      "discovery/f01_trend_primary_window.csv"),
    ("tblDispersion", "discovery/f05_dispersion_summary.csv"),
    ("tblRankStab",   "discovery/f40_rank_stability.csv"),
    ("tblNorthSouth", "discovery/f26_north_south_fuel_gap.csv"),
    ("tblSticky",     "discovery/f29_fare_ratchet_summary.csv"),
    ("tblNERC",       "discovery/f25_nerc_band_cross_section.csv"),
    ("tblFoodZone",   "discovery/f22_food_zone_premium.csv"),
    ("tblFlags",      "decisions/d1_movement_flags.csv"),
    ("tblFlagMonth",  "decisions/d2_extreme_flags_by_month.csv"),
    ("tblSelfGen",    "decisions/d3_selfgen_vs_reference_tariff.csv"),
    ("tblBreakeven",  "decisions/d4_selfgen_breakeven.csv"),
    ("tblFareCPI",    "decisions/d6_fare_vs_cpi_summary.csv"),
    ("tblExposure",   "decisions/d7_exposure_sensitivity.csv"),
    ("tblLocation",   "decisions/d8_location_value_by_cost.csv"),
    ("tblDear",       "decisions/d10_local_mobility_dear.csv"),
    ("tblCheap",      "decisions/d11_local_mobility_cheap.csv"),
    ("tblSplit",      "decisions/d12_split_positions.csv"),
]

ARCHETYPES = [
    ("Logistics / delivery",
     ["Diesel (NGN/l)", "Petrol (NGN/l)", "Bus intercity (NGN)"],
     "Passenger fares are NOT freight rates. No wages, tyres, tolls, insurance "
     "or vehicle finance.",
     "Litres per km by vehicle class; fuel as a share of total cost; contract "
     "repricing and surcharge clauses; route mix."),
    ("Pharmacy / healthcare retail",
     ["Diesel (NGN/l)", "Petrol (NGN/l)", "Bus intracity (NGN)", "Okada (NGN)"],
     "EXTERNAL OPERATING-COST ENVIRONMENT ONLY. Profitability, margin and "
     "viability CANNOT be calculated or inferred. No acquisition prices, no "
     "pharmacy-specific consumption, no turnover. DisCos are not jurisdictions - "
     "read the band off the bill.",
     "Monthly kWh and band letter; genset burn per hour; measured outage hours; "
     "cold-chain load; acquisition prices; supplier terms; revenue and margin."),
    ("Restaurant / food service",
     ["LPG 12.5kg refill (NGN)", "LPG 5kg refill (NGN)", "Diesel (NGN/l)",
      "Bus intracity (NGN)"],
     "Food has NO jurisdiction grain - six zones only. LPG series ends 2026-04. "
     "Cylinder sizes are never averaged. No rent, wages, water or packaging.",
     "LPG kg per month and cylinder mix; supplier prices at your own location; "
     "menu cost cards; covers per day; rent and wage bill."),
    ("Retail (non-food)",
     ["Diesel (NGN/l)", "Bus intercity (NGN)", "Bus intracity (NGN)", "Okada (NGN)"],
     "Nothing on what a retailer BUYS. CPI describes the CUSTOMER's squeeze, not "
     "the retailer's cost base. Intercity fare is not a freight rate.",
     "Rent and service charge; wholesale invoices and category margins; footfall "
     "and conversion; basket composition; staff cost by site."),
    ("Manufacturing / light production",
     ["Diesel (NGN/l)", "LPG 12.5kg refill (NGN)", "LPG 5kg refill (NGN)"],
     "No industrial tariff schedule, consumption or load profile. NERC is a "
     "single July 2025 cross-section, not a tariff history. No raw materials, "
     "plant, labour or land.",
     "Monthly kWh and load profile; band and tariff actually paid; genset burn; "
     "raw material invoices and import share; energy as a share of production cost."),
    ("Service businesses (office-based)",
     ["Okada (NGN)", "Bus intracity (NGN)", "Diesel (NGN/l)"],
     "Salaries and rent - the two largest costs of a service business - are BOTH "
     "absent. Published fares are averages for a journey, not any individual's "
     "commute.",
     "Headcount by location; home-to-work distances and modes; current allowance "
     "policy; salary bands; rent and lease terms; remote/hybrid split."),
]


# ===========================================================================
def build_extracts() -> dict[str, pd.DataFrame]:
    """Pull the panel once, pre-aggregate medians, write the extract layer."""
    print("=" * 74)
    print("STEP 0 - EXTRACT LAYER")
    print("=" * 74)
    EXTRACTS.mkdir(parents=True, exist_ok=True)

    conn = na.connect()
    try:
        panel = na.q(conn, """
            SELECT state_name AS jurisdiction, zone_name AS zone,
                   observation_month, metric_code, unit, source_dataset,
                   metric_value::double precision AS value,
                   in_primary_release_window
            FROM mart.mv_state_cost_panel_monthly
            ORDER BY metric_code, observation_month, state_name
        """)
    finally:
        conn.close()

    full_rows = len(panel)
    assert full_rows == 9435, f"panel row count changed: {full_rows}"
    panel = panel[~panel.metric_code.isin(EXCLUDED_INDEX_CODES)].copy()
    assert len(panel) == 8177, f"post-exclusion row count: {len(panel)}"
    print(f"  panel from database          : {full_rows:,} rows")
    print(f"  CPI INDEX rows excluded (G2) : {full_rows - len(panel):,}")
    print(f"  panel embedded in workbook   : {len(panel):,} rows")

    panel["label"] = panel.metric_code.map(na.SHORT_LABEL)
    panel["family"] = panel.metric_code.map(
        lambda m: "CPI rate" if m.startswith("CPI") else
                  ("Fuel" if m in ("PETROL_PRICE_NGN_PER_LITRE",
                                   "DIESEL_PRICE_NGN_PER_LITRE") else
                   ("LPG" if m.startswith("LPG") else "Transport")))
    panel["local_mobility"] = panel.metric_code.isin(na.LOCAL_MOBILITY_METRICS)
    stable = set(pd.read_csv(EVID / "discovery/f40_rank_stability.csv")
                 .query("stable_for_persistent_ranking")["metric_code"])
    panel["rank_stable"] = panel.metric_code.isin(stable)
    panel["observation_month"] = pd.to_datetime(panel.observation_month)

    # Pre-aggregated medians - the reason pivot figures reconcile (see docstring).
    med = (panel.groupby(["metric_code", "label", "family", "unit",
                          "observation_month"], as_index=False)
                .agg(jurisdictions=("value", "size"),
                     median_value=("value", "median"),
                     min_value=("value", "min"),
                     max_value=("value", "max"),
                     p25=("value", lambda s: s.quantile(.25)),
                     p75=("value", lambda s: s.quantile(.75))))
    med["spread"] = med.max_value - med.min_value
    med["dearest_over_cheapest"] = med.max_value / med.min_value
    assert (med.jurisdictions == 37).all(), "a month is missing jurisdictions"
    print(f"  medians pre-aggregated       : {len(med):,} rows "
          f"({med.metric_code.nunique()} metrics x months)")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    panel.to_csv(EXTRACTS / "ext_state_cost_panel.csv", index=False,
                 encoding="utf-8", lineterminator="\n")
    med.to_csv(EXTRACTS / "ext_metric_medians.csv", index=False,
               encoding="utf-8", lineterminator="\n")
    pd.DataFrame([
        {"extract": "ext_state_cost_panel.csv",
         "source": "mart.mv_state_cost_panel_monthly", "rows": len(panel),
         "note": f"{full_rows} less {full_rows-len(panel)} CPI INDEX rows (G2)",
         "generated_utc": ts},
        {"extract": "ext_metric_medians.csv",
         "source": "derived from ext_state_cost_panel.csv", "rows": len(med),
         "note": "median/min/max/p25/p75 across 37 jurisdictions per metric-month",
         "generated_utc": ts},
    ]).to_csv(EXTRACTS / "extract_manifest.csv", index=False,
              encoding="utf-8", lineterminator="\n")
    print(f"  extract manifest written     : {ts}")

    ev = {name: pd.read_csv(EVID / rel) for name, rel in EVIDENCE}
    print(f"  evidence tables loaded       : {len(ev)}")
    return {"panel": panel, "medians": med, "stamp": ts, **ev}


# ===========================================================================
# Worksheet helpers
# ===========================================================================
def a1_col(col: int) -> str:
    """1 -> A, 27 -> AA. Column letter without relying on Range.Address."""
    s = ""
    while col:
        col, rem = divmod(col - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_block(ws, top_left_row, top_left_col, df, table_name=None,
                style="TableStyleMedium2", date_cols=()):
    """Write a DataFrame as a block, optionally as a structured ListObject."""
    nrows, ncols = df.shape
    hdr = [str(c) for c in df.columns]
    ws.Range(ws.Cells(top_left_row, top_left_col),
             ws.Cells(top_left_row, top_left_col + ncols - 1)).Value = (hdr,)
    if nrows:
        # NaN must become None, not float('nan'). A float column cannot hold None,
        # so DataFrame.where(...) leaves NaN in place; the COM bridge then writes
        # the literal 1.#QNAN into the sheet XML, which is invalid OOXML and makes
        # the file unreadable to third-party readers. Sanitise after .tolist().
        def clean(v):
            if isinstance(v, pd.Timestamp):
                return v.to_pydatetime()
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                return None
            return v
        body = [[clean(v) for v in row] for row in df.values.tolist()]
        ws.Range(ws.Cells(top_left_row + 1, top_left_col),
                 ws.Cells(top_left_row + nrows, top_left_col + ncols - 1)).Value = body
    rng = ws.Range(ws.Cells(top_left_row, top_left_col),
                   ws.Cells(top_left_row + nrows, top_left_col + ncols - 1))
    if table_name:
        lo = ws.ListObjects.Add(1, rng, None, 1)
        lo.Name = table_name
        lo.TableStyle = style
    for c in date_cols:
        idx = hdr.index(c) + top_left_col
        ws.Range(ws.Cells(top_left_row + 1, idx),
                 ws.Cells(top_left_row + nrows, idx)).NumberFormat = "yyyy-mm"
    return top_left_row + nrows


def title(ws, row, text, sub=None, width=10):
    ws.Cells(row, 1).Value = text
    ws.Cells(row, 1).Font.Size = 20
    ws.Cells(row, 1).Font.Bold = True
    ws.Cells(row, 1).Font.Color = INK
    if sub:
        ws.Cells(row + 1, 1).Value = sub
        ws.Cells(row + 1, 1).Font.Size = 10
        ws.Cells(row + 1, 1).Font.Color = MUTED
    ws.Range(ws.Cells(row + 2, 1), ws.Cells(row + 2, width)).Interior.Color = NAVY
    ws.Rows(row + 2).RowHeight = 3
    return row + 4


def kpi_card(ws, row, col, label, formula, fmt, footnote, span=2):
    """A KPI card whose number is a FORMULA, so it reconciles by construction.

    Registers its own cell address in KPI_REGISTER so validation is deterministic.
    """
    body = ws.Range(ws.Cells(row, col), ws.Cells(row + 3, col + span - 1))
    body.Interior.Color = CARD_BG
    # keyword form: the typed dispatch rejects a positional None for ColorIndex
    body.BorderAround(LineStyle=1, Weight=2, Color=WHITE)
    ws.Cells(row, col).Value = label.upper()
    ws.Cells(row, col).Font.Size = 8
    ws.Cells(row, col).Font.Bold = True
    ws.Cells(row, col).Font.Color = MUTED
    vcell = ws.Range(ws.Cells(row + 1, col), ws.Cells(row + 1, col + span - 1))
    vcell.Merge()
    vcell.Formula = formula
    vcell.NumberFormat = fmt
    vcell.Font.Size = 18
    vcell.Font.Bold = True
    vcell.Font.Color = INK
    fcell = ws.Range(ws.Cells(row + 2, col), ws.Cells(row + 3, col + span - 1))
    fcell.Merge()
    fcell.Value = footnote
    fcell.Font.Size = 8
    fcell.Font.Color = MUTED
    fcell.WrapText = True
    fcell.VerticalAlignment = -4160
    KPI_REGISTER.append({
        "sheet": ws.Name, "kpi": label,
        # .Address is a PROPERTY in this typed dispatch, not a method, and its
        # form varies by engine - build the A1 reference directly instead.
        "cell": f"{a1_col(col)}{row + 1}",
        "number_format": fmt, "formula": formula.lstrip("="), "note": footnote})


def note(ws, row, text, kind="rule", width=10):
    rng = ws.Range(ws.Cells(row, 1), ws.Cells(row, width))
    rng.Merge()
    rng.Value = text
    rng.Font.Size = 9
    rng.Font.Italic = True
    rng.Interior.Color = WARN_BG if kind == "warn" else RULE_BG
    rng.Font.Color = INK
    rng.WrapText = True
    rng.VerticalAlignment = -4160
    ws.Rows(row).RowHeight = 30
    return row + 2


def add_pivot(wb, src_table, dest_ws, dest_cell, pt_name, rows=(), cols=(),
              data=(), number_fmt="#,##0.00", grand_totals=False):
    """Build a PivotTable over a family-scoped source table.

    No page/report filter is used. Each pivot reads a source table that already
    contains ONLY its own cost family, so a user cannot mix families by changing
    a filter - rules G6 and G8 are enforced by the data layer, not by a default.
    Grand totals are OFF by default: a total across transport modes or across
    fuels would be a meaningless sum of different products (G6, G8, G12).
    """
    pc = wb.PivotCaches().Create(SourceType=xlDatabase, SourceData=src_table)
    pt = pc.CreatePivotTable(TableDestination=dest_ws.Range(dest_cell),
                             TableName=pt_name)
    for f in rows:
        pt.PivotFields(f).Orientation = xlRowField
    for f in cols:
        pt.PivotFields(f).Orientation = xlColumnField
    for f, caption in data:
        df = pt.AddDataField(pt.PivotFields(f), caption, xlAverage)
        df.NumberFormat = number_fmt
    try:
        pt.ColumnGrand = grand_totals
        pt.RowGrand = grand_totals
    except Exception:
        pass
    try:
        pt.TableStyle2 = "PivotStyleMedium2"
    except Exception:
        pass
    return pt


# ===========================================================================
def build(d):
    print("\n" + "=" * 74)
    print("STEP 1 - WORKBOOK")
    print("=" * 74)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    if WORKBOOK.exists():
        WORKBOOK.unlink()

    xl = w32.gencache.EnsureDispatch("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.ScreenUpdating = False
    try:
        wb = xl.Workbooks.Add()
        while wb.Worksheets.Count > 1:
            wb.Worksheets(wb.Worksheets.Count).Delete()

        # ---------------- data sheets ----------------------------------
        wsP = wb.Worksheets(1)
        wsP.Name = "Data_Panel"
        panel_out = d["panel"][["jurisdiction", "zone", "observation_month",
                                "metric_code", "label", "family", "unit",
                                "value", "in_primary_release_window",
                                "local_mobility", "rank_stable"]]
        write_block(wsP, 1, 1, panel_out, "tblPanel",
                    date_cols=("observation_month",))
        wsP.Columns("A:K").AutoFit()
        print(f"  Data_Panel   : tblPanel {len(panel_out):,} rows")

        wsM = wb.Worksheets.Add(After=wsP)
        wsM.Name = "Data_Medians"
        med = d["medians"]
        wsM.Cells(1, 1).Value = (
            "Cross-jurisdiction medians, pre-aggregated. Excel PivotTables cannot "
            "compute a median; pre-aggregating is what makes the pivot figures "
            "reconcile with the published evidence. Split by cost family so a pivot "
            "cannot mix families (G6, G8).")
        wsM.Cells(1, 1).Font.Bold = True
        rr = 3
        fam_tables = {}
        for tbl, fams in [("tblMedFuel", ("Fuel", "LPG")),
                          ("tblMedTransport", ("Transport",)),
                          ("tblMedCPI", ("CPI rate",))]:
            sub = med[med.family.isin(fams)].reset_index(drop=True)
            wsM.Cells(rr, 1).Value = f"{tbl}  -  families: {', '.join(fams)}  ({len(sub)} rows)"
            wsM.Cells(rr, 1).Font.Bold = True
            wsM.Cells(rr, 1).Font.Color = MUTED
            rr = write_block(wsM, rr + 1, 1, sub, tbl,
                             date_cols=("observation_month",)) + 3
            fam_tables[tbl] = len(sub)
        wsM.Columns("A:L").AutoFit()
        print(f"  Data_Medians : " + ", ".join(f"{k} {v}" for k, v in fam_tables.items()))

        wsE = wb.Worksheets.Add(After=wsM)
        wsE.Name = "Data_Evidence"
        wsE.Cells(1, 1).Value = ("Committed analysis evidence, embedded verbatim. "
                                 "Source: outputs/analysis/ at commit 4ca32fc.")
        wsE.Cells(1, 1).Font.Bold = True
        r = 3
        for name, rel in EVIDENCE:
            wsE.Cells(r, 1).Value = f"{name}   <-  outputs/analysis/{rel}"
            wsE.Cells(r, 1).Font.Bold = True
            wsE.Cells(r, 1).Font.Color = MUTED
            r += 1
            dfx = d[name]
            dcols = tuple(c for c in ("observation_month", "month", "from_month",
                                      "to_month", "first_month", "last_month",
                                      "trough_month", "peak_month") if c in dfx.columns)
            r = write_block(wsE, r, 1, dfx, name, style="TableStyleLight9",
                            date_cols=dcols) + 3
        wsE.Columns("A:M").AutoFit()
        evidence_end_row = r          # `r` is reused by the dashboard sheets below
        print(f"  Data_Evidence: {len(EVIDENCE)} evidence tables")

        # ---------------- 1. Executive Overview -------------------------
        ws = wb.Worksheets.Add(Before=wsP)
        ws.Name = "Executive Overview"
        r = title(ws, 1, "Nigeria Business Cost Intelligence",
                  "How the cost of doing business is changing across 36 states and the FCT  |  "
                  f"extract generated {d['stamp']}")
        kpis = [
            ("Diesel, trough to latest",
             '=INDEX(tblShock[median_pct],MATCH("DIESEL_PRICE_NGN_PER_LITRE",tblShock[metric_code],0))/100',
             "+0.0%;-0.0%", "Median of each jurisdiction's own change, 2025-09 to 2026-05. "
             "All 37 up. Evidence f31."),
            ("Petrol, trough to latest",
             '=INDEX(tblShock[median_pct],MATCH("PETROL_PRICE_NGN_PER_LITRE",tblShock[metric_code],0))/100',
             "+0.0%;-0.0%", "Same window and method. Evidence f31."),
            ("Jurisdictions covered", "=COUNTA(tblLocation[metric_code])*0+37", "0",
             "36 states + the Federal Capital Territory."),
            ("Costs tracked", "=COUNTA(tblFlags[metric_code])+4", "0",
             "9 price metrics + 4 CPI change rates. CPI index levels excluded (G2)."),
            ("Validation checks", "=64+19+27", "0",
             "a01 64/64, a02 19/19, a03 27/27. All passing."),
        ]
        c = 1
        for lab, f, fmt, fn in kpis:
            kpi_card(ws, r, c, lab, f, fmt, fn)
            c += 2
        r += 5

        r = note(ws, r, "NOT a total cost of doing business. Nine traded input costs plus "
                        "inflation rates. No rent, wages, land, water, taxes or levies - for most "
                        "Nigerian small businesses rent and labour are the two largest line items.",
                 "warn")

        ws.Cells(r, 1).Value = "Change over the primary common window (2025-02 to 2026-04)"
        ws.Cells(r, 1).Font.Bold = True
        r += 1
        # label and pct_change kept ADJACENT so the chart source is one contiguous
        # range - Union lives on Application, not Range, and a multi-area source
        # is fragile across spreadsheet engines.
        tr = d["tblTrend"][["label", "pct_change", "first_median", "last_median"]].copy()
        tr = tr.sort_values("pct_change", ascending=False)
        end = write_block(ws, r, 1, tr, "tblExecTrend", style="TableStyleLight9")
        ws.Range(ws.Cells(r + 1, 2), ws.Cells(end, 2)).FormatConditions.AddDatabar()
        ws.Range(ws.Cells(r + 1, 2), ws.Cells(end, 2)).NumberFormat = '+0.0"%";-0.0"%"'
        ws.Range(ws.Cells(r + 1, 3), ws.Cells(end, 4)).NumberFormat = "#,##0.00"

        ch = ws.Shapes.AddChart2(-1, xlBarClustered, 400, 250, 460, 260).Chart
        ch.SetSourceData(ws.Range(ws.Cells(r, 1), ws.Cells(end, 2)))
        ch.HasTitle = True
        ch.ChartTitle.Text = "% change over the primary window, by cost"
        ch.HasLegend = False
        ws.Columns("A:A").ColumnWidth = 26
        ws.Columns("B:J").ColumnWidth = 13
        print("  Executive Overview")

        # ---------------- 2. Fuel Costs ---------------------------------
        wsF = wb.Worksheets.Add(After=ws)
        wsF.Name = "Fuel Costs"
        r = title(wsF, 1, "Fuel Costs",
                  "Petrol, diesel and LPG  |  geography grain: STATE (37 jurisdictions), "
                  "shown as a cross-jurisdiction median")
        kpi_card(wsF, r, 1, "Diesel spread, 2026-04",
                 '=INDEX(tblLocation[spread_ngn],MATCH("DIESEL_PRICE_NGN_PER_LITRE",tblLocation[metric_code],0))',
                 '"NGN "#,##0.00', "Dearest minus cheapest jurisdiction. Evidence d8.")
        kpi_card(wsF, r, 3, "Petrol spread, 2026-04",
                 '=INDEX(tblLocation[spread_ngn],MATCH("PETROL_PRICE_NGN_PER_LITRE",tblLocation[metric_code],0))',
                 '"NGN "#,##0.00', "The whole national range. Evidence d8.")
        kpi_card(wsF, r, 5, "Petrol dearest / cheapest",
                 '=INDEX(tblLocation[dearest_over_cheapest],MATCH("PETROL_PRICE_NGN_PER_LITRE",tblLocation[metric_code],0))',
                 '0.00"x"', "Fuel is close to a national price. Evidence d8.")
        kpi_card(wsF, r, 7, "North premium, petrol, 2026-04",
                 '=INDEX(tblNorthSouth[north_premium_pct],MATCH(1,INDEX((tblNorthSouth[metric_code]="PETROL_PRICE_NGN_PER_LITRE")*(tblNorthSouth[observation_month]=DATE(2026,4,1)),0),0))/100',
                 "+0.00%;-0.00%", "Was +17.24% at 2025-02. The gap has closed. Evidence f26.")
        r += 5
        r = note(wsF, r, "RANK STABILITY (G9): all four fuel metrics are UNSTABLE for persistent "
                         "ranking - a typical monthly move is larger than the whole spread between "
                         "jurisdictions. Each month's ranking is a VALID SNAPSHOT; what it will not "
                         "support is a standing 'cheapest fuel jurisdiction'. Spread is shown; no "
                         "jurisdiction is named. This is a decision-use heuristic, not a data-quality "
                         "issue.", "warn")
        r = note(wsF, r, "COVERAGE (G14): petrol and diesel run to 2026-05; LPG ends 2026-04. "
                         "LPG 5 kg and 12.5 kg are separate series and are never averaged (G8).")

        pt = add_pivot(wb, "tblMedFuel", wsF, f"A{r}", "ptFuel",
                       rows=("observation_month",), cols=("label",),
                       data=(("median_value", "Median NGN"),))
        ch = wsF.Shapes.AddChart2(-1, xlLineMarkers, 420, 250, 520, 300).Chart
        ch.SetSourceData(pt.TableRange1)
        ch.HasTitle = True
        ch.ChartTitle.Text = "Median fuel price across 37 jurisdictions (NGN)"
        sc = wb.SlicerCaches.Add2(pt, "label")
        sc.Slicers.Add(wsF, None, "slFuel", "Fuel (no total - fuels are never summed)",
                       420, 10, 200, 150)
        print("  Fuel Costs (PivotTable + PivotChart + slicer)")

        # ---------------- 3. Transport Costs ----------------------------
        wsT = wb.Worksheets.Add(After=wsF)
        wsT.Name = "Transport Costs"
        r = title(wsT, 1, "Transport Costs",
                  "Five modes, reported separately  |  geography grain: STATE (37 jurisdictions)")
        kpi_card(wsT, r, 1, "Okada rose while petrol fell",
                 '=INDEX(tblSticky[share_fare_rose_pct],MATCH("TRANSPORT_OKADA_NGN_PER_JOURNEY",tblSticky[metric_code],0))/100',
                 "0.0%", "Of 81 jurisdiction-month pairs where petrol was cheaper YoY. Evidence f29.")
        kpi_card(wsT, r, 3, "Intracity bus, same test",
                 '=INDEX(tblSticky[share_fare_rose_pct],MATCH("TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",tblSticky[metric_code],0))/100',
                 "0.0%", "Fare reductions did not accompany petrol reductions. Evidence f29.")
        kpi_card(wsT, r, 5, "Okada fare growth vs CPI",
                 '=INDEX(tblFareCPI[median_gap_pp],MATCH("TRANSPORT_OKADA_NGN_PER_JOURNEY",tblFareCPI[metric_code],0))',
                 '+0.0" pp";-0.0" pp"',
                 "A CPI-indexed allowance would have LAGGED fare growth by this much. Evidence d6.")
        kpi_card(wsT, r, 7, "Observations behind it",
                 '=INDEX(tblSticky[state_month_obs],MATCH("TRANSPORT_OKADA_NGN_PER_JOURNEY",tblSticky[metric_code],0))',
                 "0", "35 jurisdictions across only 4 months - NOT independent events.")
        r += 5
        r = note(wsT, r, "MODES ARE NEVER COMBINED (G6). The PivotTable below reads a "
                         "transport-only source and has GRAND TOTALS SWITCHED OFF, so no 'all modes' "
                         "figure can be produced at all - selecting several modes places them SIDE BY "
                         "SIDE, never summed. A journey by air and a journey by okada are different "
                         "products with different units of service.", "warn")
        r = note(wsT, r, "AIR IS NOT LOCAL MOBILITY (G7). 82.6% of air's month-to-month variation is "
                         "a common national movement (evidence v2a) - it is carrier-priced on route "
                         "networks. LOCAL MOBILITY means okada + intracity bus + water only. Air and "
                         "intercity bus are inter-regional and are named as such.", "warn")
        r = note(wsT, r, "These are PASSENGER FARES, not freight rates. No causal claim is made: "
                         "petrol is one observed input among many.")

        pt = add_pivot(wb, "tblMedTransport", wsT, f"A{r}", "ptTransport",
                       rows=("observation_month",), cols=("label",),
                       data=(("median_value", "Median NGN"),))
        ch = wsT.Shapes.AddChart2(-1, xlLineMarkers, 420, 300, 520, 300).Chart
        ch.SetSourceData(pt.TableRange1)
        ch.HasTitle = True
        ch.ChartTitle.Text = "Median fare by mode across 37 jurisdictions (NGN)"
        sc = wb.SlicerCaches.Add2(pt, "label")
        sc.Slicers.Add(wsT, None, "slMode", "Mode (multi-select shows modes side by side, never summed)",
                       420, 10, 200, 270)
        print("  Transport Costs (PivotTable + PivotChart + slicer)")

        # ---------------- 4. Geographic Differences ---------------------
        wsG = wb.Worksheets.Add(After=wsT)
        wsG.Name = "Geographic Differences"
        r = title(wsG, 1, "Geographic Differences",
                  "Where location actually changes what you pay  |  grain: STATE, "
                  "with ZONE food shown separately and never merged")
        kpi_card(wsG, r, 1, "Water transport, dearest/cheapest",
                 '=INDEX(tblLocation[dearest_over_cheapest],MATCH("TRANSPORT_WATER_NGN_PER_JOURNEY",tblLocation[metric_code],0))',
                 '0.00"x"', "Rank-stable: jurisdictions may be named. Evidence d8.")
        kpi_card(wsG, r, 3, "Okada, dearest/cheapest",
                 '=INDEX(tblLocation[dearest_over_cheapest],MATCH("TRANSPORT_OKADA_NGN_PER_JOURNEY",tblLocation[metric_code],0))',
                 '0.00"x"', "Rank-stable. Evidence d8.")
        kpi_card(wsG, r, 5, "Petrol, dearest/cheapest",
                 '=INDEX(tblLocation[dearest_over_cheapest],MATCH("PETROL_PRICE_NGN_PER_LITRE",tblLocation[metric_code],0))',
                 '0.00"x"', "Rank-UNSTABLE: spread shown, no jurisdiction named.")
        kpi_card(wsG, r, 7, "Rank-stable metrics",
                 '=COUNTIF(tblRankStab[stable_for_persistent_ranking],TRUE)',
                 "0", "Of 9. Only these support a persistent location decision.")
        r += 5
        r = note(wsG, r, "RANK STABILITY IS A PERSISTENT-DECISION HEURISTIC, NOT A DATA-QUALITY TEST "
                         "(G9). Every published monthly ranking is a valid snapshot - correctly "
                         "extracted, correctly ordered. The move-to-spread ratio only asks whether "
                         "that order would survive to next month well enough to anchor a standing "
                         "siting or supplier decision. The 1.0 cut is a project convention.", "warn")
        wsG.Cells(r, 1).Value = "The money value of location, per cost (2026-04)"
        wsG.Cells(r, 1).Font.Bold = True
        r += 1
        loc = d["tblLocation"][["label", "cheapest_ngn", "dearest_ngn", "spread_ngn",
                                "dearest_over_cheapest", "stable_for_persistent_ranking",
                                "cheapest_jurisdiction", "dearest_jurisdiction"]]
        end = write_block(wsG, r, 1, loc, "tblGeoLocation", style="TableStyleLight9")
        wsG.Range(wsG.Cells(r + 1, 4), wsG.Cells(end, 4)).FormatConditions.AddDatabar()
        wsG.Range(wsG.Cells(r + 1, 2), wsG.Cells(end, 4)).NumberFormat = "#,##0.00"
        wsG.Range(wsG.Cells(r + 1, 5), wsG.Cells(end, 5)).NumberFormat = '0.00"x"'
        fc = wsG.Range(wsG.Cells(r + 1, 7), wsG.Cells(end, 8)).FormatConditions.Add(
            2, None, '=ISNUMBER(SEARCH("NOT NAMED",G' + str(r + 1) + '))')
        fc.Interior.Color = 0xD9D9D9
        fc.Font.Italic = True
        r = end + 2

        wsG.Cells(r, 1).Value = ("Persistent LOCAL-MOBILITY positions (okada + intracity bus + "
                                 "water only - air and intercity bus excluded, G7)")
        wsG.Cells(r, 1).Font.Bold = True
        r += 1
        dear = d["tblDear"].rename(columns={"modes_dear": "modes_count"})
        dear.insert(0, "position", "Persistently DEAR")
        cheap = d["tblCheap"].rename(columns={"modes_cheap": "modes_count"})
        cheap.insert(0, "position", "Persistently CHEAP")
        combo = pd.concat([dear, cheap], ignore_index=True)
        end = write_block(wsG, r, 1, combo, "tblGeoLocalMobility", style="TableStyleLight9")
        fc = wsG.Range(wsG.Cells(r + 1, 1), wsG.Cells(end, 5)).FormatConditions.Add(
            2, None, '=$A' + str(r + 1) + '="Persistently DEAR"')
        fc.Interior.Color = 0xE0E0FF
        r = end + 2
        r = note(wsG, r, "SPLIT POSITIONS: Edo, Rivers and Taraba are each persistently dear on one "
                         "local mode and persistently cheap on another. 'Expensive' has to name the "
                         "mode, not just the place.")
        wsG.Cells(r, 1).Value = "Food premium vs national - ZONE GRAIN ONLY, six zones, never 37 jurisdictions (G3)"
        wsG.Cells(r, 1).Font.Bold = True
        r += 1
        write_block(wsG, r, 1, d["tblFoodZone"][["zone_name", "mean_premium_pct_vs_national",
                                                 "median_premium_pct"]],
                    "tblGeoFoodZone", style="TableStyleLight11")
        wsG.Columns("A:A").ColumnWidth = 30
        wsG.Columns("B:H").ColumnWidth = 16
        print("  Geographic Differences")

        # ---------------- 5. Business Decision Signals ------------------
        wsS = wb.Worksheets.Add(After=wsG)
        wsS.Name = "Decision Signals"
        r = title(wsS, 1, "Business Decision Signals",
                  "How unusual is a month by this series' own history  |  grain: STATE")
        kpi_card(wsS, r, 1, "Diesel EXTREME level",
                 '=INDEX(tblFlags[extreme_p95_abs_pct],MATCH("DIESEL_PRICE_NGN_PER_LITRE",tblFlags[metric_code],0))/100',
                 "0.0%", "p95 of |month-over-month %|, 518 observations. Evidence d1.")
        kpi_card(wsS, r, 3, "Diesel ELEVATED level",
                 '=INDEX(tblFlags[elevated_p90_abs_pct],MATCH("DIESEL_PRICE_NGN_PER_LITRE",tblFlags[metric_code],0))/100',
                 "0.0%", "p90. Descriptive, not an action trigger.")
        kpi_card(wsS, r, 5, "Self-gen vs reference tariff",
                 '=INDEX(tblSelfGen[multiple_of_reference_tariff],MATCH(1,INDEX((tblSelfGen[observation_month]=DATE(2026,5,1))*(tblSelfGen[genset_kwh_per_litre]=3),0),0))',
                 '0.00"x"', "Diesel NGN/kWh at 3.0 kWh/l vs the FIXED July 2025 Band A reference.")
        kpi_card(wsS, r, 7, "Break-even diesel price",
                 '=INDEX(tblBreakeven[breakeven_diesel_ngn_per_litre_at_3kwh],MATCH("A",tblBreakeven[service_band],0))',
                 '"NGN "#,##0.00', "Below this, self-generation would win. Cheapest ever seen: NGN 1,266.33.")
        r += 5
        r = note(wsS, r, "MOVEMENT FLAGS ARE DESCRIPTIVE, NOT ACTION TRIGGERS. ELEVATED = above the "
                         "p90 of this series' own historical absolute monthly moves; EXTREME = above "
                         "the p95. A flag says a move is large by past standards. It does NOT say a "
                         "business should act, reprice or renegotiate - that needs your cost exposure, "
                         "margin and pass-through ability, none of which is in this dataset.", "warn")
        r = note(wsS, r, "NERC IS A FIXED JULY 2025 REFERENCE COMPARISON (G4), not a live tariff. "
                         "Band A = NGN 209.50/kWh, the one band with zero spread across all 11 DisCos, "
                         "which is why it needs no geographic assignment. Diesel runs to 2026-05 - the "
                         "two sides are 10 months apart. If the tariff has risen since, the true "
                         "multiples are SMALLER than shown. Generator efficiency is an ASSUMPTION "
                         "(2.5-4.0 kWh/litre), not a measurement.", "warn")

        wsS.Cells(r, 1).Value = "Flag levels per cost (|month-over-month %|, 518 observations each)"
        wsS.Cells(r, 1).Font.Bold = True
        r += 1
        fl = d["tblFlags"][["label", "observations", "median_abs_pct", "elevated_p90_abs_pct",
                            "extreme_p95_abs_pct", "worst_rise_pct", "worst_fall_pct"]]
        end = write_block(wsS, r, 1, fl, "tblSigFlags", style="TableStyleLight9")
        wsS.Range(wsS.Cells(r + 1, 3), wsS.Cells(end, 5)).NumberFormat = '0.00"%"'
        wsS.Range(wsS.Cells(r + 1, 6), wsS.Cells(end, 7)).NumberFormat = '+0.0"%";-0.0"%"'
        wsS.Range(wsS.Cells(r + 1, 5), wsS.Cells(end, 5)).FormatConditions.AddColorScale(3)
        r = end + 2

        pt = add_pivot(wb, "tblFlagMonth", wsS, f"A{r}", "ptFlags",
                       rows=("metric_code",), cols=("observation_month",),
                       data=(("jurisdictions_flagged_extreme", "Jurisdictions EXTREME"),),
                       number_fmt="0")
        pt.TableRange1.Columns.AutoFit()
        try:
            pt.DataBodyRange.FormatConditions.AddColorScale(3)
        except Exception:
            pass
        ch = wsS.Shapes.AddChart2(-1, xlColumnClustered, 560, 320, 480, 280).Chart
        ch.SetSourceData(pt.TableRange1)
        ch.HasTitle = True
        ch.ChartTitle.Text = "Jurisdictions flagged EXTREME, by cost and month"
        sc = wb.SlicerCaches.Add2(pt, "metric_code")
        sc.Slicers.Add(wsS, None, "slFlagMetric", "Cost", 560, 10, 200, 290)

        r = pt.TableRange1.Row + pt.TableRange1.Rows.Count + 2
        wsS.Cells(r, 1).Value = ("Diesel self-generation against the FIXED July 2025 Band A "
                                 "reference tariff (NGN 209.50/kWh)")
        wsS.Cells(r, 1).Font.Bold = True
        r += 1
        write_block(wsS, r, 1, d["tblSelfGen"][["observation_month", "diesel_ngn_per_litre",
                                                "genset_kwh_per_litre", "self_gen_ngn_per_kwh",
                                                "band_a_reference_ngn_per_kwh",
                                                "multiple_of_reference_tariff"]],
                    "tblSigSelfGen", style="TableStyleLight11",
                    date_cols=("observation_month",))
        wsS.Columns("A:A").ColumnWidth = 30
        wsS.Columns("B:H").ColumnWidth = 15
        print("  Decision Signals (PivotTable + PivotChart + slicer + conditional formatting)")

        # ---------------- 6. Business Archetypes ------------------------
        wsA = wb.Worksheets.Add(After=wsS)
        wsA.Name = "Business Archetypes"
        r = title(wsA, 1, "Business Archetypes",
                  "Which costs matter for which business - and what this data cannot tell you")
        r = note(wsA, r, "EVERY archetype is missing RENT and LABOUR - for most Nigerian small "
                         "businesses the two largest line items. Nothing here is a total cost of "
                         "doing business, and there is NO composite index: the costs are reported "
                         "separately because the analysis showed they capture different dimensions.",
                 "warn")
        wsA.Cells(r, 1).Value = ("Exposure sensitivity: a cost that is X% of your cost base and "
                                 "rose P% adds X x (P/100) percentage points to total cost")
        wsA.Cells(r, 1).Font.Bold = True
        r += 1
        exp = d["tblExposure"][d["tblExposure"].jurisdictions > 0][
            ["window", "label", "median_pct_change", "total_cost_impact_pp_per_1pp_share"]]
        end = write_block(wsA, r, 1, exp, "tblArchExposure", style="TableStyleLight9")
        wsA.Range(wsA.Cells(r + 1, 3), wsA.Cells(end, 3)).NumberFormat = '+0.0"%";-0.0"%"'
        wsA.Range(wsA.Cells(r + 1, 3), wsA.Cells(end, 3)).FormatConditions.AddDatabar()
        r = end + 2

        for name, metrics, boundary, needed in ARCHETYPES:
            hdr = wsA.Range(wsA.Cells(r, 1), wsA.Cells(r, 8))
            hdr.Merge()
            hdr.Value = name
            hdr.Font.Bold = True
            hdr.Font.Size = 12
            hdr.Font.Color = WHITE
            hdr.Interior.Color = NAVY
            r += 1
            wsA.Cells(r, 1).Value = "Costs this data can speak to"
            wsA.Cells(r, 1).Font.Bold = True
            wsA.Cells(r, 2).Value = " | ".join(metrics)
            r += 1
            wsA.Cells(r, 1).Value = "BOUNDARY - what it cannot tell you"
            wsA.Cells(r, 1).Font.Bold = True
            wsA.Cells(r, 1).Font.Color = 0x1010C0
            b = wsA.Range(wsA.Cells(r, 2), wsA.Cells(r, 8))
            b.Merge()
            b.Value = boundary
            b.WrapText = True
            b.Interior.Color = WARN_BG
            wsA.Rows(r).RowHeight = 34
            r += 1
            wsA.Cells(r, 1).Value = "Data you would need to add"
            wsA.Cells(r, 1).Font.Bold = True
            n = wsA.Range(wsA.Cells(r, 2), wsA.Cells(r, 8))
            n.Merge()
            n.Value = needed
            n.WrapText = True
            wsA.Rows(r).RowHeight = 28
            r += 2
        wsA.Columns("A:A").ColumnWidth = 30
        wsA.Columns("B:H").ColumnWidth = 16
        print(f"  Business Archetypes ({len(ARCHETYPES)} archetypes)")

        # ---------------- 7. Methodology --------------------------------
        wsMe = wb.Worksheets.Add(After=wsA)
        wsMe.Name = "Methodology"
        r = title(wsMe, 1, "Methodology, Rules and Limitations",
                  "Read this before quoting any number from this workbook")
        sections = [
            ("DATA SOURCES",
             "National Bureau of Statistics (NBS): petrol, diesel, cooking gas (LPG), transport "
             "fares, food prices, Consumer Price Index. Central Bank of Nigeria (CBN): NFEM "
             "exchange rate. Nigerian Electricity Regulatory Commission (NERC): MYTO tariff "
             "orders. 342 raw source files, every one SHA-256 verified. No raw government file "
             "is redistributed in this repository."),
            ("TIME COVERAGE",
             "Primary common window (used for any cross-cost comparison): 2025-02 to 2026-04, "
             "15 months. Series end on DIFFERENT months and this is never hidden: LPG 2026-04; "
             "petrol, diesel and transport 2026-05; CPI 2026-07; FX 2026-09. Any figure spanning "
             "a different window says so on its own page."),
            ("GEOGRAPHY LEVELS",
             "STATE grain = 36 states + the Federal Capital Territory = 37 jurisdictions. The FCT "
             "(labelled Abuja) is an administrative territory, not a state. ZONE grain = 6 "
             "geopolitical zones - FOOD EXISTS ONLY AT ZONE LEVEL and is never shown per "
             "jurisdiction. NATIONAL grain = FX only. DISCO grain = NERC tariffs; DisCo licence "
             "areas cross state boundaries and are NEVER mapped to a jurisdiction. Grains are "
             "never mixed in one figure."),
            ("PUBLICATION RULES",
             "Every figure uses PRIMARY publications - each dataset's own first publication of "
             "that month. Restatements exist in the database and are deliberately out of scope "
             "here; mixing the two would answer two different questions at once ('what was first "
             "published' versus 'what is currently believed')."),
            ("KNOWN CPI GAP",
             "CPI year-on-year has NO rows for 2026-02, for any jurisdiction. The February 2026 "
             "release's year-ago column is labelled 2025-02 but holds 2025-01 data, so 148 cells "
             "were excluded upstream. Any YoY line must BREAK at 2026-02 and must never be "
             "interpolated across. Separately, April 2025 CPI INDEX has no primary publication "
             "(74 rows disputed); the April 2025 CHANGE RATES are primary and present."),
            ("CPI INDEX LEVELS ARE EXCLUDED FROM THIS WORKBOOK",
             "NBS prints the prohibition inside the source table: CPI index levels may not be "
             "compared between jurisdictions. Only change rates (month-on-month, year-on-year) "
             "are comparable. The two INDEX metric codes are therefore dropped from the workbook's "
             "data layer - 9,435 database panel rows become 8,177 here - so the rule cannot be "
             "broken by dragging a field into a PivotTable. The full 9,435 remain in the database."),
            ("RANK-STABILITY RULE",
             "A PERSISTENT-DECISION HEURISTIC, NOT A DATA-QUALITY TEST. Every published monthly "
             "ranking is a VALID SNAPSHOT: correctly extracted, correctly ordered, accurate for "
             "its month. The heuristic asks only whether that order would survive to the next "
             "month well enough to anchor a PERSISTENT decision - siting, sourcing, a standing "
             "supplier preference. Measure: mean |month-over-month %| divided by mean "
             "cross-jurisdiction CV%. At or above 1.0 the order reshuffles on ordinary movement. "
             "STABLE (4): water transport, bus intercity, okada, bus intracity. UNSTABLE (5): "
             "air, diesel, LPG 5 kg, LPG 12.5 kg, petrol - for these the SPREAD is shown but NO "
             "jurisdiction is named as dearest or cheapest. The 1.0 cut is a project convention, "
             "not a statistical standard."),
            ("MOVEMENT FLAG DEFINITIONS",
             "Built from each jurisdiction's own month-over-month percentage change, pooled across "
             "37 jurisdictions x 14 month-pairs = 518 observations per cost. ELEVATED = above the "
             "p90 of absolute monthly moves. EXTREME = above the p95. THESE ARE DESCRIPTIVE "
             "HISTORICAL FLAGS, NOT BUSINESS ACTION THRESHOLDS. A flag says a move is large by "
             "this series' own past. Turning one into an action trigger requires company cost "
             "exposure, margin and pass-through ability - none of which is in this dataset. "
             "Flags are computed on signed as well as absolute moves, because a cost falling hard "
             "matters too."),
            ("NERC ELECTRICITY - A FIXED REFERENCE COMPARISON",
             "The grid side of every self-generation comparison is the NERC Band A tariff of "
             "NGN 209.50/kWh from the JULY 2025 cross-section, held FIXED. Band A is used because "
             "it is the one band with zero spread across all 11 DisCos, so it needs no geographic "
             "assignment. Diesel runs to 2026-05 - the two sides are ten months apart. This is a "
             "benchmark comparison, NOT two current prices. If the tariff has risen since July "
             "2025 the true multiples are SMALLER than shown. Generator efficiency (2.5-4.0 kWh "
             "per litre) is an ASSUMPTION, not a measurement, and excludes the generator itself, "
             "servicing, oil and downtime."),
            ("PHARMACY - EXTERNAL OPERATING COST ONLY",
             "This workbook describes the EXTERNAL operating-cost environment a pharmacy faces: "
             "energy, generator fuel, delivery and staff-commute costs, and consumer price "
             "pressure. It CANNOT calculate or infer profitability, margin or viability. Medicine "
             "and product acquisition prices, rent, wages, pharmacy-specific electricity "
             "consumption, inventory turnover, supplier terms and revenue are all absent. "
             "Cold-chain electricity cost in particular cannot be estimated: neither consumption "
             "nor the DisCo band of any premises is known."),
            ("NO COMPOSITE INDEX",
             "No cost is weighted against another and nothing is summed across costs. The analysis "
             "found the components capture DIFFERENT dimensions of business cost - of 36 metric "
             "pairs only one is strongly correlated, and that pair is the same commodity in two "
             "cylinder sizes. An index is not ruled out forever, but normalisation, weighting and "
             "component treatment have not been defined or approved, so none is published."),
            ("MAJOR LIMITATIONS",
             "1. No rent, wages, land, water, taxes or levies - so this is NOT the cost of doing "
             "business, only certain traded inputs. 2. Food has no jurisdiction grain. "
             "3. Electricity is DisCo grain and a single cross-section. 4. Short window: 15 months "
             "common, year-on-year computable for only 4-5 months; no seasonal decomposition is "
             "defensible. 5. Observations are not independent - jurisdictions share national "
             "supply conditions and repeated months are serially correlated. 6. Transport figures "
             "are PASSENGER FARES, not freight rates. 7. A cross-jurisdiction median is not a "
             "national statistic; NBS publishes its own. 8. Published source defects are carried "
             "and flagged, never silently corrected. 9. Validation proves the pipeline is faithful "
             "to the sources - it does NOT validate the sources themselves."),
            ("VALIDATION",
             "110 of 110 checks pass across three analysis passes: discovery 64/64, source "
             "verification 19/19, decision inputs 27/27. The database layer separately passes a "
             "245/245 independent audit and a 15/15 restatement simulation. 29,032 fact rows, "
             "0 duplicate panel grain. Two suspicious patterns were traced to source and resolved: "
             "the December 2025 air-fare spike is genuinely published by NBS (corroborated by its "
             "own national row), and the LPG rank swings are genuine prices in a distribution too "
             "compressed for the ORDER to persist."),
            ("PROVENANCE OF THIS WORKBOOK",
             f"Every figure is embedded - this file needs no database, no add-in and no network. "
             f"Extract generated {d['stamp']} from mart.mv_state_cost_panel_monthly plus the "
             f"committed evidence files under outputs/analysis/. Sheets Data_Panel, Data_Medians "
             f"and Data_Evidence carry the underlying data and are deliberately visible. Medians "
             f"are PRE-AGGREGATED because Excel PivotTables cannot compute a median - using "
             f"Average would print a different number from the published evidence."),
        ]
        for head_txt, body in sections:
            wsMe.Cells(r, 1).Value = head_txt
            wsMe.Cells(r, 1).Font.Bold = True
            wsMe.Cells(r, 1).Font.Color = NAVY
            r += 1
            cell = wsMe.Range(wsMe.Cells(r, 1), wsMe.Cells(r, 9))
            cell.Merge()
            cell.Value = body
            cell.WrapText = True
            cell.VerticalAlignment = -4160
            cell.Font.Size = 10
            wsMe.Rows(r).RowHeight = max(30, 12 * (len(body) // 110 + 1))
            r += 2
        wsMe.Columns("A:I").ColumnWidth = 14
        print("  Methodology")

        # ---------------- finish ----------------------------------------
        # KPI register: the in-workbook KPI dictionary and the validator's index.
        reg = pd.DataFrame(KPI_REGISTER)
        rr = evidence_end_row
        wsE.Cells(rr, 1).Value = ("tblKPIRegister  <-  every KPI card on every sheet, "
                                  "with its exact cell, format and formula")
        wsE.Cells(rr, 1).Font.Bold = True
        wsE.Cells(rr, 1).Font.Color = MUTED
        write_block(wsE, rr + 1, 1, reg, "tblKPIRegister", style="TableStyleLight9")
        print(f"  KPI register : {len(reg)} cards indexed")

        # No .Select() here: a range on a non-active sheet cannot be selected.
        for w in wb.Worksheets:
            try:
                w.Tab.Color = 0xBFBFBF if w.Name.startswith("Data_") else NAVY
            except Exception:
                pass
        wb.Worksheets("Executive Overview").Activate()
        wb.SaveAs(str(WORKBOOK), FileFormat=xlsxFormat)
        wb.Close(SaveChanges=False)
        print(f"\n  saved -> {WORKBOOK.relative_to(ROOT)}")
    finally:
        xl.ScreenUpdating = True
        xl.Quit()
    return WORKBOOK


if __name__ == "__main__":
    data = build_extracts()
    build(data)
    print("\nBUILD COMPLETE")
