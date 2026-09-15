"""Clean the NBS Selected Food Price Watch releases into three canonical tables.

Source of record : data/raw/nbs/food/*.xlsx and the .xlsx members of .../food/*.zip
Outputs          : data/processed/nbs/food_price_national_monthly.csv
                   data/processed/nbs/food_price_zone_monthly.csv
                   data/processed/nbs/food_price_extreme_callout.csv

Implements the approved rules in docs/data_design/. In particular:

  * **the worksheet name is never used.** Two releases carry a stale one - both
    `selected_food_table_Mar_25.xlsx` and `selected_food_table_Apr25.xlsx` name their sheet
    `Selected Food Dec 2024`. Sheets are found by content: the main sheet is the one whose header
    row carries `Average of <month>-<yy>`, the zone sheet the one whose header carries
    `NORTH CENTRAL` (D-30).
  * **the release month needs three agreeing signals** - the current-month header, the prior-month
    header plus one month, and the year-ago header plus twelve - plus the file name as a fourth.
    Disagreement stops the run (D-30).
  * **periods are taken by column position**: 2 year-ago, 3 prior month, 4 current month. The
    published header text is kept verbatim in `source_period_label` and drives nothing.
  * **`MoM` and `YoY` are excluded.** They are literal Excel formulas - `=(D2-C2)/C2*100` and
    `=(D2-B2)/B2*100` - and never enter any table.
  * **the zone sheet publishes the release month**, proved arithmetically rather than by label:
    the national column D equals the state-count-weighted mean of the six zone averages in 713 of
    714 item-releases, and the prior-month column C matches in none (D-31).
  * **nothing published is corrected.** The March 2025 crate-of-eggs national average is
    arithmetically impossible against its own zone row and is written out unchanged, flagged
    `NATIONAL_ABOVE_ALL_ZONES` (D-32). Four July 2025 zone averages exceed the published state
    maximum and are written out unchanged, flagged `ZONE_ABOVE_STATE_MAXIMUM` (D-33).
  * **blank never becomes zero.** A blank cell is NULL with `value_status = 'NOT_REPORTED'`; no
    official source explains the absence, so no stronger claim is made (D-34).
  * callouts are parsed with one strict pattern, `State (number)`. No food callout in the corpus
    uses a slash or names more than one state, so no splitting rule is implemented; any future
    multi-state cell is a hard failure requiring inspection (D-35).
  * every published value keeps its precision; every price traces to exactly one spreadsheet cell.

Run from the project root:

    python src/cleaning/clean_nbs_food.py

Nothing under data/raw/ is opened for writing.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_DIR = RAW_ROOT / "nbs" / "food"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
REF_FOOD_ITEM = PROJECT_ROOT / "data" / "reference" / "ref_food_item.csv"
OUT_NATIONAL = PROJECT_ROOT / "data" / "processed" / "nbs" / "food_price_national_monthly.csv"
OUT_ZONE = PROJECT_ROOT / "data" / "processed" / "nbs" / "food_price_zone_monthly.csv"
OUT_CALLOUT = PROJECT_ROOT / "data" / "processed" / "nbs" / "food_price_extreme_callout.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_food_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

EXPECTED_RELEASES = 17
WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 5, 1)
EXPECTED_ITEMS = 42
EXPECTED_ZONES = 6
EXPECTED_STATES = 37
EXPECTED_PERIODS = 3

EXPECTED_NATIONAL_ROWS = EXPECTED_ITEMS * EXPECTED_PERIODS * EXPECTED_RELEASES   # 2142
EXPECTED_ZONE_ROWS = EXPECTED_ITEMS * EXPECTED_ZONES * EXPECTED_RELEASES         # 4284
EXPECTED_CALLOUT_ROWS = EXPECTED_ITEMS * 2 * EXPECTED_RELEASES                   # 1428

HEADER_ROW = 1
FIRST_ITEM_ROW = 2
LABEL_COLUMN = 1
PERIOD_COLUMNS = (2, 3, 4)          # year-ago, prior month, current month - BY POSITION
PERIOD_POSITIONS = ("YEAR_AGO", "PRIOR_MONTH", "CURRENT_MONTH")
DERIVED_COLUMNS = (5, 6)            # MoM, YoY - never extracted
DERIVED_HEADERS = ("mom", "yoy")
CALLOUT_COLUMNS = {7: "HIGHEST", 8: "LOWEST"}
ZONE_COLUMNS_RANGE = (2, 3, 4, 5, 6, 7)
ITEM_ANCHORS = ("item label", "item labels")
ZONE_ANCHOR = "north central"
PERIOD_ANCHOR = "average of"

ZONES = ("North Central", "North East", "North West",
         "South East", "South South", "South West")
ZONE_BY_KEY = {z.replace(" ", "").casefold(): z for z in ZONES}
# state counts per zone, from ref_state_zone.csv; Abuja counts in North Central
ZONE_STATE_COUNTS = {"North Central": 7, "North East": 6, "North West": 7,
                     "South East": 5, "South South": 6, "South West": 6}
NATIONAL_NAME = "Nigeria"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

CALLOUT_PATTERN = re.compile(r"^(?P<state>[^()]+?)\s*\(\s*(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*\)$")

# --- verified structural defects, keyed on the exact (container, member) fingerprint ------------
STALE_SHEET_NAME_FILES = {
    ("selected_food_table_Mar_25.xlsx", ""),
    ("selected_food_table_Apr25.xlsx", ""),
}
STALE_SHEET_NAME_FLAG = "STALE_SHEET_NAME"
PLURAL_HEADER_FILES = {("selected_food_table_Feb_25.xlsx", "")}
PLURAL_HEADER_FLAG = "HEADER_ITEM_LABELS_PLURAL"

# --- verified published-value anomalies. Values are preserved, never corrected ------------------
NATIONAL_ABOVE_ZONES_FLAG = "NATIONAL_ABOVE_ALL_ZONES"
MARCH_2025_EGG_ANOMALY = {
    "observation_month": "2025-03-01",
    "item_code": "EGG_AGRIC_CRATE30",
    "value_text": "7670.559190085271",
}

ZONE_ABOVE_STATE_MAX_FLAG = "ZONE_ABOVE_STATE_MAXIMUM"
# The four documented July 2025 item-releases whose zone averages break the published state
# bracket. They are counted at item-release grain (710 of 714 pass) ...
JULY_2025_BRACKET_ITEMS = {
    ("2025-07-01", "EGG_AGRIC_CRATE30"),
    ("2025-07-01", "CRAYFISH_SMALL_WHITE"),
    ("2025-07-01", "MILK_EVAP_THREECROWN_160G"),
    ("2025-07-01", "YAM_TUBER"),
}
# ... and flagged at the finer zone-cell grain, where those same four items put six individual
# zone averages outside the bracket. Three Crown Milk breaks it in three zones, not one.
JULY_2025_ZONE_CONFLICTS = {
    ("2025-07-01", "EGG_AGRIC_CRATE30", "South East"),
    ("2025-07-01", "CRAYFISH_SMALL_WHITE", "South West"),
    ("2025-07-01", "MILK_EVAP_THREECROWN_160G", "South East"),
    ("2025-07-01", "MILK_EVAP_THREECROWN_160G", "South South"),
    ("2025-07-01", "MILK_EVAP_THREECROWN_160G", "South West"),
    ("2025-07-01", "YAM_TUBER", "South South"),
}

# --- verified NULL pattern -----------------------------------------------------------------------
NO_YEAR_AGO_ITEMS = frozenset({
    "EGG_AGRIC_CRATE30", "BREAD_SLICED_450G", "BREAD_UNSLICED_450G", "CARROTS_FRESH",
    "CRAYFISH_SMALL_WHITE", "FISH_DRIED_BONGA", "GINGER_FRESH", "GOAT_MEAT_BONE_IN",
    "GROUNDNUT_OIL_75CL", "GROUNDNUTS_ROASTED_75CL", "RICE_LOCAL_BROKEN", "SEMOVITA_1KG",
    "FISH_SMOKED_MACKEREL", "MILK_EVAP_THREECROWN_160G", "WATERMELON_WHOLE",
})
NO_YEAR_AGO_LAST_RELEASE = dt.date(2025, 12, 1)   # from 2026-01 the year-ago column is complete
EXPECTED_YEAR_AGO_NULLS = 15 * 12                 # 180
EXPECTED_PRIOR_MONTH_NULLS = 15                   # January 2025 only
EXPECTED_NATIONAL_NULLS = EXPECTED_YEAR_AGO_NULLS + EXPECTED_PRIOR_MONTH_NULLS   # 195
STATUS_OK = "OK"
STATUS_BLANK = "NOT_REPORTED"

# --- reconciliation and revision tolerances ------------------------------------------------------
RECONCILE_TOLERANCE = 1e-9
EXPECTED_RECONCILE_COMPARISONS = EXPECTED_ITEMS * EXPECTED_RELEASES               # 714
EXPECTED_RECONCILE_EXCEPTIONS = 1
EXPECTED_EXTREME_BRACKET_COMPARISONS = EXPECTED_ITEMS * EXPECTED_RELEASES         # 714
EXPECTED_ZONE_BRACKET_EXCEPTIONS = 4

SUBSTANTIVE_REVISION_TOLERANCE = 1e-12
EXPECTED_PRIOR_MONTH_COMPARISONS = EXPECTED_ITEMS * (EXPECTED_RELEASES - 1)       # 672
EXPECTED_PRIOR_MONTH_IDENTICAL = 668
EXPECTED_PRIOR_MONTH_PRECISION = 0
EXPECTED_SUBSTANTIVE_REVISIONS = {
    ("2025-04-01", "EGG_AGRIC_CRATE30"),
    ("2025-07-01", "EGG_AGRIC_CRATE30"),
    ("2025-12-01", "EGG_AGRIC"),
    ("2025-12-01", "EGG_AGRIC_CRATE30"),
}
EXPECTED_YEAR_AGO_COMPARISONS = EXPECTED_ITEMS * 5                                # 210
EXPECTED_YEAR_AGO_IDENTICAL = 209
EXPECTED_YEAR_AGO_PRECISION = {("2025-01-01", "CHICKEN_FEET")}

NATIONAL_COLUMNS = [
    "observation_month", "release_month", "item_code", "item_label", "item_label_raw",
    "unit", "unit_source", "geography_type", "geography_name",
    "avg_price_ngn", "value_status", "period_position", "source_period_label",
    "is_primary_release", "source_anomaly", "header_row_used", "header_label_raw",
    "source_file", "source_member", "source_sheet", "source_row",
    "source_column_index", "source_cell_reference",
]
ZONE_COLUMNS = [
    "observation_month", "release_month", "item_code", "item_label", "item_label_raw",
    "unit", "unit_source", "geography_type", "zone", "zone_raw_label",
    "avg_price_ngn", "value_status", "observation_month_basis", "source_anomaly",
    "header_row_used", "source_file", "source_member", "source_sheet", "source_row",
    "source_column_index", "source_cell_reference",
]
CALLOUT_COLUMNS_OUT = [
    "observation_month", "release_month", "item_code", "item_label", "item_label_raw",
    "unit", "unit_source", "extreme_type", "geography_type", "state", "state_raw_label", "zone",
    "price_ngn", "is_shared_extreme", "raw_callout_text", "observation_month_basis",
    "source_anomaly", "header_row_used", "source_file", "source_member", "source_sheet",
    "source_row", "source_column_index", "source_cell_reference",
]


class ValidationError(AssertionError):
    """Raised when a validation check fails, so a broken run cannot ship a clean file."""


# ----------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_outside_raw(path: Path) -> Path:
    resolved = path.resolve()
    raw_root = RAW_ROOT.resolve()
    if resolved == raw_root or raw_root in resolved.parents:
        raise ValidationError(f"Refusing to write inside data/raw/: {resolved}")
    return resolved


def normalise(value) -> str:
    return " ".join(str(value).split()).casefold()


def text(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def load_state_lookup() -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    with REF_STATE_ZONE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = row["alias_normalised"]
            if key in lookup and lookup[key] != (row["state"], row["zone"]):
                raise ValidationError(
                    f"ref_state_zone alias {key!r} resolves to two different states")
            lookup[key] = (row["state"], row["zone"])
    return lookup


def load_item_lookup() -> tuple[dict[str, str], dict[str, dict]]:
    """alias (normalised) -> item_code, and item_code -> the reference row."""
    alias: dict[str, str] = {}
    items: dict[str, dict] = {}
    with REF_FOOD_ITEM.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row["item_code"]
            if code in items:
                raise ValidationError(f"ref_food_item duplicate item_code {code!r}")
            if row["unit"] and not row["unit_source"]:
                raise ValidationError(f"ref_food_item {code!r} has a unit with no unit_source")
            if row["unit_source"] and not row["unit_evidence"]:
                raise ValidationError(f"ref_food_item {code!r} has a source with no evidence")
            items[code] = row
            for a in [p.strip() for p in row["observed_aliases"].split("|") if p.strip()]:
                key = normalise(a)
                if key in alias and alias[key] != code:
                    raise ValidationError(f"ref_food_item alias {key!r} maps to two item codes")
                alias[key] = code
    return alias, items


STATE_LOOKUP = load_state_lookup()
ITEM_ALIAS, ITEM_REF = load_item_lookup()


# ----------------------------------------------------------------------------
def iter_workbooks():
    for path in sorted(RAW_DIR.iterdir()):
        if path.suffix.lower() == ".xlsx":
            yield path.name, "", path.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith(".xlsx") and not name.startswith("__MACOSX"):
                        yield path.name, name, archive.read(name)


def read_sheets(data: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in wb.sheetnames:
            yield sheet, [tuple(r) for r in wb[sheet].iter_rows(values_only=True)]
    finally:
        wb.close()


def cell(grid, row_idx: int, col_idx: int):
    if row_idx < 1 or row_idx > len(grid):
        return None
    row = grid[row_idx - 1]
    return row[col_idx - 1] if 1 <= col_idx <= len(row) else None


def parse_period(value) -> dt.date | None:
    m = re.search(r"([A-Za-z]+)[-\s]+(\d{2,4})\s*$", text(value))
    if not m:
        return None
    mon = m.group(1)[:3].casefold()
    if mon not in MONTHS:
        return None
    year = int(m.group(2))
    return dt.date(2000 + year if year < 100 else year, MONTHS[mon], 1)


def parse_name_month(name: str) -> dt.date | None:
    cleaned = name.replace("_", " ").replace("-", " ")
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{2,4})\b",
                  cleaned, re.IGNORECASE)
    if not m:
        return None
    year = int(m.group(2))
    return dt.date(2000 + year if year < 100 else year, MONTHS[m.group(1).casefold()], 1)


def add_months(day: dt.date, n: int) -> dt.date:
    idx = day.month - 1 + n
    return dt.date(day.year + idx // 12, idx % 12 + 1, 1)


def number_text(value) -> str:
    """Published value as text, precision unchanged. Blank stays NULL, never 0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValidationError(f"Boolean where a price was expected: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    body = str(value).strip()
    if body == "":
        return ""
    raise ValidationError(f"Non-numeric value where a price was expected: {value!r}")


def content_extent(grid) -> tuple[int, int]:
    last_row = last_col = 0
    for r, row in enumerate(grid, 1):
        for c, value in enumerate(row, 1):
            if value is not None and str(value).strip() != "":
                last_row, last_col = max(last_row, r), max(last_col, c)
    return last_row, last_col


def resolve_item(raw_label: str, where: str) -> tuple[str, dict]:
    code = ITEM_ALIAS.get(normalise(raw_label))
    if code is None:
        raise ValidationError(
            f"{where}: item label {raw_label!r} does not resolve through ref_food_item.csv. "
            f"Add it deliberately or exclude it deliberately - never silently.")
    return code, ITEM_REF[code]


def parse_callout(raw: str, where: str) -> tuple[str, str]:
    body = text(raw)
    if body == "":
        raise ValidationError(f"{where}: empty extreme callout")
    if "/" in body or "," in body.split("(")[0]:
        raise ValidationError(
            f"{where}: callout {body!r} names more than one state. No food release in the "
            f"inspected corpus does this; stop and inspect rather than split it (D-35).")
    m = CALLOUT_PATTERN.match(body)
    if not m:
        raise ValidationError(f"{where}: callout {body!r} does not match 'State (number)'")
    return m.group("state").strip(), m.group("value").replace(",", "")


# ----------------------------------------------------------------------------
def locate_sheets(container: str, member: str, data: bytes):
    """Find the two sheets by content. The worksheet name is never used (D-30)."""
    main = zone = None
    for sheet, grid in read_sheets(data):
        header = [text(cell(grid, HEADER_ROW, c)) for c in range(1, 16)]
        lowered = [h.casefold() for h in header]
        if any(h.startswith(ZONE_ANCHOR) for h in lowered):
            if zone is not None:
                raise ValidationError(f"{container}/{member}: two zone sheets")
            zone = (sheet, grid, header)
        elif any(PERIOD_ANCHOR in h for h in lowered):
            if main is not None:
                raise ValidationError(f"{container}/{member}: two main sheets")
            main = (sheet, grid, header)
    if main is None or zone is None:
        raise ValidationError(f"{container}/{member}: expected one main and one zone sheet")
    for name, (_, _, header) in (("main", main), ("zone", zone)):
        if normalise(header[0]) not in ITEM_ANCHORS:
            raise ValidationError(
                f"{container}/{member}: {name} sheet A1 is {header[0]!r}, "
                f"not an accepted item anchor {ITEM_ANCHORS}")
    return main, zone


def derive_release_month(container, member, main_header, sheet_name):
    """Three header signals must agree; the file name is a fourth. The sheet name is evidence only."""
    labels = [text(main_header[c - 1]) for c in PERIOD_COLUMNS]
    parsed = [parse_period(t) for t in labels]
    if any(p is None for p in parsed):
        raise ValidationError(f"{container}/{member}: unparseable period header in {labels!r}")
    year_ago, prior, current = parsed
    from_prior = add_months(prior, 1)
    from_year_ago = add_months(year_ago, 12)
    if not (from_prior == current == from_year_ago):
        raise ValidationError(
            f"{container}/{member}: release-month signals disagree - current header {current}, "
            f"prior+1 {from_prior}, year-ago+12 {from_year_ago}")
    from_name = parse_name_month(member or container)
    if from_name != current:
        raise ValidationError(
            f"{container}/{member}: file name implies {from_name}, headers imply {current}")
    return current, labels, parse_name_month(sheet_name)


def extract_all():
    national: list[dict] = []
    zone_rows: list[dict] = []
    callouts: list[dict] = []
    notes: list[dict] = []

    for container, member, data in iter_workbooks():
        fingerprint = (container, member)
        main, zone = locate_sheets(container, member, data)
        main_sheet, main_grid, main_header = main
        zone_sheet, zone_grid, zone_header = zone

        release, period_labels, sheet_month = derive_release_month(
            container, member, main_header, main_sheet)
        release_text = release.isoformat()

        anomalies = []
        if fingerprint in STALE_SHEET_NAME_FILES:
            anomalies.append(STALE_SHEET_NAME_FLAG)
        if fingerprint in PLURAL_HEADER_FILES:
            anomalies.append(PLURAL_HEADER_FLAG)
        if (sheet_month != release) != (fingerprint in STALE_SHEET_NAME_FILES):
            raise ValidationError(
                f"{container}/{member}: sheet name {main_sheet!r} implies {sheet_month} but the "
                f"file is {'' if fingerprint in STALE_SHEET_NAME_FILES else 'not '}on the "
                f"documented stale-name list")
        if (normalise(main_header[0]) == "item labels") != (fingerprint in PLURAL_HEADER_FILES):
            raise ValidationError(
                f"{container}/{member}: plural header anchor does not match the documented list")

        # derived columns must be where the design says they are, and are then excluded
        for offset, col in enumerate(DERIVED_COLUMNS):
            got = normalise(main_header[col - 1])
            if got != DERIVED_HEADERS[offset]:
                raise ValidationError(
                    f"{container}/{member}: column {col} header is {got!r}, "
                    f"expected {DERIVED_HEADERS[offset]!r} - refusing to guess which columns "
                    f"are derived")

        main_extent = content_extent(main_grid)
        zone_extent = content_extent(zone_grid)
        if main_extent[1] > max(CALLOUT_COLUMNS):
            raise ValidationError(f"{container}/{member}: main sheet has content right of column 8")
        if zone_extent[1] > max(ZONE_COLUMNS_RANGE):
            raise ValidationError(f"{container}/{member}: zone sheet has content right of column 7")

        # zone header must be the six canonical zones, in order
        zone_names = []
        for idx, col in enumerate(ZONE_COLUMNS_RANGE):
            raw = text(zone_header[col - 1])
            canonical = ZONE_BY_KEY.get(normalise(raw).replace(" ", ""))
            if canonical is None:
                raise ValidationError(f"{container}/{member}: zone header {raw!r} is not a zone")
            if canonical != ZONES[idx]:
                raise ValidationError(
                    f"{container}/{member}: zone column {col} is {canonical}, expected {ZONES[idx]}")
            zone_names.append((canonical, raw))

        # ---- walk the two tables by content -------------------------------------------------
        main_items, zone_items = [], []
        for row in range(FIRST_ITEM_ROW, main_extent[0] + 1):
            raw = text(cell(main_grid, row, LABEL_COLUMN))
            if raw == "":
                raise ValidationError(f"{container}/{member}: blank item label at main row {row}")
            main_items.append((row, raw))
        for row in range(FIRST_ITEM_ROW, zone_extent[0] + 1):
            raw = text(cell(zone_grid, row, LABEL_COLUMN))
            if raw == "":
                raise ValidationError(f"{container}/{member}: blank item label at zone row {row}")
            zone_items.append((row, raw))

        for name, items in (("main", main_items), ("zone", zone_items)):
            if len(items) != EXPECTED_ITEMS:
                raise ValidationError(
                    f"{container}/{member}: {name} sheet has {len(items)} items, "
                    f"expected {EXPECTED_ITEMS}")

        main_codes = [resolve_item(r, f"{container}/{member} main r{row}")[0]
                      for row, r in main_items]
        zone_codes = [resolve_item(r, f"{container}/{member} zone r{row}")[0]
                      for row, r in zone_items]
        if main_codes != zone_codes:
            diff = [i for i, (a, b) in enumerate(zip(main_codes, zone_codes)) if a != b]
            raise ValidationError(
                f"{container}/{member}: main and zone sheets list different items at {diff}")

        header_label_raw = text(main_header[0])

        # ---- national ------------------------------------------------------------------------
        for (row, raw_label), code in zip(main_items, main_codes):
            ref = ITEM_REF[code]
            for idx, col in enumerate(PERIOD_COLUMNS):
                value = cell(main_grid, row, col)
                value_text = number_text(value)
                observation = parse_period(period_labels[idx])
                row_flags = list(anomalies)
                if (observation.isoformat() == MARCH_2025_EGG_ANOMALY["observation_month"]
                        and code == MARCH_2025_EGG_ANOMALY["item_code"]
                        and value_text == MARCH_2025_EGG_ANOMALY["value_text"]):
                    row_flags.append(NATIONAL_ABOVE_ZONES_FLAG)
                national.append({
                    "observation_month": observation.isoformat(),
                    "release_month": release_text,
                    "item_code": code,
                    "item_label": ref["item_label"],
                    "item_label_raw": raw_label,
                    "unit": ref["unit"],
                    "unit_source": ref["unit_source"],
                    "geography_type": "NATIONAL",
                    "geography_name": NATIONAL_NAME,
                    "avg_price_ngn": value_text,
                    "value_status": STATUS_OK if value_text else STATUS_BLANK,
                    "period_position": PERIOD_POSITIONS[idx],
                    "source_period_label": period_labels[idx],
                    "is_primary_release": "TRUE" if observation == release else "FALSE",
                    "source_anomaly": "|".join(row_flags),
                    "header_row_used": HEADER_ROW,
                    "header_label_raw": header_label_raw,
                    "source_file": container,
                    "source_member": member,
                    "source_sheet": main_sheet,
                    "source_row": row,
                    "source_column_index": col,
                    "source_cell_reference": f"{get_column_letter(col)}{row}",
                })

            # ---- callouts --------------------------------------------------------------------
            for col, extreme in CALLOUT_COLUMNS.items():
                raw = text(cell(main_grid, row, col))
                where = f"{container}/{member} {main_sheet} {get_column_letter(col)}{row}"
                state_raw, value_text = parse_callout(raw, where)
                key = normalise(state_raw)
                if key not in STATE_LOOKUP:
                    raise ValidationError(
                        f"{where}: state {state_raw!r} does not resolve through ref_state_zone.csv")
                state, state_zone = STATE_LOOKUP[key]
                callouts.append({
                    "observation_month": release_text,
                    "release_month": release_text,
                    "item_code": code,
                    "item_label": ref["item_label"],
                    "item_label_raw": raw_label,
                    "unit": ref["unit"],
                    "unit_source": ref["unit_source"],
                    "extreme_type": extreme,
                    "geography_type": "STATE",
                    "state": state,
                    "state_raw_label": state_raw,
                    "zone": state_zone,
                    "price_ngn": value_text,
                    "is_shared_extreme": "FALSE",
                    "raw_callout_text": raw,
                    "observation_month_basis": "RELEASE_CURRENT_PERIOD_COLUMN",
                    "source_anomaly": "|".join(anomalies),
                    "header_row_used": HEADER_ROW,
                    "source_file": container,
                    "source_member": member,
                    "source_sheet": main_sheet,
                    "source_row": row,
                    "source_column_index": col,
                    "source_cell_reference": f"{get_column_letter(col)}{row}",
                })

        # ---- zone ------------------------------------------------------------------------------
        for (row, raw_label), code in zip(zone_items, zone_codes):
            ref = ITEM_REF[code]
            for idx, col in enumerate(ZONE_COLUMNS_RANGE):
                canonical, raw_zone = zone_names[idx]
                value_text = number_text(cell(zone_grid, row, col))
                row_flags = list(anomalies)
                if (release_text, code, canonical) in JULY_2025_ZONE_CONFLICTS:
                    row_flags.append(ZONE_ABOVE_STATE_MAX_FLAG)
                zone_rows.append({
                    "observation_month": release_text,
                    "release_month": release_text,
                    "item_code": code,
                    "item_label": ref["item_label"],
                    "item_label_raw": raw_label,
                    "unit": ref["unit"],
                    "unit_source": ref["unit_source"],
                    "geography_type": "ZONE",
                    "zone": canonical,
                    "zone_raw_label": raw_zone,
                    "avg_price_ngn": value_text,
                    "value_status": STATUS_OK if value_text else STATUS_BLANK,
                    "observation_month_basis": "RELEASE_CURRENT_PERIOD_COLUMN",
                    "source_anomaly": "|".join(row_flags),
                    "header_row_used": HEADER_ROW,
                    "source_file": container,
                    "source_member": member,
                    "source_sheet": zone_sheet,
                    "source_row": row,
                    "source_column_index": col,
                    "source_cell_reference": f"{get_column_letter(col)}{row}",
                })

        notes.append({
            "release_month": release_text,
            "source_file": container,
            "source_member": member,
            "main_sheet": main_sheet,
            "zone_sheet": zone_sheet,
            "sheet_name_month": sheet_month.isoformat() if sheet_month else "",
            "header_label_raw": header_label_raw,
            "period_labels": period_labels,
            "main_extent": main_extent,
            "zone_extent": zone_extent,
            "anomalies": "|".join(anomalies),
        })

    return national, zone_rows, callouts, notes


# ----------------------------------------------------------------------------
def weighted_reconciliation(national, zone_rows):
    """national == sum(zone * states_in_zone) / 37, per item-release (D-31)."""
    zone_index = defaultdict(dict)
    for r in zone_rows:
        zone_index[(r["release_month"], r["item_code"])][r["zone"]] = r["avg_price_ngn"]
    results = []
    for r in national:
        if r["period_position"] != "CURRENT_MONTH":
            continue
        zones = zone_index.get((r["release_month"], r["item_code"]), {})
        if len(zones) != EXPECTED_ZONES or not r["avg_price_ngn"]:
            results.append((r, None, None))
            continue
        implied = sum(float(zones[z]) * ZONE_STATE_COUNTS[z] for z in ZONES) / sum(
            ZONE_STATE_COUNTS.values())
        published = float(r["avg_price_ngn"])
        error = abs(implied - published) / abs(published) if published else None
        results.append((r, implied, error))
    return results


def extreme_bracket(national, callouts, zone_rows):
    """Lowest <= national <= Highest, and every zone average inside the same bracket."""
    extremes = defaultdict(dict)
    for r in callouts:
        extremes[(r["release_month"], r["item_code"])][r["extreme_type"]] = float(r["price_ngn"])
    zone_index = defaultdict(dict)
    for r in zone_rows:
        zone_index[(r["release_month"], r["item_code"])][r["zone"]] = float(r["avg_price_ngn"])

    national_fail, zone_fail, structure, compared = [], [], [], 0
    for r in national:
        if r["period_position"] != "CURRENT_MONTH" or not r["avg_price_ngn"]:
            continue
        key = (r["release_month"], r["item_code"])
        pair = extremes.get(key, {})
        if set(pair) != {"HIGHEST", "LOWEST"}:
            # never raise from a helper: that would discard the failures validate() has already
            # collected and report only this one
            structure.append((key, sorted(pair)))
            continue
        low, high = pair["LOWEST"], pair["HIGHEST"]
        compared += 1
        if not (low <= float(r["avg_price_ngn"]) <= high):
            national_fail.append((key, low, float(r["avg_price_ngn"]), high))
        zones = zone_index.get(key, {})
        offenders = sorted(z for z, v in zones.items() if not (low <= v <= high))
        if offenders:
            zone_fail.append((key, low, high, offenders,
                              {z: zones[z] for z in offenders}))
    return compared, national_fail, zone_fail, structure


def classify_difference(earlier: str, later: str) -> str:
    if earlier == later:
        return "identical"
    a, b = float(earlier), float(later)
    if a == b:
        return "identical"
    if a != 0 and abs(a - b) / abs(a) < SUBSTANTIVE_REVISION_TOLERANCE:
        return "precision"
    return "substantive"


def cross_release(national, position: str, offset: int):
    published = {}
    for r in national:
        if r["period_position"] == "CURRENT_MONTH":
            published[(r["release_month"], r["item_code"])] = r["avg_price_ngn"]
    compared = Counter()
    precision, substantive, blanks = [], [], []
    for r in national:
        if r["period_position"] != position:
            continue
        release = dt.date.fromisoformat(r["release_month"])
        source = add_months(release, -offset).isoformat()
        earlier = published.get((source, r["item_code"]))
        if earlier is None:
            continue
        later = r["avg_price_ngn"]
        if earlier == "" or later == "":
            compared["one blank" if earlier != later else "both blank"] += 1
            if earlier != later:
                blanks.append((source, r["release_month"], r["item_code"], earlier, later))
            continue
        kind = classify_difference(earlier, later)
        compared[kind] += 1
        entry = (r["observation_month"], r["item_code"], earlier, later)
        if kind == "precision":
            precision.append(entry)
        elif kind == "substantive":
            substantive.append(entry)
    return compared, precision, substantive, blanks


def verify_manifest(path: Path, hash_field: str, prefix: str) -> tuple[int, list[str]]:
    bad, count = [], 0
    if not path.exists():
        return 0, [f"MISSING MANIFEST {path.name}"]
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rel = row["destination_path"].replace(chr(92), "/")
            if not rel.startswith(prefix):
                continue
            count += 1
            target = PROJECT_ROOT / rel
            if not target.exists():
                bad.append(f"MISSING {rel}")
            elif sha256_file(target) != row[hash_field]:
                bad.append(f"CHANGED {rel}")
    return count, bad


def re_read_check(national, zone_rows, callouts) -> list[str]:
    wanted = defaultdict(list)
    for r in national + zone_rows:
        wanted[(r["source_file"], r["source_member"], r["source_sheet"])].append(
            (r, "avg_price_ngn"))
    for r in callouts:
        wanted[(r["source_file"], r["source_member"], r["source_sheet"])].append(
            (r, "raw_callout_text"))
    problems = []
    for container, member, data in iter_workbooks():
        for sheet, grid in read_sheets(data):
            key = (container, member, sheet)
            if key not in wanted:
                continue
            for r, field in wanted[key]:
                original = cell(grid, int(r["source_row"]), int(r["source_column_index"]))
                got = text(original) if field == "raw_callout_text" else number_text(original)
                if got != r[field]:
                    problems.append(
                        f"{container}:{sheet}:{r['source_cell_reference']} "
                        f"re-read {got!r} but wrote {r[field]!r}")
    return problems


# ----------------------------------------------------------------------------
def validate(national, zone_rows, callouts, notes) -> list[str]:
    failures: list[str] = []
    passed: list[str] = []

    def check(number, title, ok, detail=""):
        line = f"{number:2d}. {title}"
        if ok:
            passed.append(f"{line} - PASS{(' - ' + detail) if detail else ''}")
        else:
            failures.append(f"{line} - FAIL - {detail}")

    releases = [dt.date.fromisoformat(n["release_month"]) for n in notes]
    expected_months = []
    cursor = WINDOW_START
    while cursor <= WINDOW_END:
        expected_months.append(cursor)
        cursor = add_months(cursor, 1)

    check(1, "17 releases, 2025-01 to 2026-05, contiguous and unique",
          sorted(releases) == expected_months,
          f"got {len(releases)} releases: {sorted({str(r) for r in releases})}")

    check(2, "every workbook yields exactly one main sheet and one zone sheet located by content",
          all(n["main_sheet"] and n["zone_sheet"] for n in notes)
          and len({n["zone_sheet"] for n in notes}) == 1,
          f"zone sheet names: {sorted({n['zone_sheet'] for n in notes})}")

    stale = {(n["source_file"], n["source_member"]) for n in notes
             if STALE_SHEET_NAME_FLAG in n["anomalies"]}
    check(3, "the worksheet name disagrees with the headers in exactly the two documented files",
          stale == STALE_SHEET_NAME_FILES, f"got {sorted(stale)}")

    plural = {(n["source_file"], n["source_member"]) for n in notes
              if PLURAL_HEADER_FLAG in n["anomalies"]}
    check(4, "the plural 'Item Labels' anchor appears in exactly one documented file",
          plural == PLURAL_HEADER_FILES, f"got {sorted(plural)}")

    check(5, "three period labels per release, and all three release-month signals agreed",
          all(len(n["period_labels"]) == EXPECTED_PERIODS for n in notes),
          "derive_release_month raises on disagreement")

    check(6, "no content below row 43 or right of column 8 in any sheet",
          all(n["main_extent"][0] == 43 and n["main_extent"][1] <= 8
              and n["zone_extent"][0] == 43 and n["zone_extent"][1] <= 7 for n in notes),
          f"extents seen: {sorted({(n['main_extent'], n['zone_extent']) for n in notes})}")

    check(7, "42 items per sheet per release, identical order in both sheets",
          all(Counter(r["release_month"] for r in national)[str(m)] ==
              EXPECTED_ITEMS * EXPECTED_PERIODS for m in expected_months),
          "extract_all raises on a mismatch")

    unresolved = {r["item_label_raw"] for r in national + zone_rows
                  if r["item_code"] not in ITEM_REF}
    check(8, "every item label resolves through ref_food_item.csv",
          not unresolved, f"unresolved: {sorted(unresolved)}")

    codes = {r["item_code"] for r in national}
    check(9, "all 42 reference item codes are present and none is invented",
          codes == set(ITEM_REF), f"missing {sorted(set(ITEM_REF)-codes)}, extra {sorted(codes-set(ITEM_REF))}")

    # Columns 5 and 6 are MoM/YoY on the main sheet but South East / South South on the zone
    # sheet, so the check is per table, against that table's own permitted columns.
    off_column = (
        [r for r in national if int(r["source_column_index"]) not in PERIOD_COLUMNS]
        + [r for r in callouts if int(r["source_column_index"]) not in CALLOUT_COLUMNS]
        + [r for r in zone_rows if int(r["source_column_index"]) not in ZONE_COLUMNS_RANGE]
    )
    main_sheets = {n["main_sheet"] for n in notes}
    derived_leak = [r for r in national + zone_rows + callouts
                    if r["source_sheet"] in main_sheets
                    and int(r["source_column_index"]) in DERIVED_COLUMNS]
    check(10, "no row is sourced from a derived MoM/YoY column, and every row comes from a "
              "column its own table permits",
          not off_column and not derived_leak,
          f"off-column {len(off_column)}, derived leak {len(derived_leak)}")

    check(11, f"national row count == {EXPECTED_NATIONAL_ROWS}",
          len(national) == EXPECTED_NATIONAL_ROWS, f"got {len(national)}")
    check(12, f"zone row count == {EXPECTED_ZONE_ROWS}",
          len(zone_rows) == EXPECTED_ZONE_ROWS, f"got {len(zone_rows)}")
    check(13, f"callout row count == {EXPECTED_CALLOUT_ROWS}",
          len(callouts) == EXPECTED_CALLOUT_ROWS, f"got {len(callouts)}")

    nat_key = Counter((r["release_month"], r["observation_month"], r["item_code"]) for r in national)
    check(14, "national primary key (release_month, observation_month, item_code) is unique",
          all(v == 1 for v in nat_key.values()),
          f"duplicates: {[k for k, v in nat_key.items() if v > 1][:3]}")

    zone_key = Counter((r["observation_month"], r["item_code"], r["zone"]) for r in zone_rows)
    check(15, "zone primary key (observation_month, item_code, zone) is unique",
          all(v == 1 for v in zone_key.values()),
          f"duplicates: {[k for k, v in zone_key.items() if v > 1][:3]}")

    call_key = Counter((r["observation_month"], r["item_code"], r["extreme_type"], r["state"])
                       for r in callouts)
    check(16, "callout primary key (observation_month, item_code, extreme_type, state) is unique",
          all(v == 1 for v in call_key.values()),
          f"duplicates: {[k for k, v in call_key.items() if v > 1][:3]}")

    nulls = [r for r in national if r["avg_price_ngn"] == ""]
    year_ago_nulls = [r for r in nulls if r["period_position"] == "YEAR_AGO"]
    prior_nulls = [r for r in nulls if r["period_position"] == "PRIOR_MONTH"]
    current_nulls = [r for r in nulls if r["period_position"] == "CURRENT_MONTH"]
    check(17, f"exactly {EXPECTED_NATIONAL_NULLS} NULL national prices, in the documented pattern",
          (len(nulls) == EXPECTED_NATIONAL_NULLS
           and len(year_ago_nulls) == EXPECTED_YEAR_AGO_NULLS
           and len(prior_nulls) == EXPECTED_PRIOR_MONTH_NULLS
           and not current_nulls),
          f"total {len(nulls)}, year-ago {len(year_ago_nulls)}, prior {len(prior_nulls)}, "
          f"current {len(current_nulls)}")

    bad_pattern = []
    for r in year_ago_nulls:
        if r["item_code"] not in NO_YEAR_AGO_ITEMS:
            bad_pattern.append(("unexpected item", r["release_month"], r["item_code"]))
        if dt.date.fromisoformat(r["release_month"]) > NO_YEAR_AGO_LAST_RELEASE:
            bad_pattern.append(("2026 release", r["release_month"], r["item_code"]))
    per_release = Counter(r["release_month"] for r in year_ago_nulls)
    for month in expected_months:
        want = 15 if month <= NO_YEAR_AGO_LAST_RELEASE else 0
        if per_release[month.isoformat()] != want:
            bad_pattern.append(("wrong count", month.isoformat(), per_release[month.isoformat()]))
    check(18, "year-ago NULLs are 15 per release for 2025-01..2025-12 and none from 2026-01",
          not bad_pattern, f"{bad_pattern[:4]}")

    check(19, "the January 2025 prior-month NULLs are the same 15 items",
          {r["item_code"] for r in prior_nulls} == NO_YEAR_AGO_ITEMS
          and {r["release_month"] for r in prior_nulls} == {"2025-01-01"},
          f"{sorted({r['item_code'] for r in prior_nulls})}")

    statuses = Counter(r["value_status"] for r in national + zone_rows)
    mislabelled = [r for r in national + zone_rows
                   if (r["avg_price_ngn"] == "") != (r["value_status"] == STATUS_BLANK)]
    check(20, f"value_status is only {STATUS_OK}/{STATUS_BLANK} and matches emptiness exactly",
          set(statuses) <= {STATUS_OK, STATUS_BLANK} and not mislabelled, f"{dict(statuses)}")

    zeroes = [r for r in national + zone_rows
              if r["avg_price_ngn"] not in ("",) and float(r["avg_price_ngn"]) == 0]
    check(21, "no blank was ever turned into a zero",
          not zeroes, f"{len(zeroes)} zero-valued prices")

    check(22, "zone table has no NULLs and exactly six canonical zones per item-release",
          not [r for r in zone_rows if r["avg_price_ngn"] == ""]
          and all(v == EXPECTED_ZONES for v in
                  Counter((r["release_month"], r["item_code"]) for r in zone_rows).values()),
          "")

    states = {r["state"] for r in callouts}
    check(23, f"all callout states resolve and all {EXPECTED_STATES} appear at least once",
          len(states) == EXPECTED_STATES, f"{len(states)} distinct states")

    shared = [r for r in callouts if r["is_shared_extreme"] != "FALSE"]
    slashes = [r for r in callouts if "/" in r["raw_callout_text"]]
    types = Counter(r["extreme_type"] for r in callouts)
    pairing = Counter((r["release_month"], r["item_code"], r["extreme_type"]) for r in callouts)
    n_compared, nat_fail, zone_fail, structure = extreme_bracket(national, callouts, zone_rows)
    check(24, "exactly one HIGHEST and one LOWEST per item-release, each naming a single state; "
              "no third category, no ties, no slashes",
          (not shared and not slashes and not structure
           and set(types) == {"HIGHEST", "LOWEST"}
           and types["HIGHEST"] == types["LOWEST"] == EXPECTED_ITEMS * EXPECTED_RELEASES
           and all(v == 1 for v in pairing.values())),
          f"shared {len(shared)}, slashes {len(slashes)}, categories {dict(types)}, "
          f"broken pairs {structure[:3]}, repeated {[k for k, v in pairing.items() if v > 1][:3]}")

    recon = weighted_reconciliation(national, zone_rows)
    compared = [x for x in recon if x[2] is not None]
    breaches = [x for x in compared if x[2] > RECONCILE_TOLERANCE]
    documented = {(MARCH_2025_EGG_ANOMALY["observation_month"], MARCH_2025_EGG_ANOMALY["item_code"])}
    got = {(x[0]["observation_month"], x[0]["item_code"]) for x in breaches}
    check(25, f"national == weighted zone mean within {RECONCILE_TOLERANCE:g} in "
              f"{EXPECTED_RECONCILE_COMPARISONS - EXPECTED_RECONCILE_EXCEPTIONS} of "
              f"{EXPECTED_RECONCILE_COMPARISONS} item-releases",
          (len(compared) == EXPECTED_RECONCILE_COMPARISONS
           and len(breaches) == EXPECTED_RECONCILE_EXCEPTIONS and got == documented),
          f"compared {len(compared)}, breaches {len(breaches)} at {sorted(got)}")

    flagged = {(r["observation_month"], r["item_code"]) for r in national
               if NATIONAL_ABOVE_ZONES_FLAG in r["source_anomaly"]}
    anomaly_rows = [r for r in national if NATIONAL_ABOVE_ZONES_FLAG in r["source_anomaly"]]
    check(26, "the March 2025 crate-of-eggs anomaly is preserved byte-exact and flagged everywhere "
              "it is restated",
          (flagged == documented and len(anomaly_rows) == 3
           and {r["avg_price_ngn"] for r in anomaly_rows} == {MARCH_2025_EGG_ANOMALY["value_text"]}),
          f"flagged {sorted(flagged)}, rows {len(anomaly_rows)}, "
          f"values {sorted({r['avg_price_ngn'] for r in anomaly_rows})}")

    check(27, f"Lowest <= national <= Highest in all {EXPECTED_EXTREME_BRACKET_COMPARISONS} "
              f"item-releases",
          n_compared == EXPECTED_EXTREME_BRACKET_COMPARISONS and not nat_fail,
          f"compared {n_compared}, failures {nat_fail[:3]}")

    conflict_items = {key for key, _, _, _, _ in zone_fail}
    zone_conflicts = {(key[0], key[1], z) for key, _, _, offenders, _ in zone_fail
                      for z in offenders}
    check(28, f"every zone average lies within [Lowest, Highest] in "
              f"{EXPECTED_EXTREME_BRACKET_COMPARISONS - EXPECTED_ZONE_BRACKET_EXCEPTIONS} of "
              f"{EXPECTED_EXTREME_BRACKET_COMPARISONS} item-releases; the "
              f"{EXPECTED_ZONE_BRACKET_EXCEPTIONS} exceptions are the documented July 2025 cases",
          (len(conflict_items) == EXPECTED_ZONE_BRACKET_EXCEPTIONS
           and conflict_items == JULY_2025_BRACKET_ITEMS),
          f"got {sorted(conflict_items)}")

    marked = {(r["release_month"], r["item_code"], r["zone"]) for r in zone_rows
              if ZONE_ABOVE_STATE_MAX_FLAG in r["source_anomaly"]}
    check(29, "each individual zone cell outside the bracket is flagged, and none other",
          marked == JULY_2025_ZONE_CONFLICTS == zone_conflicts,
          f"flagged {sorted(marked)}; measured {sorted(zone_conflicts)}")

    prior_counts, prior_prec, prior_subst, prior_blank = cross_release(
        national, "PRIOR_MONTH", 1)
    subst_keys = {(a, b) for a, b, _, _ in prior_subst}
    check(30, f"prior-month restatement: {EXPECTED_PRIOR_MONTH_COMPARISONS} compared, "
              f"{EXPECTED_PRIOR_MONTH_IDENTICAL} byte-identical, "
              f"{EXPECTED_PRIOR_MONTH_PRECISION} precision-only, "
              f"{len(EXPECTED_SUBSTANTIVE_REVISIONS)} substantive",
          (sum(prior_counts.values()) == EXPECTED_PRIOR_MONTH_COMPARISONS
           and prior_counts["identical"] == EXPECTED_PRIOR_MONTH_IDENTICAL
           and prior_counts["precision"] == EXPECTED_PRIOR_MONTH_PRECISION
           and subst_keys == EXPECTED_SUBSTANTIVE_REVISIONS),
          f"{dict(prior_counts)}, substantive at {sorted(subst_keys)}, blanks {prior_blank[:2]}")

    year_counts, year_prec, year_subst, year_blank = cross_release(national, "YEAR_AGO", 12)
    prec_keys = {(a, b) for a, b, _, _ in year_prec}
    check(31, f"year-ago restatement: {EXPECTED_YEAR_AGO_COMPARISONS} compared, "
              f"{EXPECTED_YEAR_AGO_IDENTICAL} byte-identical, "
              f"{len(EXPECTED_YEAR_AGO_PRECISION)} precision-only, 0 substantive",
          (sum(year_counts.values()) == EXPECTED_YEAR_AGO_COMPARISONS
           and year_counts["identical"] == EXPECTED_YEAR_AGO_IDENTICAL
           and prec_keys == EXPECTED_YEAR_AGO_PRECISION
           and not year_subst),
          f"{dict(year_counts)}, precision at {sorted(prec_keys)}, substantive {year_subst[:2]}")

    missing_prov = [r for r in national + zone_rows + callouts
                    if not r["source_file"] or not r["source_sheet"] or not r["source_row"]
                    or not r["source_cell_reference"]]
    mismatched = [r for r in national + zone_rows + callouts
                  if r["source_cell_reference"] !=
                  f"{get_column_letter(int(r['source_column_index']))}{r['source_row']}"]
    check(32, "every row carries complete provenance and a self-consistent A1 reference",
          not missing_prov and not mismatched,
          f"missing {len(missing_prov)}, mismatched {len(mismatched)}")

    reread = re_read_check(national, zone_rows, callouts)
    check(33, "every written value re-reads identically from its source cell",
          not reread, f"{len(reread)} mismatches: {reread[:2]}")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nbs/food")
    check(34, f"all {n1} acquired food source files match their recorded SHA-256",
          n1 > 0 and not bad1, f"{bad1[:3]}")

    for path in (OUT_NATIONAL, OUT_ZONE, OUT_CALLOUT, REPORT_PATH):
        assert_outside_raw(path)
    check(35, "no output path resolves inside data/raw/", True, "assert_outside_raw passed")

    if failures:
        raise ValidationError(
            f"{len(failures)} validation check(s) failed:\n" + "\n".join(failures))
    return passed


# ----------------------------------------------------------------------------
def write_csv(path: Path, columns, rows):
    target = assert_outside_raw(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(national, zone_rows, callouts, notes, passed):
    recon = [x for x in weighted_reconciliation(national, zone_rows) if x[2] is not None]
    breaches = [x for x in recon if x[2] > RECONCILE_TOLERANCE]
    n_compared, nat_fail, zone_fail, _ = extreme_bracket(national, callouts, zone_rows)
    prior_counts, _, prior_subst, _ = cross_release(national, "PRIOR_MONTH", 1)
    year_counts, year_prec, _, _ = cross_release(national, "YEAR_AGO", 12)

    units = Counter(ITEM_REF[c]["unit_source"] or "UNRESOLVED" for c in ITEM_REF)
    unresolved = sorted(ITEM_REF[c]["item_label"] for c in ITEM_REF if not ITEM_REF[c]["unit"])

    lines = []
    add = lines.append
    add("# NBS Selected Food Price Watch - Cleaning Validation")
    add("")
    add(f"Generated by `src/cleaning/clean_nbs_food.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.")
    add("")
    add("## Scope")
    add("")
    add(f"- **Releases processed:** {len(notes)} spreadsheet releases")
    add(f"- **Release coverage:** {WINDOW_START} to {WINDOW_END} "
        f"({len(notes)} months, no gaps)")
    add(f"- **National rows:** {len(national)}")
    add(f"- **Zone rows:** {len(zone_rows)}")
    add(f"- **Callout rows:** {len(callouts)}")
    add("")
    add("Food is the only dataset in the project with **no state column at all**. State names exist "
        "only inside the packed `Highest` / `Lowest` text, and that limitation is preserved rather "
        "than papered over.")
    add("")
    add("## Row counts")
    add("")
    add("| Table | Arithmetic | Rows |")
    add("|---|---|---|")
    add(f"| `food_price_national_monthly` | {EXPECTED_RELEASES} releases x {EXPECTED_ITEMS} items "
        f"x {EXPECTED_PERIODS} periods | **{len(national)}** |")
    add(f"| `food_price_zone_monthly` | {EXPECTED_RELEASES} x {EXPECTED_ITEMS} x {EXPECTED_ZONES} "
        f"zones | **{len(zone_rows)}** |")
    add(f"| `food_price_extreme_callout` | {EXPECTED_RELEASES} x {EXPECTED_ITEMS} x 2 extremes | "
        f"**{len(callouts)}** |")
    add("")
    add("## Release-month derivation")
    add("")
    add("The worksheet name is **never** used. Three header signals must agree, and the file name "
        "is a fourth (D-30).")
    add("")
    add("| Release | Year-ago header | Prior header | Current header | Sheet name implies | "
        "Sheet name agrees? |")
    add("|---|---|---|---|---|---|")
    for n in sorted(notes, key=lambda x: x["release_month"]):
        agree = "yes" if n["sheet_name_month"] == n["release_month"] else "**NO**"
        add(f"| {n['release_month']} | `{n['period_labels'][0]}` | `{n['period_labels'][1]}` | "
            f"`{n['period_labels'][2]}` | {n['sheet_name_month'] or 'n/a'} | {agree} |")
    add("")
    add("## NULL pattern")
    add("")
    nulls = [r for r in national if r["avg_price_ngn"] == ""]
    add(f"**{len(nulls)} NULL national prices**, and no NULL anywhere else. Every one carries "
        f"`value_status = '{STATUS_BLANK}'`. No official NBS source explains the absence, so no "
        f"stronger claim than *not reported* is made (D-34). No blank is ever filled, and no blank "
        f"becomes a zero.")
    add("")
    add("| Period column | Releases affected | Items affected | NULLs |")
    add("|---|---|---|---|")
    add(f"| Year-ago | 2025-01 … 2025-12 (12) | {len(NO_YEAR_AGO_ITEMS)} | "
        f"{EXPECTED_YEAR_AGO_NULLS} |")
    add(f"| Prior month | 2025-01 only | {len(NO_YEAR_AGO_ITEMS)} | "
        f"{EXPECTED_PRIOR_MONTH_NULLS} |")
    add(f"| Current month | none | 0 | 0 |")
    add(f"| **Total** | | | **{EXPECTED_NATIONAL_NULLS}** |")
    add("")
    add("From the 2026-01 release onward the year-ago column is complete for all 42 items, so the "
        "count is release-dependent and must never be written as \"15 per month\".")
    add("")
    add("The 15 items:")
    add("")
    for code in sorted(NO_YEAR_AGO_ITEMS):
        add(f"- `{code}` - {ITEM_REF[code]['item_label']}")
    add("")
    add("## Food-item reference")
    add("")
    add(f"`data/reference/ref_food_item.csv` holds {len(ITEM_REF)} items and "
        f"{sum(int(r['alias_variant_count']) for r in ITEM_REF.values())} label aliases. Two raw "
        f"variants are reconciled:")
    add("")
    add("| Canonical `item_label` | Raw variant | Where |")
    add("|---|---|---|")
    add("| `Agric hen eggs,` | `Agric hen eggs` | `Selected_food_table_Jan25.xlsx` main sheet A2 |")
    add("| `Smoked fish (Mackerel)` | `Smoked fish` | zone sheet A33, all 17 releases |")
    add("")
    add("`item_label_raw` on every row preserves what that sheet actually printed.")
    add("")
    add("## Unit coverage")
    add("")
    add(f"Units are **never inferred**. {len(ITEM_REF) - len(unresolved)} of {len(ITEM_REF)} items "
        f"carry one: {units.get('SPREADSHEET_LABEL', 0)} stated by the spreadsheet label itself, "
        f"{units.get('NBS_REPORT_PDF', 0)} stated in an official NBS report PDF. Every PDF claim "
        f"was tied to its item by matching the naira figure the sentence quotes against that "
        f"release's published cell; `unit_evidence` records the citation.")
    add("")
    add(f"**{len(unresolved)} items have no unit and are left NULL:**")
    add("")
    for label in unresolved:
        add(f"- {label}")
    add("")
    add("## National / zone reconciliation (hard check)")
    add("")
    add("```")
    add("national  =  sum(zone_average x states_in_zone) / 37")
    add("weights: North Central 7, North East 6, North West 7, "
        "South East 5, South South 6, South West 6")
    add("```")
    add("")
    add(f"**{len(recon) - len(breaches)} of {len(recon)} item-releases agree within a relative "
        f"tolerance of {RECONCILE_TOLERANCE:g}.** The published national is therefore the plain "
        f"average of the 37 state averages, exactly as the NBS methodology page states.")
    add("")
    add("The single exception is documented, preserved and flagged, never recalculated:")
    add("")
    for r, implied, err in breaches:
        add(f"- **{r['observation_month']} {r['item_label']}** - published "
            f"`{r['avg_price_ngn']}`, implied `{implied:.6f}`, {err*100:+.3f}%. "
            f"Source `{r['source_file']}`"
            + (f" / `{r['source_member']}`" if r['source_member'] else "")
            + f" sheet `{r['source_sheet']}` cell `{r['source_cell_reference']}`. "
              f"Flagged `{NATIONAL_ABOVE_ZONES_FLAG}`.")
    add("")
    add("## Extreme brackets (hard checks)")
    add("")
    add(f"- `Lowest <= national <= Highest`: **{n_compared - len(nat_fail)} of {n_compared}** "
        f"item-releases pass.")
    add(f"- every zone average inside `[Lowest, Highest]`: "
        f"**{n_compared - len(zone_fail)} of {n_compared}** item-releases pass.")
    add("")
    add("The four failures are all in July 2025 and all documented. Neither the zone value nor the "
        "callout is corrected - we cannot establish which published component is wrong (D-33):")
    add("")
    add("| Item | Zone | Zone average | Published `Lowest` | Published `Highest` |")
    add("|---|---|---|---|---|")
    for key, low, high, offenders, values in zone_fail:
        for z in offenders:
            add(f"| {ITEM_REF[key[1]]['item_label']} | {z} | {values[z]} | {low} | {high} |")
    add("")
    add("## Cross-release comparison")
    add("")
    add("| Comparison | Compared | Byte-identical | Precision-only | Substantive |")
    add("|---|---|---|---|---|")
    add(f"| Prior-month column vs the earlier release's own month | "
        f"{sum(prior_counts.values())} | {prior_counts['identical']} | "
        f"{prior_counts['precision']} | **{prior_counts['substantive']}** |")
    add(f"| Year-ago column vs the release 12 months earlier | {sum(year_counts.values())} | "
        f"{year_counts['identical']} | {year_counts['precision']} | "
        f"**{year_counts['substantive']}** |")
    add("")
    add(f"The {prior_counts['substantive']} substantive differences are genuine NBS revisions and "
        f"are never collapsed. Both publications are kept, told apart by `release_month`. Every "
        f"delta is an exact multiple of 1/37 - one state restated by a round naira amount:")
    add("")
    add("| Observation month | Item | First published | Restated | Delta | Delta x 37 |")
    add("|---|---|---|---|---|---|")
    for obs, code, earlier, later in sorted(prior_subst):
        d = float(later) - float(earlier)
        add(f"| {obs} | {ITEM_REF[code]['item_label']} | `{earlier}` | `{later}` | "
            f"{d:+.6f} | {d*37:+.2f} |")
    add("")
    add("Sub-tolerance differences (precision only, never described as identical or as revisions):")
    add("")
    for obs, code, earlier, later in sorted(year_prec):
        add(f"- {obs}, {ITEM_REF[code]['item_label']}: `{earlier}` vs `{later}`")
    add("")
    add("## Structural variations and anomalies")
    add("")
    add("| Finding | Handling |")
    add("|---|---|")
    add("| Stale worksheet name `Selected Food Dec 2024` in the March and April 2025 files | "
        f"Sheet name ignored; month from three agreeing headers. `{STALE_SHEET_NAME_FLAG}`. |")
    add("| `Item Labels` (plural) in February 2025 | Accepted as an alias of `Item Label`; "
        f"`{PLURAL_HEADER_FLAG}`; `header_label_raw` keeps the published text. |")
    add("| Lowercase `Average of feb-24`, long vs short month names | Parsed case-insensitively; "
        "the published label is preserved in `source_period_label`. |")
    add("| Reported sheet extents of 50-51 rows and up to 12 columns | Tables are sized from "
        "content; nothing exists below row 43 or right of column 8. |")
    add("| `MoM` / `YoY` | Excluded. They are literal Excel formulas `=(D2-C2)/C2*100` and "
        "`=(D2-B2)/B2*100`; the cleaner asserts the two headers before excluding them. |")
    add("| March 2025 crate-of-eggs national average above every zone | Preserved byte-exact, "
        f"flagged `{NATIONAL_ABOVE_ZONES_FLAG}` on all three rows that carry it. |")
    add("| Four July 2025 zone averages above the published state maximum | Preserved byte-exact, "
        f"flagged `{ZONE_ABOVE_STATE_MAX_FLAG}`. |")
    add("| No food callout ever names two states | No splitting rule implemented; a slash or a "
        "second state is a hard failure requiring inspection (D-35). |")
    add("")
    add("## Validation checks")
    add("")
    for line in passed:
        add(f"- {line}")
    add("")
    add("## Raw integrity")
    add("")
    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nbs/food")
    n2, bad2 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/")
    n3, bad3 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/")
    add(f"- Food source files verified against `transfer_verification.csv`: **{n1}**, "
        f"{len(bad1)} problems.")
    add(f"- Whole original corpus: **{n2}** files, {len(bad2)} problems.")
    add(f"- September 2026 extension corpus: **{n3}** files, {len(bad3)} problems.")
    add("- Nothing under `data/raw/` is opened for writing; `assert_outside_raw()` guards every "
        "output path.")
    add("")

    target = assert_outside_raw(REPORT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    national, zone_rows, callouts, notes = extract_all()
    print(f"releases   {len(notes)}")
    print(f"national   {len(national)} rows "
          f"({sum(1 for r in national if r['avg_price_ngn'] == '')} NULL)")
    print(f"zone       {len(zone_rows)} rows")
    print(f"callout    {len(callouts)} rows")

    recon = [x for x in weighted_reconciliation(national, zone_rows) if x[2] is not None]
    breaches = [x for x in recon if x[2] > RECONCILE_TOLERANCE]
    print(f"reconcile  {len(recon)} compared -> {len(recon)-len(breaches)} within "
          f"{RECONCILE_TOLERANCE:g}, {len(breaches)} documented exception(s)")

    n_compared, nat_fail, zone_fail, _ = extreme_bracket(national, callouts, zone_rows)
    print(f"brackets   national {n_compared-len(nat_fail)}/{n_compared}, "
          f"zone {n_compared-len(zone_fail)}/{n_compared}")

    prior_counts, _, _, _ = cross_release(national, "PRIOR_MONTH", 1)
    year_counts, _, _, _ = cross_release(national, "YEAR_AGO", 12)
    print(f"prior-month {sum(prior_counts.values())} -> {prior_counts['identical']} identical, "
          f"{prior_counts['precision']} precision-only, {prior_counts['substantive']} substantive")
    print(f"year-ago    {sum(year_counts.values())} -> {year_counts['identical']} identical, "
          f"{year_counts['precision']} precision-only, {year_counts['substantive']} substantive")

    passed = validate(national, zone_rows, callouts, notes)
    print(f"validation {len(passed)}/{len(passed)} checks pass")

    write_csv(OUT_NATIONAL, NATIONAL_COLUMNS, national)
    write_csv(OUT_ZONE, ZONE_COLUMNS, zone_rows)
    write_csv(OUT_CALLOUT, CALLOUT_COLUMNS_OUT, callouts)
    write_report(national, zone_rows, callouts, notes, passed)
    for path in (OUT_NATIONAL, OUT_ZONE, OUT_CALLOUT, REPORT_PATH):
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
