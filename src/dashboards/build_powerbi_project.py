"""Build the Nigeria Business Cost Intelligence Power BI project (PBIP).

    python src/dashboards/build_powerbi_project.py

Produces a version-control-friendly PBIP project under `powerbi/`:

    NBCI_Cost_Dashboard.pbip                  project pointer
    NBCI_Cost_Dashboard.SemanticModel/        TMDL, written by Microsoft's own serializer
    NBCI_Cost_Dashboard.Report/               PBIR - 7 pages, 108 visuals
    data/                                     the 32 CSVs the model reads

THE AUTOMATION ROUTE, AND WHY IT IS THIS ONE
--------------------------------------------
Nothing here hand-writes TMDL. The model is built as real Tabular Object Model objects
and serialised by `TmdlSerializer` - the same writer that ships inside the installed
Power BI Desktop - so the on-disk format is whatever that build itself produces. The
report is PBIR JSON generated against Microsoft's published schemas and validated
against them before Desktop ever sees it.

The pipeline runs in four steps, each of which fails loudly rather than producing a
plausible-looking wrong answer:

    1. pbi_model_data.py    extract + evidence -> powerbi/data/*.csv   (row counts asserted)
    2. pbi_model_spec.py    tables, columns, measures, relationships -> model_spec.json
    3. pbi_build_model.ps1  TOM -> TMDL, then DESERIALISE IT AGAIN to prove it round-trips
    4. pbi_report.py        PBIR pages and visuals

    then:  pbi_validate.ps1  opens it in Desktop and interrogates the live engine

WINDOWS POWERSHELL 5.1 IS REQUIRED for step 3. PowerShell 7 is .NET Core and the
WindowsApps ACL refuses to load Power BI's assemblies into it with "Access is denied".

THE ONE MACHINE-DEPENDENT SETTING is the `DataFolder` Power Query parameter, which holds
the absolute path of `powerbi/data`. Power Query has no relative-path concept, so a
parameter is the honest way to express this rather than pretending otherwise. It is a
single, documented value in `expressions.tmdl`, it contains no user name, and the
validator asserts it is the ONLY absolute path in the project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PBI = ROOT / "powerbi"
NAME = "NBCI_Cost_Dashboard"

sys.path.insert(0, str(HERE))

WIN_PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / \
    "WindowsPowerShell" / "v1.0" / "powershell.exe"


def banner(n: int, text: str) -> None:
    print("\n" + "=" * 74)
    print(f"STEP {n} - {text}")
    print("=" * 74)


def main() -> int:
    banner(1, "MODEL DATA (star schema + evidence + narrative)")
    import pbi_model_data
    tables = pbi_model_data.build_everything()
    written = pbi_model_data.write_all(tables)
    for nm, n in written:
        print(f"  {nm:26s} {n:>6,} rows")
    total_rows = sum(n for _, n in written)
    size_kb = sum(p.stat().st_size for p in (PBI / "data").glob("*.csv")) / 1024
    print(f"  -> {len(written)} tables, {total_rows:,} rows, {size_kb:,.0f} KB")

    banner(2, "SEMANTIC MODEL SPECIFICATION")
    import pbi_model_spec
    spec = pbi_model_spec.build_spec()
    out = PBI / "build"
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    n_cols = sum(len(t["columns"]) for t in spec["tables"])
    n_meas = sum(len(t["measures"]) for t in spec["tables"])
    print(f"  tables {len(spec['tables'])}  columns {n_cols}  measures {n_meas}  "
          f"relationships {len(spec['relationships'])} "
          f"(+{len(spec['relationshipsAbsentByDesign'])} absent by design)")
    print(f"  compatibilityLevel {spec['compatibilityLevel']}")

    banner(3, "TMDL VIA MICROSOFT'S OWN SERIALIZER")
    if not WIN_PS.exists():
        raise SystemExit(f"Windows PowerShell 5.1 not found at {WIN_PS}. "
                         "Step 3 cannot run under PowerShell 7 (see the module docstring).")
    r = subprocess.run(
        [str(WIN_PS), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(HERE / "pbi_build_model.ps1"),
         "-SpecPath", str(out / "model_spec.json"),
         "-OutPath", str(PBI / f"{NAME}.SemanticModel" / "definition")],
        capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip())
        raise SystemExit("TMDL serialisation failed")

    banner(4, "PBIR REPORT AND PROJECT SCAFFOLDING")
    import pbi_project_files
    for p in pbi_project_files.write_all():
        print(f"  {p.relative_to(ROOT)}")
    import pbi_report
    rep = pbi_report.write_report()
    for nm, cnt in rep["detail"]:
        print(f"  {nm:32s} {cnt:>3} visuals")
    print(f"  -> {rep['pages']} pages, {rep['visuals']} visuals")

    print("\n" + "=" * 74)
    print("BUILT. Nothing is proven until Desktop opens it:")
    print('  powershell.exe -NoProfile -ExecutionPolicy Bypass -File '
          r'"src\dashboards\pbi_validate.ps1"')
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
