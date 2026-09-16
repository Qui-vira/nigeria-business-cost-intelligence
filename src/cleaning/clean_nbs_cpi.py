"""Clean the NBS CPI state tables (Table-5) into one canonical long table.

Source of record : data/raw/nbs/cpi/*.xlsx and the .xlsx/.xls members of .../cpi/*.zip
Output           : data/processed/nbs/cpi_state_monthly.csv

**Scope.** `Table-5` only - the state CPI table, Food and All Items. Nine other sheets exist in these
workbooks and none is ingested:

    Table1, Table2, Table3, Table4                  national / urban / rural series
    Table1 (2), Table2 (2), Table3 (2), Table3 (3), Table4 (2)
                                                    pre-rebasing working sheets: dual-base,
                                                    ~96,857 #REF! cells, one an exact duplicate

Two profiling anomalies stay outside this dataset and are documented, not processed: the October and
November 2025 `Table2` sheets carry a 1995-base series under a "Base Year 2024 = 100" title, and the
`(2)` sheets carry two bases side by side in identically-headed columns.

Implements the approved rules in docs/data_design/. In particular:

  * **the base is established from Table-5 itself** (D-47). Every release must state
    `(Base Period: 2024 = 100)` on its own sheet; the base is never inherited from Table1, which
    carries two contradictory base titles in every release.
  * **an index is never stored in the same field as a rate without saying which it is** (D-48).
    Every row carries `measure` and `unit`: `INDEX` / `INDEX_2024_100`, or
    `CHANGE_MOM_PCT` / `CHANGE_YOY_PCT` with `PERCENT`.
  * **published change rates are ingested, never recomputed** (D-49). The index-ratio identity is a
    validation check with a documented tolerance and one documented exception, not a generator.
  * **the table ends where labels stop resolving to states**, never on the literal word "Note"
    (D-50). Row 42 is a footnote sitting inside the label column and is not a geography.
  * release month and observation month are separate: one release publishes three index months.
  * tables are sized from content; `max_row` / `max_column` are never trusted.

Run from the project root:

    python src/cleaning/clean_nbs_cpi.py

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
import xlrd
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_DIR = RAW_ROOT / "nbs" / "cpi"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "nbs" / "cpi_state_monthly.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_cpi_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

EXPECTED_RELEASES = 18
WINDOW_START = dt.date(2025, 2, 1)
WINDOW_END = dt.date(2026, 7, 1)
EXPECTED_STATES = 37
CPI_GROUPS = ("FOOD", "ALL_ITEMS")
INDEX_PERIODS = 3
CHANGE_MEASURES = 2

STATE_GROUP_CELLS = EXPECTED_STATES * len(CPI_GROUPS)                                          # 74
EXPECTED_ROWS_PER_RELEASE = STATE_GROUP_CELLS * (INDEX_PERIODS + CHANGE_MEASURES)              # 370

# February 2026's year-ago column is excluded entirely - see YEAR_AGO_CONFLICT below - taking
# 74 INDEX rows and the 74 CHANGE_YOY_PCT rows computed from that same denominator with it.
EXPECTED_INDEX_ROWS = STATE_GROUP_CELLS * INDEX_PERIODS * EXPECTED_RELEASES - STATE_GROUP_CELLS
EXPECTED_CHANGE_ROWS = (STATE_GROUP_CELLS * CHANGE_MEASURES * EXPECTED_RELEASES
                        - STATE_GROUP_CELLS)                                                   # 2590
EXPECTED_TOTAL_ROWS = EXPECTED_INDEX_ROWS + EXPECTED_CHANGE_ROWS                               # 6512

TABLE5_SHEET_KEY = "table5"
EXCLUDED_SHEETS = ("Table1", "Table2", "Table3", "Table4",
                   "Table1 (2)", "Table2 (2)", "Table3 (2)", "Table3 (3)", "Table4 (2)")

HEADER_PERIOD_ROW = 3
HEADER_MEASURE_ROW = 4
FIRST_STATE_ROW = 5
LABEL_COLUMN = 2
BASE_ROW = 2
# (column, group, period slot) for the three index blocks, then the two change blocks
INDEX_COLUMNS = {0: (3, 4), 1: (5, 6), 2: (7, 8)}      # slot -> (Food col, All Items col)
CHANGE_COLUMNS = {"CHANGE_YOY_PCT": (9, 10), "CHANGE_MOM_PCT": (11, 12)}
PERIOD_POSITIONS = ("YEAR_AGO", "PRIOR_MONTH", "CURRENT_MONTH")
CHANGE_LABEL_COLUMNS = {9: "Annual Change", 11: "Monthly Change"}

BASE_PERIOD = "2024=100"
BASE_PATTERN = re.compile(r"base\s*period\s*:?\s*2024\s*=\s*100", re.I)
UNIT_INDEX = "INDEX_2024_100"
UNIT_PERCENT = "PERCENT"
GEOGRAPHY_TYPE = "STATE"
COMPARABILITY_WARNING = ("Indices may not be used for inter-state price comparison because market "
                         "baskets differ state to state.")

INDEX_MIN, INDEX_MAX = 50.0, 400.0
CHANGE_MIN, CHANGE_MAX = -50.0, 200.0

# --- verified published anomaly: a single hand-rounded cell --------------------------------------
HAND_ROUNDED_CHANGE_FLAG = "PUBLISHED_CHANGE_ROUNDED_TO_2DP"
HAND_ROUNDED_CHANGE = {
    ("2025-08-01", "Borno", "ALL_ITEMS", "CHANGE_YOY_PCT"): "26.31",
}
CHANGE_IDENTITY_TOLERANCE = 1e-12
EXPECTED_IDENTITY_COMPARISONS = EXPECTED_STATES * len(CPI_GROUPS) * EXPECTED_RELEASES   # 1332
SUBSTANTIVE_REVISION_TOLERANCE = 1e-12

# --- verified state-label variants ----------------------------------------------------------------
# --- verified period-label defect: February 2026's year-ago column holds January 2025 data -------
# The header reads 2025-02-01. All 74 values are byte-identical to the published January 2025
# column and none matches published February 2025; the March 2026 release is the control and
# matches its own year-ago month 74/74. The column is therefore excluded outright - not relabelled
# to January, not published as February - and so are the 74 CHANGE_YOY_PCT values computed from
# that same denominator (D-51).
YEAR_AGO_CONFLICT_FLAG = "YEAR_AGO_PERIOD_LABEL_DATA_CONFLICT"
YEAR_AGO_CONFLICT_RELEASE = dt.date(2026, 2, 1)
EXPECTED_YEAR_AGO_EXCLUSIONS = STATE_GROUP_CELLS      # 74 INDEX cells
EXPECTED_YOY_EXCLUSIONS = STATE_GROUP_CELLS           # 74 CHANGE_YOY_PCT cells

# --- verified alignment defect: April 2025's state labels disagree with two later restatements ---
# Published values are kept exactly as NBS published them. Nothing is shifted, replaced or
# relabelled; the rows are flagged and demoted out of "first publication" instead (D-52).
ALIGNMENT_DISPUTED_FLAG = "STATE_VALUE_ALIGNMENT_DISPUTED"
ALIGNMENT_DISPUTED_RELEASE = dt.date(2025, 4, 1)
EXPECTED_ALIGNMENT_DISPUTED_ROWS = STATE_GROUP_CELLS  # 74 current-month INDEX rows
EXPECTED_ALIGNMENT_CONFLICTS = 67                     # of those 74, how many the later two contradict
EXPECTED_LATER_RESTATEMENTS_AGREE = 73                # the later two agree on 73 of the 74 ...
# ... and disagree on exactly one, which is published as three different values in three releases:
ALIGNMENT_TRIPLE_VALUE = ("Borno", "FOOD", {"2025-04-01": "114.69492",
                                            "2025-05-01": "146.650854",
                                            "2026-04-01": "136.650854"})
# The April 2025 defect compromises that observation month as a whole, so a disagreement between
# ANY two publications of 2025-04 belongs to the documented defect, not to a normal revision.
KNOWN_CONFLICT_OBSERVATION_MONTHS = {ALIGNMENT_DISPUTED_RELEASE.isoformat()}

DOUBLE_S_FLAG = "STATE_LABEL_NASSARAWA_DOUBLE_S"
NASSARAWA_RELEASES = {"2025-02-01", "2025-03-01", "2025-04-01",
                      "2025-06-01", "2025-07-01", "2025-08-01"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

COLUMNS = [
    "release_month", "observation_month", "state", "state_raw_label", "zone", "geography_type",
    "cpi_group", "cpi_group_raw", "measure", "value", "unit", "base_period",
    "period_position", "period_label_raw", "is_primary_release", "comparability_warning",
    "value_status", "source_anomaly", "extraction_method",
    "source_file", "source_member", "source_sheet", "source_row",
    "source_column_index", "source_cell_reference",
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


def flat(value) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def normalise(value) -> str:
    return flat(value).casefold()


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


STATE_LOOKUP = load_state_lookup()


def add_months(day: dt.date, n: int) -> dt.date:
    idx = day.month - 1 + n
    return dt.date(day.year + idx // 12, idx % 12 + 1, 1)


def release_of(name: str) -> dt.date:
    cleaned = re.sub(r"[_\-/]+", " ", name)
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(20\d{2}|\d{2})\b",
                  cleaned, re.I)
    if not m:
        raise ValidationError(f"{name}: no release month in the file name")
    year = int(m.group(2))
    return dt.date(2000 + year if year < 100 else year, MONTHS[m.group(1)[:3].casefold()], 1)


def number_text(value) -> str:
    """Published value as text, precision unchanged. Blank stays NULL, never 0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValidationError(f"Boolean where a CPI value was expected: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    body = str(value).strip()
    if body == "":
        return ""
    raise ValidationError(f"Non-numeric value where a CPI value was expected: {value!r}")


# ----------------------------------------------------------------------------
def iter_members():
    for path in sorted(RAW_DIR.iterdir()):
        if path.suffix.lower() in (".xlsx", ".xls"):
            yield path.name, "", path.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith((".xlsx", ".xls")) and not name.startswith("__MACOSX"):
                        yield path.name, name, archive.read(name)


def is_table5(sheet_name: str) -> bool:
    return flat(sheet_name).casefold().replace(" ", "").replace("-", "") == TABLE5_SHEET_KEY


def read_table5(name: str, data: bytes):
    """Return (sheet_name, grid, extraction_method, all_sheet_names).

    Both readers are normalised so a date cell arrives as a datetime either way. Only the Table-5
    sheet is ever converted into a grid; the excluded sheets are listed but never read.
    """
    if name.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheets = list(wb.sheetnames)
            hits = [n for n in sheets if is_table5(n)]
            if len(hits) != 1:
                raise ValidationError(f"{name}: expected exactly one Table-5 sheet, found {hits}")
            grid = [tuple(r) for r in wb[hits[0]].iter_rows(values_only=True)]
            return hits[0], grid, "XLSX_OPENPYXL", sheets
        finally:
            wb.close()
    book = xlrd.open_workbook(file_contents=data)
    sheets = list(book.sheet_names())
    hits = [n for n in sheets if is_table5(n)]
    if len(hits) != 1:
        raise ValidationError(f"{name}: expected exactly one Table-5 sheet, found {hits}")
    sheet = book.sheet_by_name(hits[0])
    grid = []
    for r in range(sheet.nrows):
        row = []
        for c in range(sheet.ncols):
            value, kind = sheet.cell_value(r, c), sheet.cell_type(r, c)
            if kind == xlrd.XL_CELL_DATE:
                value = xlrd.xldate_as_datetime(value, book.datemode)
            elif kind == xlrd.XL_CELL_EMPTY:
                value = None
            row.append(value)
        grid.append(tuple(row))
    return hits[0], grid, f"XLS_XLRD_{xlrd.__version__}", sheets


def cell(grid, row_idx: int, col_idx: int):
    if row_idx < 1 or row_idx > len(grid):
        return None
    row = grid[row_idx - 1]
    return row[col_idx - 1] if 1 <= col_idx <= len(row) else None


def content_extent(grid) -> tuple[int, int]:
    last_row = last_col = 0
    for r, row in enumerate(grid, 1):
        for c, value in enumerate(row, 1):
            if value is not None and str(value).strip() != "":
                last_row, last_col = max(last_row, r), max(last_col, c)
    return last_row, last_col


def period_of(value, where: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date().replace(day=1)
    if isinstance(value, dt.date):
        return value.replace(day=1)
    raise ValidationError(f"{where}: period header {value!r} is not a date cell")


def extract_release(container: str, member: str, data: bytes) -> dict:
    name = member or container
    release = release_of(name)
    sheet, grid, method, all_sheets = read_table5(name, data)

    excluded_present = [s for s in all_sheets if not is_table5(s)]
    unexpected = [s for s in excluded_present if s not in EXCLUDED_SHEETS]
    if unexpected:
        raise ValidationError(
            f"{name}: unrecognised sheet(s) {unexpected}; every non-Table-5 sheet must be on the "
            f"documented exclusion list before it can be ignored")

    extent = content_extent(grid)
    if extent[1] > 12:
        raise ValidationError(f"{name}: Table-5 has content right of column 12 ({extent})")

    base_text = next((flat(v) for v in grid[BASE_ROW - 1] if flat(v)), "")
    if not BASE_PATTERN.search(base_text):
        raise ValidationError(
            f"{name}: Table-5 does not state the 2024 = 100 base on its own sheet "
            f"(row {BASE_ROW} reads {base_text!r}). The base is never inherited from Table1.")

    periods = []
    for slot, (food_col, _) in INDEX_COLUMNS.items():
        periods.append(period_of(cell(grid, HEADER_PERIOD_ROW, food_col),
                                 f"{name} r{HEADER_PERIOD_ROW}c{food_col}"))
    if periods[2] != release:
        raise ValidationError(
            f"{name}: current-period header is {periods[2]}, file implies release {release}")
    if periods[1] != add_months(release, -1) or periods[0] != add_months(release, -12):
        raise ValidationError(
            f"{name}: period columns are not year-ago / prior / current: {periods}")

    for col, expected in ((3, "Food"), (4, "All Items"), (5, "Food"), (6, "All Items"),
                          (7, "Food"), (8, "All Items"), (9, "Food"), (10, "All Items"),
                          (11, "Food"), (12, "All Items")):
        got = flat(cell(grid, HEADER_MEASURE_ROW, col))
        if got.casefold() != expected.casefold():
            raise ValidationError(
                f"{name}: measure header c{col} is {got!r}, expected {expected!r}")
    for col, label in CHANGE_LABEL_COLUMNS.items():
        got = flat(cell(grid, HEADER_PERIOD_ROW, col))
        if got.casefold() != label.casefold():
            raise ValidationError(f"{name}: c{col} header is {got!r}, expected {label!r}")

    # ---- walk the state block; it ends where a label stops resolving to a state (D-50) ----------
    states, terminator = [], None
    row = FIRST_STATE_ROW
    while row <= extent[0]:
        raw = flat(cell(grid, row, LABEL_COLUMN))
        if raw == "":
            terminator = (row, raw, "blank label")
            break
        if normalise(raw) not in STATE_LOOKUP:
            terminator = (row, raw, "label does not resolve through ref_state_zone")
            break
        states.append((row, raw))
        row += 1
    if len(states) != EXPECTED_STATES:
        raise ValidationError(
            f"{name}: {len(states)} state rows before the table terminated, "
            f"expected {EXPECTED_STATES}; terminator was {terminator}")
    if terminator is None:
        raise ValidationError(f"{name}: the state block never terminated")
    trailing = [flat(cell(grid, r, LABEL_COLUMN)) for r in range(terminator[0] + 1, extent[0] + 1)
                if flat(cell(grid, r, LABEL_COLUMN))]
    if trailing:
        raise ValidationError(f"{name}: unexpected labels after the terminator: {trailing}")

    return dict(container=container, member=member, sheet=sheet, grid=grid, release=release,
                periods=periods, states=states, base_text=base_text, method=method,
                extent=extent, terminator=terminator, all_sheets=all_sheets)


def build_rows(releases: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (canonical rows, excluded-cell evidence).

    Excluded cells are never emitted as observations. Their published value and full provenance are
    retained as evidence so the exclusion is auditable rather than merely asserted.
    """
    out: list[dict] = []
    excluded: list[dict] = []
    for rel in releases:
        release_text = rel["release"].isoformat()
        nassarawa = release_text in NASSARAWA_RELEASES
        for row_idx, raw_label in rel["states"]:
            state, zone = STATE_LOOKUP[normalise(raw_label)]
            label_flags = [DOUBLE_S_FLAG] if normalise(raw_label) == "nassarawa" else []
            if bool(label_flags) != (nassarawa and normalise(raw_label) == "nassarawa"):
                raise ValidationError(
                    f"{rel['member'] or rel['container']}: {raw_label!r} in {release_text} does not "
                    f"match the documented spelling-variant releases")
            for gi, group in enumerate(CPI_GROUPS):
                group_raw = flat(cell(rel["grid"], HEADER_MEASURE_ROW, INDEX_COLUMNS[0][gi]))
                for slot, observation in enumerate(rel["periods"]):
                    col = INDEX_COLUMNS[slot][gi]
                    value = number_text(cell(rel["grid"], row_idx, col))
                    if not value:
                        raise ValidationError(
                            f"{rel['member'] or rel['container']} r{row_idx}c{col}: empty index "
                            f"cell for {raw_label} / {group}")
                    position = PERIOD_POSITIONS[slot]
                    if (rel["release"] == YEAR_AGO_CONFLICT_RELEASE
                            and position == "YEAR_AGO"):
                        excluded.append(_evidence(
                            rel, release_text, observation, state, raw_label, group, "INDEX",
                            value, position, row_idx, col, YEAR_AGO_CONFLICT_FLAG,
                            "header month and data month disagree; the column holds the published "
                            "January 2025 values"))
                        continue
                    flags = list(label_flags)
                    if (rel["release"] == ALIGNMENT_DISPUTED_RELEASE
                            and position == "CURRENT_MONTH"):
                        flags.append(ALIGNMENT_DISPUTED_FLAG)
                    out.append(_row(rel, release_text, observation, state, raw_label, zone,
                                    group, group_raw, "INDEX", value, UNIT_INDEX,
                                    position,
                                    flat(cell(rel["grid"], HEADER_PERIOD_ROW, col)) or
                                    observation.isoformat(),
                                    row_idx, col, flags))
                for measure, cols in CHANGE_COLUMNS.items():
                    col = cols[gi]
                    value = number_text(cell(rel["grid"], row_idx, col))
                    if not value:
                        raise ValidationError(
                            f"{rel['member'] or rel['container']} r{row_idx}c{col}: empty change "
                            f"cell for {raw_label} / {group}")
                    if (rel["release"] == YEAR_AGO_CONFLICT_RELEASE
                            and measure == "CHANGE_YOY_PCT"):
                        excluded.append(_evidence(
                            rel, release_text, rel["periods"][2], state, raw_label, group,
                            measure, value, "CURRENT_MONTH", row_idx, col,
                            YEAR_AGO_CONFLICT_FLAG,
                            "computed from the disputed year-ago denominator, so it cannot be "
                            "represented as a true February 2026 year-on-year change"))
                        continue
                    flags = list(label_flags)
                    key = (release_text, state, group, measure)
                    if key in HAND_ROUNDED_CHANGE:
                        if value != HAND_ROUNDED_CHANGE[key]:
                            raise ValidationError(
                                f"{key}: documented hand-rounded value is "
                                f"{HAND_ROUNDED_CHANGE[key]!r} but the source now reads {value!r}")
                        flags.append(HAND_ROUNDED_CHANGE_FLAG)
                    label_col = 9 if measure == "CHANGE_YOY_PCT" else 11
                    out.append(_row(rel, release_text, rel["periods"][2], state, raw_label, zone,
                                    group, group_raw, measure, value, UNIT_PERCENT,
                                    "CURRENT_MONTH",
                                    flat(cell(rel["grid"], HEADER_PERIOD_ROW, label_col)),
                                    row_idx, col, flags))
    return out, excluded


def _evidence(rel, release_text, observation, state, raw_label, group, measure, value,
              position, row_idx, col, flag, reason):
    """A published cell that is deliberately NOT an observation, kept with its provenance."""
    return {
        "release_month": release_text,
        "header_observation_month": observation.isoformat(),
        "state": state,
        "state_raw_label": raw_label,
        "cpi_group": group,
        "measure": measure,
        "published_value": value,
        "period_position": position,
        "exclusion_flag": flag,
        "exclusion_reason": reason,
        "source_file": rel["container"],
        "source_member": rel["member"],
        "source_sheet": rel["sheet"],
        "source_row": row_idx,
        "source_column_index": col,
        "source_cell_reference": f"{get_column_letter(col)}{row_idx}",
    }


def _row(rel, release_text, observation, state, raw_label, zone, group, group_raw,
         measure, value, unit, position, period_label, row_idx, col, flags):
    return {
        "release_month": release_text,
        "observation_month": observation.isoformat(),
        "state": state,
        "state_raw_label": raw_label,
        "zone": zone,
        "geography_type": GEOGRAPHY_TYPE,
        "cpi_group": group,
        "cpi_group_raw": group_raw,
        "measure": measure,
        "value": value,
        "unit": unit,
        "base_period": BASE_PERIOD,
        "period_position": position,
        "period_label_raw": period_label,
        # A disputed-alignment row is still the release's own current month, but it is not a
        # trustworthy first publication of it, so it is demoted rather than deleted (D-52).
        "is_primary_release": ("TRUE" if observation.isoformat() == release_text
                               and ALIGNMENT_DISPUTED_FLAG not in flags else "FALSE"),
        "comparability_warning": COMPARABILITY_WARNING,
        "value_status": "OK",
        "source_anomaly": "|".join(flags),
        "extraction_method": rel["method"],
        "source_file": rel["container"],
        "source_member": rel["member"],
        "source_sheet": rel["sheet"],
        "source_row": row_idx,
        "source_column_index": col,
        "source_cell_reference": f"{get_column_letter(col)}{row_idx}",
    }


def extract_all():
    releases = [extract_release(c, m, d) for c, m, d in iter_members()]
    releases.sort(key=lambda r: r["release"])
    rows, excluded = build_rows(releases)
    return releases, rows, excluded


# ----------------------------------------------------------------------------
def change_identity(rows):
    """Published change vs the index ratio. Validation only - nothing is ever recomputed."""
    index = defaultdict(dict)
    for r in rows:
        if r["measure"] == "INDEX":
            index[(r["release_month"], r["state"], r["cpi_group"])][r["period_position"]] = \
                float(r["value"])
    results, orphans = [], []
    for r in rows:
        if r["measure"] not in ("CHANGE_MOM_PCT", "CHANGE_YOY_PCT"):
            continue
        idx = index[(r["release_month"], r["state"], r["cpi_group"])]
        want = "PRIOR_MONTH" if r["measure"] == "CHANGE_MOM_PCT" else "YEAR_AGO"
        # A denominator can be legitimately absent - February 2026's year-ago column is excluded -
        # so report the orphan rather than raising out of the validator.
        if want not in idx or "CURRENT_MONTH" not in idx or not idx.get(want):
            orphans.append(r)
            continue
        implied = (idx["CURRENT_MONTH"] / idx[want] - 1) * 100
        results.append((r, implied, abs(implied - float(r["value"]))))
    return results, orphans


CLASSES = ("BYTE_IDENTICAL", "PRECISION_ONLY", "KNOWN_SOURCE_STRUCTURE_CONFLICT",
           "SUBSTANTIVE_REVISION")
KNOWN_STRUCTURE_FLAGS = (ALIGNMENT_DISPUTED_FLAG, YEAR_AGO_CONFLICT_FLAG)


def cross_release(rows):
    """Classify every repeated index observation.

    A disagreement is only a SUBSTANTIVE_REVISION when neither side is a cell already documented as
    a source-structure defect. The comparable population is whatever the canonical output contains,
    so excluding the February 2026 year-ago column changes it - the total is never hard-coded.
    """
    seen = defaultdict(list)
    for r in rows:
        if r["measure"] == "INDEX":
            seen[(r["observation_month"], r["state"], r["cpi_group"])].append(r)
    counts = Counter()
    detail = defaultdict(list)
    for key, group in seen.items():
        group.sort(key=lambda x: x["release_month"])
        # every pair, not just each later against the first: comparing only against the first
        # would hide a disagreement between two later restatements of the same month
        for i, earlier in enumerate(group):
            for later in group[i + 1:]:
                counts["compared"] += 1
                if earlier["value"] == later["value"]:
                    counts["BYTE_IDENTICAL"] += 1
                    continue
                a, b = float(earlier["value"]), float(later["value"])
                if a == b or (a != 0 and abs(a - b) / abs(a) < SUBSTANTIVE_REVISION_TOLERANCE):
                    kind = "PRECISION_ONLY"
                elif (key[0] in KNOWN_CONFLICT_OBSERVATION_MONTHS
                      or any(f in earlier["source_anomaly"] or f in later["source_anomaly"]
                             for f in KNOWN_STRUCTURE_FLAGS)):
                    kind = "KNOWN_SOURCE_STRUCTURE_CONFLICT"
                else:
                    kind = "SUBSTANTIVE_REVISION"
                counts[kind] += 1
                detail[kind].append((key, earlier, later))
    return counts, detail


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


def re_read_check(releases, rows) -> list[str]:
    grids = {(r["container"], r["member"]): r["grid"] for r in releases}
    problems = []
    for r in rows:
        grid = grids.get((r["source_file"], r["source_member"]))
        if grid is None:
            problems.append(f"{r['source_file']}: no grid for re-read")
            continue
        if not str(r["source_row"]).isdigit() or not str(r["source_column_index"]).isdigit():
            problems.append(f"{r['source_file']}: row {r['source_row']!r} / column "
                            f"{r['source_column_index']!r} is not a usable cell address")
            continue
        original = number_text(cell(grid, int(r["source_row"]), int(r["source_column_index"])))
        if original != r["value"]:
            problems.append(f"{r['source_file']} {r['source_cell_reference']}: "
                            f"re-read {original!r} but wrote {r['value']!r}")
    return problems


# ----------------------------------------------------------------------------
def validate(releases, rows, excluded) -> list[str]:
    failures: list[str] = []
    passed: list[str] = []

    def check(number, title, ok, detail=""):
        line = f"{number:2d}. {title}"
        if ok:
            passed.append(f"{line} - PASS{(' - ' + detail) if detail else ''}")
        else:
            failures.append(f"{line} - FAIL - {detail}")

    identity, orphan_changes = change_identity(rows)

    months, cursor = [], WINDOW_START
    while cursor <= WINDOW_END:
        months.append(cursor)
        cursor = add_months(cursor, 1)

    check(1, f"{EXPECTED_RELEASES} releases, {WINDOW_START} to {WINDOW_END}, contiguous",
          sorted(r["release"] for r in releases) == months,
          f"got {len(releases)}")

    check(2, "every release yields exactly one Table-5, located by content",
          all(is_table5(r["sheet"]) for r in releases)
          and len({r["sheet"] for r in releases}) == 1,
          f"sheet names {sorted({r['sheet'] for r in releases})}")

    seen_sheets = {s for r in releases for s in r["all_sheets"] if not is_table5(s)}
    check(3, "every non-Table-5 sheet is on the documented exclusion list and none is ingested",
          seen_sheets <= set(EXCLUDED_SHEETS)
          and not [x for x in rows if not is_table5(x["source_sheet"])],
          f"sheets present but excluded: {sorted(seen_sheets)}")

    check(4, "every release states the 2024 = 100 base on Table-5 itself",
          all(BASE_PATTERN.search(r["base_text"]) for r in releases)
          and {x["base_period"] for x in rows} == {BASE_PERIOD},
          f"base texts {sorted({r['base_text'] for r in releases})}")

    check(5, f"{EXPECTED_STATES} states per release, every label resolving through ref_state_zone",
          all(len(r["states"]) == EXPECTED_STATES for r in releases)
          and all(normalise(lab) in STATE_LOOKUP for r in releases for _, lab in r["states"]),
          f"state counts {sorted({len(r['states']) for r in releases})}")

    terminators = {r["release"].isoformat(): r["terminator"] for r in releases}
    footnotes = [t for t in terminators.values() if t[1].casefold().startswith("note")]
    check(6, "the table terminates on an unresolvable label, and that label is the NBS footnote",
          len(footnotes) == EXPECTED_RELEASES
          and all(t[0] == FIRST_STATE_ROW + EXPECTED_STATES for t in terminators.values()),
          f"terminator rows {sorted({t[0] for t in terminators.values()})}")

    # a non-numeric source_row is check 38's failure to report, not this one's to crash on
    below = [x for x in rows if str(x["source_row"]).isdigit()
             and int(x["source_row"]) >= FIRST_STATE_ROW + EXPECTED_STATES]
    check(7, "the footnote is never ingested as a geography",
          not [x for x in rows if x["state_raw_label"].casefold().startswith("note")]
          and not below,
          f"{len(below)} rows sourced at or below the footnote row")

    variants = defaultdict(set)
    for x in rows:
        variants[x["state_raw_label"]].add(x["release_month"])
    nas = {k: sorted(v) for k, v in variants.items() if k.casefold().startswith("nas")}
    check(8, "Nassarawa appears in exactly the 6 documented releases, Nasarawa in the other 12",
          set(nas.get("Nassarawa", [])) == NASSARAWA_RELEASES
          and len(nas.get("Nasarawa", [])) == EXPECTED_RELEASES - len(NASSARAWA_RELEASES)
          and {STATE_LOOKUP[normalise(k)][0] for k in nas} == {"Nasarawa"},
          f"{ {k: len(v) for k, v in nas.items()} }")

    unresolved = [x for x in rows
                  if normalise(x["state_raw_label"]) not in STATE_LOOKUP
                  or STATE_LOOKUP[normalise(x["state_raw_label"])] != (x["state"], x["zone"])]
    check(9, "every row's state and zone are the canonical resolution of its own raw label",
          not unresolved and not orphan_changes,
          f"{len(unresolved)} rows disagree with ref_state_zone; "
          f"{len(orphan_changes)} change rows have no index denominator")

    abuja = [x for x in rows if x["state"] == "Abuja"]
    check(10, "Abuja resolves for the FCT, in every release, with its raw label preserved",
          len({x["release_month"] for x in abuja}) == EXPECTED_RELEASES
          and {x["state_raw_label"] for x in abuja} == {"Abuja"}
          and {x["zone"] for x in abuja} == {"North Central"},
          f"{len(abuja)} rows")

    idx_rows = [x for x in rows if x["measure"] == "INDEX"]
    chg_rows = [x for x in rows if x["measure"] != "INDEX"]
    check(11, f"INDEX rows == {EXPECTED_INDEX_ROWS}", len(idx_rows) == EXPECTED_INDEX_ROWS,
          f"got {len(idx_rows)}")
    check(12, f"CHANGE rows == {EXPECTED_CHANGE_ROWS}", len(chg_rows) == EXPECTED_CHANGE_ROWS,
          f"got {len(chg_rows)}")
    check(13, f"total rows == {EXPECTED_TOTAL_ROWS}", len(rows) == EXPECTED_TOTAL_ROWS,
          f"got {len(rows)}")

    per_release = Counter(x["release_month"] for x in rows)
    conflict_release = YEAR_AGO_CONFLICT_RELEASE.isoformat()
    short = EXPECTED_ROWS_PER_RELEASE - EXPECTED_YEAR_AGO_EXCLUSIONS - EXPECTED_YOY_EXCLUSIONS
    check(14, f"{EXPECTED_ROWS_PER_RELEASE} rows in every release except {conflict_release[:7]}, "
              f"which has {short} after its two documented exclusions",
          all(v == (short if k == conflict_release else EXPECTED_ROWS_PER_RELEASE)
              for k, v in per_release.items()),
          f"{ {k[:7]: v for k, v in sorted(per_release.items()) if v != EXPECTED_ROWS_PER_RELEASE} }")

    key = Counter((x["release_month"], x["observation_month"], x["state"],
                   x["cpi_group"], x["measure"]) for x in rows)
    check(15, "logical key (release, observation, state, group, measure) is unique",
          all(v == 1 for v in key.values()),
          f"duplicates {[k for k, v in key.items() if v > 1][:3]}")

    check(16, "cpi_group is only FOOD or ALL_ITEMS, and the raw header is preserved",
          {x["cpi_group"] for x in rows} == set(CPI_GROUPS)
          and {x["cpi_group_raw"] for x in rows} == {"Food", "All Items"},
          f"{sorted({x['cpi_group_raw'] for x in rows})}")

    bad_unit = [x for x in rows
                if (x["measure"] == "INDEX") != (x["unit"] == UNIT_INDEX)]
    check(17, "measure and unit always agree: INDEX with INDEX_2024_100, changes with PERCENT",
          not bad_unit and {x["unit"] for x in rows} == {UNIT_INDEX, UNIT_PERCENT}
          and {x["measure"] for x in rows} == {"INDEX", "CHANGE_MOM_PCT", "CHANGE_YOY_PCT"},
          f"{len(bad_unit)} mismatched")

    bad_period = []
    for r in releases:
        if r["periods"] != [add_months(r["release"], -12), add_months(r["release"], -1),
                            r["release"]]:
            bad_period.append((r["release"], r["periods"]))
    check(18, "the three index periods are year-ago, prior month and the release month",
          not bad_period, f"{bad_period[:2]}")

    check(19, "change rows describe the release month; index rows keep their own month",
          all(x["observation_month"] == x["release_month"] for x in chg_rows)
          and all(x["period_position"] == "CURRENT_MONTH" for x in chg_rows)
          and {x["period_position"] for x in idx_rows} == set(PERIOD_POSITIONS),
          "")

    primary = [x for x in idx_rows if x["is_primary_release"] == "TRUE"]
    expect_primary = (STATE_GROUP_CELLS * EXPECTED_RELEASES
                      - EXPECTED_ALIGNMENT_DISPUTED_ROWS)
    check(20, f"{expect_primary} first-publication index rows: one per state-group per release, "
              f"less the {EXPECTED_ALIGNMENT_DISPUTED_ROWS} demoted April 2025 rows",
          len(primary) == expect_primary
          and all(x["observation_month"] == x["release_month"] for x in primary)
          and not [x for x in primary if ALIGNMENT_DISPUTED_FLAG in x["source_anomaly"]],
          f"{len(primary)}")

    iv = [float(x["value"]) for x in idx_rows]
    cv = [float(x["value"]) for x in chg_rows]
    check(21, "index values and change values lie in their own plausible ranges",
          all(INDEX_MIN <= v <= INDEX_MAX for v in iv)
          and all(CHANGE_MIN <= v <= CHANGE_MAX for v in cv),
          f"index {min(iv):.2f}..{max(iv):.2f}, change {min(cv):.2f}..{max(cv):.2f}")

    check(22, "the comparability warning is carried on every row",
          {x["comparability_warning"] for x in rows} == {COMPARABILITY_WARNING}, "")

    mom = [x for x in identity if x[0]["measure"] == "CHANGE_MOM_PCT"]
    yoy = [x for x in identity if x[0]["measure"] == "CHANGE_YOY_PCT"]
    mom_bad = [x for x in mom if x[2] > CHANGE_IDENTITY_TOLERANCE]
    check(23, f"published Monthly Change equals the index ratio in all "
              f"{EXPECTED_IDENTITY_COMPARISONS} comparisons",
          len(mom) == EXPECTED_IDENTITY_COMPARISONS and not mom_bad,
          f"compared {len(mom)}, breaches {len(mom_bad)}")

    # the February 2026 year-on-year rows are excluded, so this population is 74 smaller than the
    # monthly one
    expect_yoy = EXPECTED_IDENTITY_COMPARISONS - EXPECTED_YOY_EXCLUSIONS
    yoy_bad = [x for x in yoy if x[2] > CHANGE_IDENTITY_TOLERANCE]
    documented = {(k[0], k[1], k[2], k[3]) for k in HAND_ROUNDED_CHANGE}
    got = {(x[0]["release_month"], x[0]["state"], x[0]["cpi_group"], x[0]["measure"])
           for x in yoy_bad}
    check(24, f"published Annual Change equals the index ratio in "
              f"{expect_yoy - len(HAND_ROUNDED_CHANGE)} of {expect_yoy}, with "
              f"{len(HAND_ROUNDED_CHANGE)} documented exception",
          len(yoy) == expect_yoy and got == documented,
          f"compared {len(yoy)}, breaches {len(yoy_bad)} at {sorted(got)}")

    flagged = {(x["release_month"], x["state"], x["cpi_group"], x["measure"]) for x in rows
               if HAND_ROUNDED_CHANGE_FLAG in x["source_anomaly"]}
    check(25, "the hand-rounded published change is preserved byte-exact and flagged",
          flagged == documented
          and all(x["value"] == HAND_ROUNDED_CHANGE[
              (x["release_month"], x["state"], x["cpi_group"], x["measure"])]
              for x in rows if HAND_ROUNDED_CHANGE_FLAG in x["source_anomaly"]),
          f"flagged {sorted(flagged)}")

    counts, detail = cross_release(rows)
    check(26, "every repeated index observation falls into exactly one of the four classes",
          counts["compared"] > 0
          and counts["compared"] == sum(counts[c] for c in CLASSES),
          f"{ {c: counts[c] for c in CLASSES} } of {counts['compared']}")

    check(27, "no disagreement involving a documented source-structure defect is counted as a "
              "substantive revision",
          not [t for t in detail["SUBSTANTIVE_REVISION"]
               if any(f in t[1]["source_anomaly"] or f in t[2]["source_anomaly"]
                      for f in KNOWN_STRUCTURE_FLAGS)],
          f"substantive {counts['SUBSTANTIVE_REVISION']}, "
          f"known-structure {counts['KNOWN_SOURCE_STRUCTURE_CONFLICT']}")

    excl_idx = [e for e in excluded if e["measure"] == "INDEX"]
    excl_yoy = [e for e in excluded if e["measure"] == "CHANGE_YOY_PCT"]
    conflict = YEAR_AGO_CONFLICT_RELEASE.isoformat()

    check(28, f"zero {conflict[:7]} year-ago INDEX rows survive into the canonical output",
          not [x for x in rows if x["release_month"] == conflict
               and x["measure"] == "INDEX" and x["period_position"] == "YEAR_AGO"], "")

    check(29, f"zero {conflict[:7]} CHANGE_YOY_PCT rows survive into the canonical output",
          not [x for x in rows if x["release_month"] == conflict
               and x["measure"] == "CHANGE_YOY_PCT"], "")

    check(30, f"the {EXPECTED_YEAR_AGO_EXCLUSIONS} excluded year-ago INDEX cells are recorded as "
             f"evidence with full provenance",
          len(excl_idx) == EXPECTED_YEAR_AGO_EXCLUSIONS
          and all(e["release_month"] == conflict and e["period_position"] == "YEAR_AGO"
                  and e["exclusion_flag"] == YEAR_AGO_CONFLICT_FLAG
                  and e["published_value"] and e["source_cell_reference"] for e in excl_idx),
          f"{len(excl_idx)} cells, columns "
          f"{sorted({int(e['source_column_index']) for e in excl_idx})}")

    check(31, f"the {EXPECTED_YOY_EXCLUSIONS} excluded year-on-year cells are recorded as evidence "
             f"with full provenance",
          len(excl_yoy) == EXPECTED_YOY_EXCLUSIONS
          and all(e["release_month"] == conflict
                  and e["exclusion_flag"] == YEAR_AGO_CONFLICT_FLAG
                  and e["published_value"] and e["source_cell_reference"] for e in excl_yoy),
          f"{len(excl_yoy)} cells, columns "
          f"{sorted({int(e['source_column_index']) for e in excl_yoy})}")

    disputed = [x for x in rows if ALIGNMENT_DISPUTED_FLAG in x["source_anomaly"]]
    apr = ALIGNMENT_DISPUTED_RELEASE.isoformat()
    check(32, f"all {EXPECTED_ALIGNMENT_DISPUTED_ROWS} April 2025 current-month INDEX rows carry "
             f"{ALIGNMENT_DISPUTED_FLAG}",
          len(disputed) == EXPECTED_ALIGNMENT_DISPUTED_ROWS
          and all(x["release_month"] == apr and x["measure"] == "INDEX"
                  and x["period_position"] == "CURRENT_MONTH" for x in disputed),
          f"{len(disputed)} rows")

    check(33, "every disputed April 2025 row has is_primary_release = FALSE",
          all(x["is_primary_release"] == "FALSE" for x in disputed), "")

    apr_cur = {(x["state"], x["cpi_group"]): x["value"] for x in rows
               if x["release_month"] == apr and x["measure"] == "INDEX"
               and x["period_position"] == "CURRENT_MONTH"}
    reread_apr = {}
    for r in releases:
        if r["release"] != ALIGNMENT_DISPUTED_RELEASE:
            continue
        for row_idx, raw in r["states"]:
            st = STATE_LOOKUP[normalise(raw)][0]
            for gi, grp in enumerate(CPI_GROUPS):
                reread_apr[(st, grp)] = number_text(
                    cell(r["grid"], row_idx, INDEX_COLUMNS[2][gi]))
    check(34, "no April 2025 value was re-aligned or replaced - every one still equals its own cell",
          apr_cur == reread_apr and len(apr_cur) == EXPECTED_ALIGNMENT_DISPUTED_ROWS,
          f"{len(apr_cur)} values compared against a fresh read of the April workbook")

    later = [x for x in rows if x["observation_month"] == apr and x["measure"] == "INDEX"
             and x["release_month"] in ("2025-05-01", "2026-04-01")]
    agree = 0
    may = {(x["state"], x["cpi_group"]): x["value"] for x in later
           if x["release_month"] == "2025-05-01"}
    nxt = {(x["state"], x["cpi_group"]): x["value"] for x in later
           if x["release_month"] == "2026-04-01"}
    agree = sum(1 for k in may if k in nxt and may[k] == nxt[k])
    conflicting = sum(1 for k in may if k in apr_cur and may[k] != apr_cur[k])
    triple = {x["release_month"]: x["value"] for x in rows
              if x["observation_month"] == apr and x["measure"] == "INDEX"
              and x["state"] == ALIGNMENT_TRIPLE_VALUE[0]
              and x["cpi_group"] == ALIGNMENT_TRIPLE_VALUE[1]}
    check(35, f"the May 2025 and April 2026 restatements are untouched, agree with each other on "
              f"{EXPECTED_LATER_RESTATEMENTS_AGREE} of {STATE_GROUP_CELLS}, and contradict "
              f"{EXPECTED_ALIGNMENT_CONFLICTS} of the April current-month values; the one they "
              f"also disagree on is published as three different values",
          len(may) == STATE_GROUP_CELLS and len(nxt) == STATE_GROUP_CELLS
          and agree == EXPECTED_LATER_RESTATEMENTS_AGREE
          and conflicting == EXPECTED_ALIGNMENT_CONFLICTS
          and not [x for x in later if ALIGNMENT_DISPUTED_FLAG in x["source_anomaly"]]
          and triple == ALIGNMENT_TRIPLE_VALUE[2],
          f"May/April-2026 agree on {agree}/{STATE_GROUP_CELLS}; "
          f"{conflicting} contradict the April release; "
          f"{ALIGNMENT_TRIPLE_VALUE[0]} {ALIGNMENT_TRIPLE_VALUE[1]} = {triple}")


    check(36, "no value is empty and value_status is OK throughout",
          not [x for x in rows if x["value"] == ""]
          and {x["value_status"] for x in rows} == {"OK"}, "")

    check(37, "no content below row 42 or right of column 12 in any Table-5",
          all(r["extent"] == (FIRST_STATE_ROW + EXPECTED_STATES, 12) for r in releases),
          f"extents {sorted({r['extent'] for r in releases})}")

    mismatched = [x for x in rows
                  if x["source_cell_reference"] !=
                  f"{get_column_letter(int(x['source_column_index']))}{x['source_row']}"]
    missing = [x for x in rows if not x["source_file"] or not x["source_sheet"]
               or not x["source_row"] or not x["source_cell_reference"]]
    check(38, "every row carries complete provenance and a self-consistent A1 reference",
          not mismatched and not missing,
          f"mismatched {len(mismatched)}, missing {len(missing)}")

    check(39, "index rows cite columns 3-8 and change rows columns 9-12",
          {int(x["source_column_index"]) for x in idx_rows} == {3, 4, 5, 6, 7, 8}
          and {int(x["source_column_index"]) for x in chg_rows} == {9, 10, 11, 12}, "")

    reread = re_read_check(releases, rows)
    check(40, "every written value re-reads identically from its source cell",
          not reread, f"{len(reread)} mismatches: {reread[:2]}")

    methods = {x["extraction_method"] for x in rows}
    check(41, "the March 2026 .xls is read by xlrd and every other release by openpyxl",
          methods == {"XLSX_OPENPYXL", f"XLS_XLRD_{xlrd.__version__}"}
          and {x["release_month"] for x in rows
               if x["extraction_method"].startswith("XLS_XLRD")} == {"2026-03-01"},
          f"{sorted(methods)}")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nbs/cpi")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/nbs/cpi")
    check(42, f"all {n1 + n2} acquired CPI source files match their recorded SHA-256",
          n1 + n2 > 0 and not bad1 and not bad2, f"{(bad1 + bad2)[:3]}")

    for path in (OUT_PATH, REPORT_PATH):
        assert_outside_raw(path)
    check(43, "no output path resolves inside data/raw/", True, "assert_outside_raw passed")

    if failures:
        raise ValidationError(
            f"{len(failures)} validation check(s) failed:\n" + "\n".join(failures))
    return passed


# ----------------------------------------------------------------------------
def write_csv(rows):
    target = assert_outside_raw(OUT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(releases, rows, excluded, passed):
    idx_rows = [x for x in rows if x["measure"] == "INDEX"]
    chg_rows = [x for x in rows if x["measure"] != "INDEX"]
    identity, orphan_changes = change_identity(rows)
    mom = [x for x in identity if x[0]["measure"] == "CHANGE_MOM_PCT"]
    yoy = [x for x in identity if x[0]["measure"] == "CHANGE_YOY_PCT"]
    counts, detail = cross_release(rows)

    lines = []
    add = lines.append
    add("# NBS CPI (state) - Cleaning Validation")
    add("")
    add(f"Generated by `src/cleaning/clean_nbs_cpi.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.")
    add("")
    add("> **What this dataset is.** The NBS CPI **state** table (`Table-5`) only - Food and All "
        "Items, by state, on the 2024 = 100 base. The national, urban, rural and pre-rebasing "
        "sheets in the same workbooks are deliberately not processed.")
    add("")
    add("## Environment")
    add("")
    add(f"- `xlrd` **{xlrd.__version__}** was installed so the genuine OLE2 `.xls` workbook in "
        f"`CPI_Report_March_2026.zip` could be read. The project has no dependency manifest, so "
        f"the version is recorded here rather than in a new one.")
    add(f"- `openpyxl` {openpyxl.__version__} reads the other 17 releases.")
    add("- `extraction_method` records which reader produced each row.")
    add("")
    add("## Scope and exclusions")
    add("")
    add(f"- **Releases processed:** {len(releases)} ({WINDOW_START} to {WINDOW_END}, no gaps)")
    add(f"- **Rows:** {len(rows)} - {len(idx_rows)} INDEX, {len(chg_rows)} change")
    add("")
    add("Nine sheets sit in these workbooks and none is ingested:")
    add("")
    add("| Excluded sheet | Why |")
    add("|---|---|")
    add("| `Table1`, `Table2`, `Table3`, `Table4` | national / urban / rural series - out of scope "
        "for a state dataset |")
    add("| `Table1 (2)`, `Table2 (2)`, `Table3 (2)`, `Table3 (3)`, `Table4 (2)` | pre-rebasing "
        "working sheets: two bases in identically-headed adjacent columns, ~96,857 `#REF!` cells "
        "(all in `Table1 (2)`), and `Table3 (3)` an exact duplicate of `Table3 (2)` |")
    add("")
    add("A check asserts that every non-Table-5 sheet present is on this list, so a newly-added "
        "sheet fails the run instead of being ignored.")
    add("")
    add("Two profiling anomalies stay documented but outside this dataset: the **October and "
        "November 2025 `Table2`** sheets publish a 1995-base series under a `Base Year 2024 = 100` "
        "title (All-Items runs 1.93 to 128.89 over 370 rows), and the `(2)` sheets carry the "
        "dual-base history.")
    add("")
    add("## Row arithmetic")
    add("")
    add("| | Per release | x 18 releases |")
    add("|---|---|---|")
    add(f"| INDEX - {EXPECTED_STATES} states x {len(CPI_GROUPS)} groups x {INDEX_PERIODS} periods "
        f"| {EXPECTED_STATES*len(CPI_GROUPS)*INDEX_PERIODS} | **{len(idx_rows)}** |")
    add(f"| CHANGE - {EXPECTED_STATES} x {len(CPI_GROUPS)} x {CHANGE_MEASURES} measures "
        f"| {EXPECTED_STATES*len(CPI_GROUPS)*CHANGE_MEASURES} | **{len(chg_rows)}** |")
    add(f"| **Total** | **{EXPECTED_ROWS_PER_RELEASE}** | **{len(rows)}** |")
    add("")
    add("## Measures, units and the base")
    add("")
    add("| measure | unit | Rows | Source columns |")
    add("|---|---|---|---|")
    for measure, unit in (("INDEX", UNIT_INDEX), ("CHANGE_YOY_PCT", UNIT_PERCENT),
                          ("CHANGE_MOM_PCT", UNIT_PERCENT)):
        sel = [x for x in rows if x["measure"] == measure]
        cols = sorted({int(x["source_column_index"]) for x in sel})
        add(f"| `{measure}` | `{unit}` | {len(sel)} | {cols} |")
    add("")
    add("**An index and a rate never share an unlabelled numeric field.** Index values run "
        f"{min(float(x['value']) for x in idx_rows):.2f} to "
        f"{max(float(x['value']) for x in idx_rows):.2f}; change values run "
        f"{min(float(x['value']) for x in chg_rows):.2f} to "
        f"{max(float(x['value']) for x in chg_rows):.2f}. Those ranges overlap, which is exactly "
        "why `measure` and `unit` are mandatory dimensions rather than conveniences.")
    add("")
    add(f"Every release states its own base on `Table-5` row {BASE_ROW}: "
        f"`{releases[0]['base_text']}`. The base is **never** inherited from `Table1`, which "
        "carries two contradictory base titles - `Base September 1985 = 100` on row 1 and "
        "`Base: 2024 = 100` on row 2 - in all 18 releases (D-47).")
    add("")
    add("## Period structure")
    add("")
    add("One release publishes three index months and describes one of them with two change rates.")
    add("")
    add("| Release | Year-ago | Prior month | Current | Change rows describe |")
    add("|---|---|---|---|---|")
    for r in releases:
        add(f"| {r['release']} | {r['periods'][0]} | {r['periods'][1]} | {r['periods'][2]} | "
            f"{r['periods'][2]} |")
    add("")
    add("## Geography")
    add("")
    add(f"{EXPECTED_STATES} states and the FCT in every release, resolving through "
        "`ref_state_zone.csv`. **The table is terminated by a label that stops resolving to a "
        "state, never by the literal word \"Note\"** (D-50).")
    add("")
    add("| Release | Terminator row | Terminator label |")
    add("|---|---|---|")
    add(f"| all {len(releases)} | {FIRST_STATE_ROW + EXPECTED_STATES} | "
        f"`{releases[0]['terminator'][1][:70]}...` |")
    add("")
    variants = defaultdict(set)
    for x in rows:
        if x["state"] == "Nasarawa":
            variants[x["state_raw_label"]].add(x["release_month"])
    add("Spelling variant, preserved in `state_raw_label` and flagged:")
    add("")
    add("| Raw label | Releases |")
    add("|---|---|")
    for k in sorted(variants):
        add(f"| `{k}` | {len(variants[k])} - {', '.join(sorted(m[:7] for m in variants[k]))} |")
    add("")
    add("It is not a one-way correction: 2025-05 uses `Nasarawa`, then 2025-06, 2025-07 and "
        "2025-08 revert to `Nassarawa` before it settles from 2025-09.")
    add("")
    add("## Published change rates - validated, never recomputed")
    add("")
    add(f"The published rates are ingested as published. The index-ratio identity is a **check**, "
        f"with a tolerance of {CHANGE_IDENTITY_TOLERANCE:g}:")
    add("")
    add("| Check | Compared | Within tolerance | Exceptions |")
    add("|---|---|---|---|")
    add(f"| `Monthly Change` vs current/prior | {len(mom)} | "
        f"{sum(1 for x in mom if x[2] <= CHANGE_IDENTITY_TOLERANCE)} | 0 |")
    add(f"| `Annual Change` vs current/year-ago | {len(yoy)} | "
        f"{sum(1 for x in yoy if x[2] <= CHANGE_IDENTITY_TOLERANCE)} | "
        f"{sum(1 for x in yoy if x[2] > CHANGE_IDENTITY_TOLERANCE)} |")
    add("")
    add("The single exception is a **hand-rounded published cell**, preserved exactly and flagged "
        f"`{HAND_ROUNDED_CHANGE_FLAG}`:")
    add("")
    for x in yoy:
        if x[2] > CHANGE_IDENTITY_TOLERANCE:
            r = x[0]
            add(f"- **{r['release_month']} {r['state']} {r['cpi_group']}** - "
                f"`{r['source_file']}` sheet `{r['source_sheet']}` cell "
                f"`{r['source_cell_reference']}` reads **{r['value']}**, while the index ratio "
                f"implies {x[1]:.8f}. Every other Annual Change in that release carries 14-15 "
                f"decimal places; this one is a round 2-dp number. NBS published it; it is not "
                f"corrected.")
    add("")
    add("## Two documented source defects")
    add("")
    add("### 1. February 2026's year-ago column is labelled 2025-02 but holds 2025-01 data")
    add("")
    add(f"`{excluded[0]['source_file']}` sheet `{excluded[0]['source_sheet']}` row "
        f"{HEADER_PERIOD_ROW} column C reads **2025-02-01**. All "
        f"{EXPECTED_YEAR_AGO_EXCLUSIONS} values beneath it are byte-identical to the published "
        f"**January 2025** column and none matches published February 2025. The March 2026 release "
        f"is the control and matches its own year-ago month 74/74.")
    add("")
    add(f"**Both the {EXPECTED_YEAR_AGO_EXCLUSIONS} year-ago INDEX cells and the "
        f"{EXPECTED_YOY_EXCLUSIONS} `CHANGE_YOY_PCT` cells are excluded from the canonical "
        f"output** - the year-on-year rates are computed from that same disputed denominator, so "
        f"they cannot be represented as true February 2026 year-on-year changes. They are **not** "
        f"relabelled to January, **not** published as February, and **not** recomputed from "
        f"another release (D-51).")
    add("")
    add(f"All {len(excluded)} excluded cells are retained as evidence with full provenance, "
        f"flagged `{YEAR_AGO_CONFLICT_FLAG}`. A sample:")
    add("")
    add("| Cell | State | Group | Measure | Published value |")
    add("|---|---|---|---|---|")
    for e in excluded[:3] + [e for e in excluded if e["measure"] == "CHANGE_YOY_PCT"][:2]:
        add(f"| `{e['source_cell_reference']}` | {e['state']} | {e['cpi_group']} | "
            f"`{e['measure']}` | {e['published_value']} |")
    add("")
    add("### 2. April 2025 assigns 67 of 74 values to states two later releases contradict")
    add("")
    add(f"The published values are kept **exactly as NBS published them** - nothing shifted, "
        f"replaced or relabelled. All {EXPECTED_ALIGNMENT_DISPUTED_ROWS} April 2025 current-month "
        f"INDEX rows carry `{ALIGNMENT_DISPUTED_FLAG}` and `is_primary_release = FALSE` (D-52).")
    add("")
    add("| Evidence | |")
    add("|---|---|")
    add(f"| April current-month rows flagged | {EXPECTED_ALIGNMENT_DISPUTED_ROWS} |")
    add(f"| Contradicted by both later restatements | {EXPECTED_ALIGNMENT_CONFLICTS} |")
    add(f"| The two later restatements agree with each other on | "
        f"{EXPECTED_LATER_RESTATEMENTS_AGREE} of {STATE_GROUP_CELLS} |")
    add("| April's own Monthly/Annual Change columns | internally consistent with its own "
        "misaligned block, to 1e-14 |")
    add("")
    add("From Bayelsa (row 11) down, each April row carries the value the later releases assign to "
        "the **next** state - `Bayelsa 115.819464` in April is `Benue 115.819464` in both May 2025 "
        "and April 2026. Because the percentages were already computed from the misaligned block, "
        "the defect predates publication. **This is a source alignment defect, not a revision.**")
    add("")
    tri = ALIGNMENT_TRIPLE_VALUE
    add(f"The two later restatements themselves disagree on exactly one cell: "
        f"**{tri[0]} {tri[1]}, observation 2025-04**, is published as three different values - "
        + ", ".join(f"`{v}` ({k[:7]})" for k, v in sorted(tri[2].items())) + ".")
    add("")
    add("## Cross-release comparison")
    add("")
    add("`Table-5` republishes its year-ago and prior-month columns, so the same state-month is "
        "published up to three times. **Every pair is compared**, not just each later publication "
        "against the first - otherwise a disagreement between two later restatements would be "
        "invisible. The comparable population depends on what the canonical output contains, so it "
        "is computed, never assumed.")
    add("")
    add("| Classification | Count |")
    add("|---|---|")
    for c in CLASSES:
        bold = "**" if c == "SUBSTANTIVE_REVISION" else ""
        add(f"| {bold}`{c}`{bold} | {bold}{counts[c]}{bold} |")
    add(f"| **Compared** | **{counts['compared']}** |")
    add("")
    add(f"**Genuine substantive revisions: {counts['SUBSTANTIVE_REVISION']}.** Every large "
        f"disagreement is explained by one of the two documented source defects, and the single "
        f"`PRECISION_ONLY` difference is:")
    add("")
    for key, a, b in detail["PRECISION_ONLY"]:
        ra = abs(float(a["value"]) - float(b["value"])) / abs(float(a["value"]))
        add(f"- {key[0]} {key[1]} {key[2]}: `{a['value']}` ({a['release_month'][:7]}) vs "
            f"`{b['value']}` ({b['release_month'][:7]}), relative difference {ra:.1e}")
    add("")
    add("Nothing is collapsed onto a latest value: every publication keeps its own row, told apart "
        f"by `release_month`, so any disagreement stays auditable. The tolerance is "
        f"{SUBSTANTIVE_REVISION_TOLERANCE:g}.")
    add("")
    add("## The comparability warning")
    add("")
    add(f"Every one of the {len(rows)} rows carries NBS's own restriction verbatim:")
    add("")
    add(f"> {COMPARABILITY_WARNING}")
    add("")
    add("It is printed inside the source table, in the label column of the row below the last "
        "state. **These index levels must not be used to rank states by absolute cost.** A "
        "state's values are comparable with that same state's other months, not with another "
        "state's.")
    add("")
    add("## Validation checks")
    add("")
    for line in passed:
        add(f"- {line}")
    add("")
    add("## Raw integrity")
    add("")
    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nbs/cpi")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/nbs/cpi")
    n3, bad3 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/")
    n4, bad4 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/")
    add(f"- CPI source files verified: **{n1 + n2}** ({n1} original + {n2} extension), "
        f"{len(bad1) + len(bad2)} problems.")
    add(f"- Whole acquired corpus: **{n3 + n4}** files, {len(bad3) + len(bad4)} problems.")
    add("- Nothing under `data/raw/` is opened for writing; `assert_outside_raw()` guards every "
        "output path.")
    add("")

    target = assert_outside_raw(REPORT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    releases, rows, excluded = extract_all()
    idx = sum(1 for x in rows if x["measure"] == "INDEX")
    mom = sum(1 for x in rows if x["measure"] == "CHANGE_MOM_PCT")
    yoy = sum(1 for x in rows if x["measure"] == "CHANGE_YOY_PCT")
    print(f"xlrd       {xlrd.__version__}")
    print(f"releases   {len(releases)}  {releases[0]['release']} .. {releases[-1]['release']}")
    print(f"rows       {len(rows)}  (INDEX {idx}, MoM {mom}, YoY {yoy})")
    print(f"excluded   {len(excluded)} published cells kept as evidence, never as observations")
    counts, _ = cross_release(rows)
    print(f"repeats    { {c: counts[c] for c in CLASSES} } of {counts['compared']}")
    passed = validate(releases, rows, excluded)
    print(f"validation {len(passed)}/{len(passed)} checks pass")
    write_csv(rows)
    write_report(releases, rows, excluded, passed)
    for path in (OUT_PATH, REPORT_PATH):
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
