"""PBIP project scaffolding: the .pbip pointer, item descriptors and .gitignore.

These are the small wrapper files around the two items Power BI Desktop actually opens -
the SemanticModel folder (TMDL, written by `pbi_build_model.ps1`) and the Report folder
(PBIR, written by `pbi_report.py`).

VERSION-CONTROL NOTES
---------------------
* Files are written UTF-8 **without BOM** and with **LF** endings. Power BI Desktop writes
  CRLF when it re-saves; `.gitattributes` normalises so a Desktop save is not a whole-file
  diff.
* `**/.pbi/localSettings.json` and `**/.pbi/cache.abf` are ignored - the first is per-user,
  the second is the data cache and would commit the data a second time.
* `logicalId` is a stable GUID derived from the item name, not a random one, so a rebuild
  does not churn the descriptor.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PBI = ROOT / "powerbi"
NAME = "NBCI_Cost_Dashboard"
SM = PBI / f"{NAME}.SemanticModel"
RPT = PBI / f"{NAME}.Report"

PLATFORM_SCHEMA = ("https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json")


def stable_guid(seed: str) -> str:
    """Deterministic GUID so rebuilding does not produce a spurious diff."""
    return str(uuid.UUID(bytes=hashlib.sha256(seed.encode()).digest()[:16]))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))          # utf-8, no BOM, LF


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_all() -> list[Path]:
    written: list[Path] = []

    # --- the root pointer -------------------------------------------------
    # NOTE the schema namespace: pbip/pbipProperties, NOT item/pbip/...
    # Every PBIR $schema is a `const` in the JSON schema and each file sets
    # additionalProperties:false, so a wrong URL or a stray property is a hard
    # validation failure, not a warning.
    pbip = PBI / f"{NAME}.pbip"
    write_json(pbip, {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    written.append(pbip)

    # --- semantic model item ---------------------------------------------
    # version 4.0+ is what permits the TMDL `definition/` folder; 1.0 forces TMSL.
    write_json(SM / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2",
        "settings": {},
    })
    written.append(SM / "definition.pbism")

    write_json(SM / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": stable_guid(f"{NAME}.SemanticModel")},
    })
    written.append(SM / ".platform")

    # --- report item ------------------------------------------------------
    # version "4.0" is what enables the PBIR `definition/` folder; "1.0" would force
    # the legacy single-blob report.json, which is undocumented and not externally
    # editable. byPath is relative and uses forward slashes even on Windows.
    write_json(RPT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}},
    })
    written.append(RPT / "definition.pbir")

    write_json(RPT / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": stable_guid(f"{NAME}.Report")},
    })
    written.append(RPT / ".platform")

    # --- repo hygiene -----------------------------------------------------
    write_text(PBI / ".gitignore", "\n".join([
        "# Power BI Desktop per-user state and the local data cache.",
        "# cache.abf holds the loaded data: committing it would store the CSVs twice.",
        "# editorSettings.json is Desktop's own preference file, written the first time",
        "# the project is opened. It is not part of the deliverable and differs per user.",
        "**/.pbi/",
        "",
        "# Intermediate build artefacts. model_spec.json regenerates from pbi_model_spec.py.",
        "build/",
        "",
    ]) + "\n")
    written.append(PBI / ".gitignore")

    write_text(PBI / ".gitattributes", "\n".join([
        "# Power BI Desktop writes CRLF. Normalise so a Desktop save is not a whole-file diff.",
        "*.tmdl   text eol=crlf",
        "*.pbir   text eol=crlf",
        "*.pbism  text eol=crlf",
        "*.pbip   text eol=crlf",
        "*.json   text eol=crlf",
        "*.csv    text eol=lf",
        "",
    ]) + "\n")
    written.append(PBI / ".gitattributes")

    return written


if __name__ == "__main__":
    for p in write_all():
        print(f"  {p.relative_to(ROOT)}")
