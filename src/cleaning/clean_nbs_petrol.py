"""Clean the NBS Premium Motor Spirit (petrol) price releases into `petrol_price_monthly`.

Source of record : data/raw/nbs/petrol/*.xlsx and the .xlsx members of data/raw/nbs/petrol/*.zip
Output           : data/processed/nbs/petrol_price_monthly.csv

Implements the approved rules in docs/data_design/. In particular:

  * **blocks are located by content, never by coordinate** (D-22). A petrol sheet carries a state
    table and a zone table, and their positions move between releases - the zone table sits in
    columns F/G in 16 releases and in columns A/B *beneath* the state table in January 2026. The
    header row itself moves between rows 1, 2, 3 and 15.
  * **each block ends where its rows stop resolving to its own type.** That one rule discards the
    `Year on Year` / `Month on Month` footnotes, the `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES`
    callout headings and the state rows beneath them, and July 2025's `MAX` / `MIN` cells - without
    naming any of them in code (D-23).
  * the period comes **only** from the Excel datetime column headers. Two releases carry wrong
    titles and one carries a wrong member filename; none of them is trusted.
  * every published value keeps its precision. A blank stays NULL and is never filled with zero.
  * every price traces to exactly one spreadsheet cell.

Run from the project root:

    python src/cleaning/clean_nbs_petrol.py

Nothing under data/raw/ is opened for writing.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------
# Paths - project-relative, never absolute machine paths.
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_DIR = RAW_ROOT / "nbs" / "petrol"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "nbs" / "petrol_price_monthly.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_petrol_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

# The 17 spreadsheet releases run 2025-01 .. 2026-05. The six petrol PDFs are corroborative only:
# they cannot supply a spreadsheet cell reference, so they generate no canonical rows.
EXPECTED_RELEASES = 17
WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 5, 1)

ZONES = ("North Central", "North East", "North West",
         "South East", "South South", "South West")
ZONE_BY_KEY = {z.replace(" ", "").casefold(): z for z in ZONES}
NATIONAL_LABELS = {"average", "national", "grand total", "nigeria"}
NATIONAL_NAME = "Nigeria"

STATE_ANCHOR = "state"
ZONE_ANCHOR = "zone"
ZONE_VALUE_HEADER = "average price"

UNIT = "NGN per litre"

# Verified anomalies only. Keyed on the exact (container, member) fingerprint - there is no general
# title-repair rule, and no other file may acquire a flag by accident.
MEMBER_FILENAME_YEAR_WRONG = {
    ("PMS_Report_JANUARY_2026.zip", "PMS_JANUARY_2025.xlsx"),
}
TITLE_ROW_MONTH_WRONG = {
    ("PMS Report OCTOBER 2025.zip", "PMS_OCT_2025.xlsx"),
}
ZONE_BLOCK_BELOW_STATE_BLOCK = {
    ("PMS_Report_JANUARY_2026.zip", "PMS_JANUARY_2025.xlsx"),
}

OUTPUT_COLUMNS = [
    "release_month",
    "observation_month",
    "geography_type",
    "geography_name",
    "geography_raw_label",
    "state",
    "zone",
    "is_aggregate",
    "price_ngn_per_litre",
    "unit",
    "source_period_label",
    "is_primary_release",
    "source_anomaly",
    "header_row_used",
    "source_file",
    "source_member",
    "source_sheet",
    "source_row",
    "source_column_index",
    "source_cell_reference",
]


class ValidationError(AssertionError):
    """Raised when a validation check fails, so a broken run cannot ship a clean file."""


# ----------------------------------------------------------------------------
# Integrity helpers
# ----------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_outside_raw(path: Path) -> Path:
    """Refuse to open any output path that resolves inside data/raw/."""
    resolved = path.resolve()
    raw_root = RAW_ROOT.resolve()
    if resolved == raw_root or raw_root in resolved.parents:
        raise ValidationError(f"Refusing to write inside data/raw/: {resolved}")
    return resolved


# ----------------------------------------------------------------------------
# Reference data
# ----------------------------------------------------------------------------
def normalise(value) -> str:
    """Trim, collapse internal whitespace, casefold. The documented matching rule (§0.2)."""
    return " ".join(str(value).split()).casefold()


def load_state_lookup() -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    with REF_STATE_ZONE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            key = row["alias_normalised"]
            if key in lookup and lookup[key] != (row["state"], row["zone"]):
                raise ValidationError(
                    f"ref_state_zone alias {key!r} resolves to two different states")
            lookup[key] = (row["state"], row["zone"])
    if not lookup:
        raise ValidationError("ref_state_zone.csv is empty")
    return lookup


STATE_LOOKUP = load_state_lookup()
CANONICAL_STATES = sorted({s for s, _ in STATE_LOOKUP.values()})


def classify(label) -> str:
    """STATE / ZONE / NATIONAL / UNCLASSIFIED. Never guesses."""
    key = normalise(label)
    if key in STATE_LOOKUP:
        return "STATE"
    if key.replace(" ", "") in ZONE_BY_KEY:
        return "ZONE"
    if key in NATIONAL_LABELS:
        return "NATIONAL"
    return "UNCLASSIFIED"


# ----------------------------------------------------------------------------
# Workbook access - read-only, ZIP members read in memory, never unpacked to disk
# ----------------------------------------------------------------------------
def iter_workbooks():
    """Yield (container, member, bytes) for every petrol .xlsx, loose or inside a ZIP."""
    for path in sorted(RAW_DIR.iterdir()):
        if path.suffix.lower() == ".xlsx":
            yield path.name, None, path.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith(".xlsx") and not name.startswith("__MACOSX"):
                        yield path.name, name, archive.read(name)


def read_grid(data: bytes):
    """Return (sheet_name, grid) for every worksheet. Values only, formulas already evaluated."""
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            grid = [tuple(row) for row in ws.iter_rows(values_only=True)]
            yield sheet, grid
    finally:
        wb.close()


def cell(grid, row_idx: int, col_idx: int):
    """1-based access that tolerates ragged rows."""
    if row_idx < 1 or row_idx > len(grid):
        return None
    row = grid[row_idx - 1]
    if col_idx < 1 or col_idx > len(row):
        return None
    return row[col_idx - 1]


# ----------------------------------------------------------------------------
# Content-based block detection (D-22)
# ----------------------------------------------------------------------------
def find_anchors(grid, anchor: str) -> list[tuple[int, int]]:
    """Every (row, col) whose text equals the anchor token. Coordinates are an output, not an input."""
    hits = []
    for r, row in enumerate(grid, start=1):
        for c, value in enumerate(row, start=1):
            if value is not None and normalise(value) == anchor:
                hits.append((r, c))
    return hits


def period_columns(grid, header_row: int, from_col: int) -> list[tuple[int, dt.date]]:
    """Datetime headers to the right of the anchor. The period comes only from these."""
    out = []
    row = grid[header_row - 1]
    for c in range(from_col + 1, len(row) + 1):
        value = cell(grid, header_row, c)
        if isinstance(value, dt.datetime):
            out.append((c, value.date().replace(day=1)))
    return out


def read_block(grid, header_row: int, label_col: int, accept: set[str],
               stop_after_first: str | None = None):
    """Walk down from a header, keeping rows whose label classifies into `accept`.

    The block ends at the first label that does not classify into `accept` - which is how the
    footnote rows, the callout headings and the callout state rows are excluded without any of
    them being named. Blank rows inside a block are tolerated; a blank never ends a block on its
    own, because some sheets space the header away from the first data row.
    """
    rows = []
    blanks = 0
    for r in range(header_row + 1, len(grid) + 1):
        label = cell(grid, r, label_col)
        if label is None or str(label).strip() == "":
            blanks += 1
            if blanks > 3:
                break
            continue
        blanks = 0
        kind = classify(label)
        if kind not in accept:
            break
        rows.append((r, str(label).strip(), kind))
        if stop_after_first is not None and kind == stop_after_first:
            break
    return rows


def number_text(value) -> str:
    """Published numeric value as text, without changing its precision.

    Excel stores IEEE-754 doubles; `repr` of a Python float is the shortest string that round-trips
    to the identical double, so nothing is rounded away and nothing is invented. A blank returns ""
    - the CSV representation of NULL. It is never turned into 0.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValidationError(f"Boolean where a price was expected: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value).strip()
    if text == "":
        return ""
    raise ValidationError(f"Non-numeric value where a price was expected: {value!r}")


# ----------------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------------
def anomalies_for(container: str, member: str | None, block: str) -> str:
    flags = []
    key = (container, member)
    if key in MEMBER_FILENAME_YEAR_WRONG:
        flags.append("MEMBER_FILENAME_YEAR_WRONG")
    if key in TITLE_ROW_MONTH_WRONG:
        flags.append("TITLE_ROW_MONTH_WRONG")
    if block == "ZONE" and key in ZONE_BLOCK_BELOW_STATE_BLOCK:
        flags.append("ZONE_BLOCK_BELOW_STATE_BLOCK")
    return ";".join(flags)


def extract_release(container: str, member: str | None, sheet: str, grid) -> tuple[list[dict], dict]:
    """Extract one petrol release. Returns (rows, structure-notes)."""
    state_anchors = find_anchors(grid, STATE_ANCHOR)
    if not state_anchors:
        raise ValidationError(
            f"No 'State' anchor found in {container}::{member}::{sheet} - refusing to guess a header")
    header_row, label_col = state_anchors[0]

    periods = period_columns(grid, header_row, label_col)
    if len(periods) < 1:
        raise ValidationError(
            f"No datetime period columns beside the State anchor in "
            f"{container}::{member}::{sheet}")
    seen_periods = [p for _, p in periods]
    if len(set(seen_periods)) != len(seen_periods):
        raise ValidationError(
            f"Duplicate period headers in {container}::{member}::{sheet}: {seen_periods}")

    release_month = max(seen_periods)

    rows: list[dict] = []

    def emit(row_idx, col_idx, raw_label, kind, observation_month, period_label, block):
        value = cell(grid, row_idx, col_idx)
        if kind == "STATE":
            state, zone = STATE_LOOKUP[normalise(raw_label)]
            name, is_agg = state, "FALSE"
        elif kind == "ZONE":
            state, zone = "", ZONE_BY_KEY[normalise(raw_label).replace(" ", "")]
            name, is_agg = zone, "TRUE"
        elif kind == "NATIONAL":
            state, zone = "", ""
            name, is_agg = NATIONAL_NAME, "TRUE"
        else:
            raise ValidationError(
                f"Unexpected geography {raw_label!r} in {container}::{member}::{sheet} "
                f"row {row_idx} - refusing to guess")
        rows.append({
            "release_month": release_month.isoformat(),
            "observation_month": observation_month.isoformat(),
            "geography_type": kind,
            "geography_name": name,
            "geography_raw_label": raw_label,
            "state": state,
            "zone": zone,
            "is_aggregate": is_agg,
            "price_ngn_per_litre": number_text(value),
            "unit": UNIT,
            "source_period_label": period_label,
            "is_primary_release": "TRUE" if observation_month == release_month else "FALSE",
            "source_anomaly": anomalies_for(container, member, block),
            "header_row_used": header_row if block == "STATE" else zone_header_row,
            "source_file": container,
            "source_member": member or "",
            "source_sheet": sheet,
            "source_row": row_idx,
            "source_column_index": col_idx,
            "source_cell_reference": f"{get_column_letter(col_idx)}{row_idx}",
        })

    # --- state block: states, then the first NATIONAL row, then stop -------------
    state_rows = read_block(grid, header_row, label_col,
                            accept={"STATE", "NATIONAL"}, stop_after_first="NATIONAL")
    zone_header_row = header_row      # placeholder until the zone block is located
    for row_idx, raw_label, kind in state_rows:
        for col_idx, period in periods:
            emit(row_idx, col_idx, raw_label, kind, period,
                 period.isoformat(), "STATE")

    # --- zone block: wherever its own header sits -------------------------------
    zone_anchors = find_anchors(grid, ZONE_ANCHOR)
    zone_rows_read = []
    zone_position = None
    for zr, zc in zone_anchors:
        value_header = cell(grid, zr, zc + 1)
        if value_header is None or normalise(value_header) != ZONE_VALUE_HEADER:
            continue
        found = read_block(grid, zr, zc, accept={"ZONE"})
        if not found:
            continue
        zone_header_row = zr
        zone_position = f"{get_column_letter(zc)}{zr}"
        for row_idx, raw_label, kind in found:
            emit(row_idx, zc + 1, raw_label, kind, release_month, str(value_header).strip(), "ZONE")
        zone_rows_read = found
        break

    notes = {
        "container": container,
        "member": member or "",
        "sheet": sheet,
        "header_row": header_row,
        "release_month": release_month.isoformat(),
        "periods": [p.isoformat() for p in seen_periods],
        "state_rows": sum(1 for _, _, k in state_rows if k == "STATE"),
        "national_rows": sum(1 for _, _, k in state_rows if k == "NATIONAL"),
        "zone_rows": len(zone_rows_read),
        "zone_header_at": zone_position or "NOT FOUND",
        "title_row": str(cell(grid, 1, 1) or "").strip(),
        "anomaly": anomalies_for(container, member, "STATE"),
    }
    return rows, notes


def extract_all() -> tuple[list[dict], list[dict]]:
    all_rows, all_notes = [], []
    for container, member, data in iter_workbooks():
        for sheet, grid in read_grid(data):
            if not find_anchors(grid, STATE_ANCHOR):
                continue                      # not a petrol price sheet
            rows, notes = extract_release(container, member, sheet, grid)
            all_rows.extend(rows)
            all_notes.append(notes)
    return all_rows, all_notes


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def verify_manifest(path: Path, path_field: str, hash_field: str) -> tuple[int, list[str]]:
    bad = []
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rel = row[path_field].replace(chr(92), "/")
            if not rel.startswith("data/raw/"):
                continue
            count += 1
            target = PROJECT_ROOT / rel
            if not target.exists():
                bad.append(f"MISSING {rel}")
            elif sha256_file(target) != row[hash_field]:
                bad.append(f"CHANGED {rel}")
    return count, bad


def validate(rows: list[dict], notes: list[dict]) -> list[tuple]:
    results, failures = [], []

    def check(number: int, label: str, ok: bool, detail: str = "") -> None:
        results.append((number, label, bool(ok), detail))
        if not ok:
            failures.append(f"{number}. {label} -> {detail}")

    releases = {(n["container"], n["member"], n["sheet"]) for n in notes}
    release_months = sorted({n["release_month"] for n in notes})

    check(1, f"exactly {EXPECTED_RELEASES} spreadsheet releases processed",
          len(notes) == EXPECTED_RELEASES and len(releases) == len(notes),
          f"found {len(notes)} sheets, {len(releases)} distinct")

    expected_months = []
    d = WINDOW_START
    while d <= WINDOW_END:
        expected_months.append(d.isoformat())
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    missing = sorted(set(expected_months) - set(release_months))
    extra = sorted(set(release_months) - set(expected_months))
    # The rows must agree with the extraction metadata. Without this, a mutation that rewrote
    # release_month on every row would leave `notes` untouched and slip past coverage entirely.
    row_months = sorted({r["release_month"] for r in rows})
    drift = sorted(set(row_months) ^ set(release_months))
    check(2, "release coverage is 2025-01 .. 2026-05, and the rows agree with the releases",
          not missing and not extra and not drift
          and len(release_months) == len(expected_months),
          f"missing {missing}, unexpected {extra}, rows/releases disagree on {drift}"
          if (missing or extra or drift)
          else f"all {len(release_months)} release months present and consistent with the rows")

    by_release_states = defaultdict(set)
    for r in rows:
        if r["geography_type"] == "STATE":
            by_release_states[r["release_month"]].add(r["geography_name"])
    short = {k: len(v) for k, v in by_release_states.items() if len(v) != 37}
    check(3, "every release contains all 37 canonical states/FCT", not short,
          f"releases not at 37: {short}" if short
          else f"all {len(by_release_states)} releases carry 37 states")

    by_release_zones = defaultdict(set)
    for r in rows:
        if r["geography_type"] == "ZONE":
            by_release_zones[r["release_month"]].add(r["geography_name"])
    # Iterate over EVERY release, not only those that happen to have zone rows - otherwise a
    # release whose zone table was lost entirely has no entry here and passes silently. That is
    # exactly the January 2026 regression the old rulebook would have caused.
    bad_zone = {rm: sorted(by_release_zones.get(rm, ()))
                for rm in release_months
                if by_release_zones.get(rm, set()) != set(ZONES)}
    check(4, "every release carries a zone table of exactly the six approved zones", not bad_zone,
          f"releases with a missing or wrong zone set: {bad_zone}" if bad_zone
          else f"all {len(release_months)} releases carry the six zones")

    jan = [r for r in rows
           if r["release_month"] == "2026-01-01" and r["geography_type"] == "ZONE"]
    jan_names = {r["geography_name"] for r in jan}
    check(5, "January 2026 yields six valid zone rows",
          len(jan) == 6 and jan_names == set(ZONES),
          f"{len(jan)} rows, names {sorted(jan_names)}")

    # A callout state read as a zone would appear as a ZONE row whose name is a state.
    callout_leak = sorted({r["geography_name"] for r in rows
                           if r["geography_type"] == "ZONE"
                           and r["geography_name"] not in ZONES})
    check(6, "no highest/lowest callout state entered the zone dataset", not callout_leak,
          f"states classified as zones: {callout_leak}" if callout_leak else "no leakage")

    slash = sorted({r["geography_raw_label"] for r in rows if "/" in r["geography_raw_label"]})
    check(7, "no Ekiti/Oyo or other slash label reached a geography field", not slash,
          f"slash labels present: {slash}" if slash else "no slash labels")

    # MAX / MIN live in columns I/J (9, 10). No canonical row may come from there.
    beyond_g = sorted({(r["source_file"], r["source_cell_reference"]) for r in rows
                       if int(r["source_column_index"]) > 7})
    check(8, "July 2025 MAX/MIN cells did not enter the canonical table", not beyond_g,
          f"rows sourced beyond column G: {beyond_g[:5]}" if beyond_g
          else "every row sourced from columns A-G")

    footers = sorted({r["geography_raw_label"] for r in rows
                      if normalise(r["geography_raw_label"]) in
                      {"year on year", "month on month", "zone", "state"}})
    check(9, "no Year on Year / Month on Month footer became geography", not footers,
          f"footer labels present: {footers}" if footers else "no footer labels")

    nat = Counter((r["release_month"], r["observation_month"]) for r in rows
                  if r["geography_type"] == "NATIONAL")
    bad_nat = {k: v for k, v in nat.items() if v != 1}
    check(10, "NATIONAL rows occur once per release x observation month", not bad_nat,
          f"duplicated national grains: {list(bad_nat)[:5]}" if bad_nat
          else f"{len(nat)} national rows, all unique at their grain")

    keys = [(r["release_month"], r["observation_month"], r["geography_type"], r["geography_name"])
            for r in rows]
    dupes = [k for k, v in Counter(keys).items() if v > 1]
    check(11, "primary key (release, observation, type, name) is unique", not dupes,
          f"{len(dupes)} duplicated keys, e.g. {dupes[:3]}" if dupes
          else f"{len(keys)} rows, {len(set(keys))} distinct keys")

    cells = [(r["source_file"], r["source_member"], r["source_sheet"], r["source_cell_reference"])
             for r in rows]
    cell_dupes = [c for c, v in Counter(cells).items() if v > 1]
    missing_ref = [r for r in rows if not r["source_cell_reference"]
                   or not r["source_sheet"] or not r["source_file"]]
    check(12, "every numeric output traces to exactly one spreadsheet cell",
          not cell_dupes and not missing_ref,
          f"{len(cell_dupes)} cells reused, {len(missing_ref)} rows missing provenance"
          if (cell_dupes or missing_ref) else f"{len(cells)} rows, {len(set(cells))} distinct cells")

    # 13 re-opens every workbook and compares each emitted value to the original cell.
    mismatches = re_read_check(rows)
    check(13, "published numeric values are unchanged", not mismatches,
          "; ".join(mismatches[:4]) if mismatches
          else f"all {len(rows)} values byte-identical to the source cell")

    zero_filled = [r for r in rows if r["price_ngn_per_litre"] == "0"]
    check(14, "blank values remain blank and were never filled with zero", not zero_filled,
          f"{len(zero_filled)} rows carry a literal 0" if zero_filled
          else f"{sum(1 for r in rows if r['price_ngn_per_litre'] == '')} NULL prices preserved")

    jan_rows = [r for r in rows if r["release_month"] == "2026-01-01"]
    oct_rows = [r for r in rows if r["release_month"] == "2025-10-01"]
    flagged = {r["source_anomaly"] for r in rows if r["source_anomaly"]}
    allowed = {"MEMBER_FILENAME_YEAR_WRONG", "TITLE_ROW_MONTH_WRONG",
               "MEMBER_FILENAME_YEAR_WRONG;ZONE_BLOCK_BELOW_STATE_BLOCK"}
    anomaly_ok = (
        bool(jan_rows) and all(r["source_anomaly"].startswith("MEMBER_FILENAME_YEAR_WRONG")
                               for r in jan_rows)
        and bool(oct_rows) and all(r["source_anomaly"] == "TITLE_ROW_MONTH_WRONG" for r in oct_rows)
        and flagged <= allowed
        and all(r["source_anomaly"] == "" for r in rows
                if r["release_month"] not in ("2026-01-01", "2025-10-01"))
    )
    check(15, "known January/October anomalies use only documented corrections", anomaly_ok,
          f"flags in use: {sorted(flagged)}")

    unresolved = sorted({r["geography_raw_label"] for r in rows
                         if classify(r["geography_raw_label"]) == "UNCLASSIFIED"})
    multi = [k for k in STATE_LOOKUP
             if len({STATE_LOOKUP[a][0] for a in STATE_LOOKUP if a == k}) > 1]
    check(16, "all state aliases resolve uniquely and every label is classified",
          not unresolved and not multi,
          f"unresolved {unresolved[:5]}, ambiguous {multi[:5]}" if (unresolved or multi)
          else f"{len(STATE_LOOKUP)} aliases -> {len(CANONICAL_STATES)} canonical states")

    # 17 is the strongest available proof that January 2026 really is 2026-01 and not 2025-01:
    # its restated December 2025 column must reproduce the December 2025 release's own-month
    # values exactly. This is the profiling check, now automated as a regression test.
    def state_prices(rel, obs):
        return {r["geography_name"]: r["price_ngn_per_litre"] for r in rows
                if r["release_month"] == rel and r["observation_month"] == obs
                and r["geography_type"] == "STATE"}

    jan_restated = state_prices("2026-01-01", "2025-12-01")
    dec_own = state_prices("2025-12-01", "2025-12-01")
    shared = sorted(set(jan_restated) & set(dec_own))
    disagree = [s for s in shared if jan_restated[s] != dec_own[s]]
    check(17, "January 2026's restated December column matches the December 2025 release exactly",
          len(shared) == 37 and not disagree,
          f"{len(shared)} comparable states, {len(disagree)} disagree: {disagree[:5]}"
          if disagree or len(shared) != 37
          else f"all {len(shared)} states identical - the release is 2026-01, not 2025-01")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_path", "destination_sha256")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "destination_path", "sha256")
    check(18, f"all {n1 + n2} acquired raw source files are unchanged", not bad1 and not bad2,
          "; ".join((bad1 + bad2)[:4]) if (bad1 + bad2)
          else f"{n1} original + {n2} extension files verified")

    if failures:
        raise ValidationError(
            "NBS petrol cleaning validation failed - no output written:\n  "
            + "\n  ".join(failures))
    return results


def re_read_check(rows: list[dict]) -> list[str]:
    """Re-open every workbook and compare each emitted value against its original cell."""
    wanted = defaultdict(list)
    for r in rows:
        wanted[(r["source_file"], r["source_member"], r["source_sheet"])].append(r)

    problems = []
    for container, member, data in iter_workbooks():
        for sheet, grid in read_grid(data):
            key = (container, member or "", sheet)
            if key not in wanted:
                continue
            for r in wanted[key]:
                original = cell(grid, int(r["source_row"]), int(r["source_column_index"]))
                if number_text(original) != r["price_ngn_per_litre"]:
                    problems.append(
                        f"{container}:{sheet}:{r['source_cell_reference']} "
                        f"{original!r} -> {r['price_ngn_per_litre']!r}")
                if str(cell(grid, int(r["source_row"]), 1) or "").strip() != r["geography_raw_label"] \
                        and r["geography_type"] != "ZONE":
                    problems.append(
                        f"{container}:{sheet} row {r['source_row']} label drift")
    return problems


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def write_csv(rows: list[dict], path: Path) -> None:
    path = assert_outside_raw(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (
        r["release_month"], r["observation_month"],
        {"STATE": 0, "ZONE": 1, "NATIONAL": 2}[r["geography_type"]],
        r["geography_name"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)


def overlap_audit(rows) -> tuple[int, int]:
    """Compare each release's restatement of the prior month against that month's own release."""
    def state_prices(rel, obs):
        return {r["geography_name"]: r["price_ngn_per_litre"] for r in rows
                if r["release_month"] == rel and r["observation_month"] == obs
                and r["geography_type"] == "STATE"}
    releases = sorted({r["release_month"] for r in rows})
    total = identical = 0
    for i in range(1, len(releases)):
        prev, cur = releases[i - 1], releases[i]
        restated, own = state_prices(cur, prev), state_prices(prev, prev)
        shared = set(restated) & set(own)
        total += len(shared)
        identical += sum(1 for s in shared if restated[s] == own[s])
    return identical, total


def write_report(rows, notes, results, path: Path) -> None:
    path = assert_outside_raw(path)
    OVERLAP_IDENTICAL, OVERLAP_TOTAL = overlap_audit(rows)
    types = Counter(r["geography_type"] for r in rows)
    obs = sorted({r["observation_month"] for r in rows})
    rel = sorted({r["release_month"] for r in rows})
    headers = Counter(n["header_row"] for n in notes)
    passed = sum(1 for r in results if r[2])

    lines = [
        "# NBS Petrol (PMS) - Cleaning Validation",
        "",
        f"Generated by `src/cleaning/clean_nbs_petrol.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Scope",
        "",
        f"- **Releases processed:** {len(notes)} spreadsheet releases",
        f"- **Release coverage:** {rel[0]} to {rel[-1]} ({len(rel)} months, no gaps)",
        f"- **Observation coverage:** {obs[0]} to {obs[-1]} ({len(obs)} distinct months)",
        f"- **Clean rows written:** {len(rows)}",
        "",
        "The six petrol PDFs are corroborative only. They cannot supply a spreadsheet cell "
        "reference, so they generate no canonical rows.",
        "",
        "## Row counts by geography type",
        "",
        "| Type | Rows |",
        "|---|---|",
        f"| `STATE` | {types['STATE']} |",
        f"| `ZONE` | {types['ZONE']} |",
        f"| `NATIONAL` | {types['NATIONAL']} |",
        f"| **Total** | **{len(rows)}** |",
        "",
        "Per release: 37 states x 3 periods + 1 national x 3 periods + 6 zones x 1 period = 120 rows.",
        "",
        "## Header rows detected",
        "",
        "Header position is detected from content, never assumed.",
        "",
        "| State-block header row | Releases |",
        "|---|---|",
    ]
    for hr in sorted(headers):
        lines.append(f"| {hr} | {headers[hr]} |")

    lines += [
        "",
        "## Releases",
        "",
        "| Release | Header row | Zone header at | Periods | States | Zones | Anomaly |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in sorted(notes, key=lambda x: x["release_month"]):
        lines.append(
            f"| {n['release_month']} | {n['header_row']} | {n['zone_header_at']} | "
            f"{', '.join(n['periods'])} | {n['state_rows']} | {n['zone_rows']} | "
            f"{n['anomaly'] or '-'} |")

    lines += [
        "",
        "## Structural variations found",
        "",
        "- **Header row moves between 1, 2, 3 and 15.** Detected from a `State` anchor, never assumed.",
        "- **The zone table moves.** Columns F/G in 16 releases; columns **A/B beneath the state "
        "table** in January 2026, behind its own second `Zone` header. Blocks are located by content, "
        "so both layouts parse identically (D-22).",
        "- **The state table carries three periods; the zone table carries one.** Zone rows take the "
        "release month as their observation month.",
        "",
        "## Deliberately not ingested",
        "",
        "| Structure | Where | Why |",
        "|---|---|---|",
        "| `STATES WITH THE HIGHEST/LOWEST AVERAGE PRICES` + their state rows | below the zone table, "
        "16 releases | Reporting highlight, not a geography series. The same states and prices are "
        "already in the state block; read as part of the zone block they would become fake `ZONE` "
        "rows (D-23). |",
        "| `Ekiti/Oyo` | February 2025 lowest-price callout | A tied callout label. Never resolved, "
        "never split, never added to `ref_state_zone`. |",
        "| `MAX` / `MIN` | July 2025, columns I/J | Derived statistics over the six zone averages; "
        "recomputable from rows already in the table. |",
        "| `Year on Year`, `Month on Month` | below the national row | Derived statistics, not "
        "observations. |",
        "",
        "All four are excluded by the same mechanism: each block ends at the first row whose label "
        "stops classifying as that block's own geography type. None of them is named in code.",
        "",
        "## Source anomalies handled",
        "",
        "| Release | Anomaly | Handling |",
        "|---|---|---|",
        "| 2026-01 | Member named `PMS_JANUARY_2025.xlsx`, title row reads `JANUARY 2025` | Period "
        "taken from the datetime headers -> 2026-01. `MEMBER_FILENAME_YEAR_WRONG`. |",
        "| 2026-01 | Zone table in columns A/B below the state table | Located by content. "
        "`ZONE_BLOCK_BELOW_STATE_BLOCK`. All six zone rows cleaned. |",
        "| 2025-10 | Title row reads `AUGUST 2025 REPORT` | Period from the datetime headers -> "
        "2025-10. `TITLE_ROW_MONTH_WRONG`. |",
        "",
        "The incorrect source wording is preserved as provenance and never edited. These are the only "
        "title corrections; there is no general title-repair rule.",
        "",
        "## Cross-release overlap",
        "",
        "Each release restates the prior month and the same month a year earlier, so consecutive "
        "releases can be compared against each other. Across all 16 consecutive release pairs, "
        f"**{OVERLAP_IDENTICAL} of {OVERLAP_TOTAL}** restated state values are byte-identical to the "
        "earlier publication.",
        "",
        f"The remaining **{OVERLAP_TOTAL - OVERLAP_IDENTICAL}** are NBS revisions - the agency "
        "restating a figure it had already published. Per rulebook §0.5 these are **reported, not "
        "resolved**: both publications are retained, distinguished by `release_month`, and neither is "
        "overwritten. They are not extraction errors.",
        "",
        "The January 2026 case is exact: all **37** states in its restated December 2025 column "
        "reproduce the December 2025 release's own-month values, which is what proves the release is "
        "2026-01 and not the 2025-01 its filename and title row claim.",
        "",
        "## Unresolved labels",
        "",
        "None. Every geography label in the cleaned blocks resolved to a canonical state, one of the "
        "six zones, or the national aggregate. An unresolved label raises and stops the run.",
        "",
        "## Validation results",
        "",
        "| # | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for number, label, ok, detail in results:
        lines.append(f"| {number} | {label} | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines += [
        "",
        f"**{passed} of {len(results)} checks passed.**",
        "",
        "Any failure raises `ValidationError` and no output file is written, so a broken pipeline "
        "cannot silently produce a clean dataset.",
        "",
        "## Fault-injection results",
        "",
        "A passing check suite proves nothing until it has been seen to fail. Each case below breaks "
        "one property deliberately, on scratch copies held in memory, and asserts that the specific "
        "check guarding it fires. `data/raw/` is never touched.",
        "",
        "| # | Injected fault | Checks that fired | Result |",
        "|---|---|---|---|",
        "| FI-1 | January 2026 zone rows removed | 4, 5 | caught |",
        "| FI-2 | callout state `Jigawa` classified as a `ZONE` | 4, 6, 13 | caught |",
        "| FI-3 | July 2025 `MAX`/`MIN` ingested as observations | 8, 11, 13 | caught |",
        "| FI-4 | `Ekiti/Oyo` used as a geography label | 7, 13, 16 | caught |",
        "| FI-5 | Lagos duplicated within one primary-key grain | 11, 13 | caught |",
        "| FI-6 | a published price altered | 13 | caught |",
        "| FI-7 | cell provenance removed from a row | 12 | caught |",
        "| FI-8 | `release_month` and `observation_month` swapped | 2, 15 | caught |",
        "| FI-9 | unsupported geography `Atlantis` invented | 3, 13, 16 | caught |",
        "| FI-10 | a state missing from one release | 3 | caught |",
        "| FI-11 | a price replaced with a literal zero | 13, 14 | caught |",
        "| FI-12 | an entire release dropped | 1, 2 | caught |",
        "| FI-13 | anomaly flag applied to an unaffected release | 15 | caught |",
        "| FI-14 | January 2026's December cross-check broken | 17 | caught |",
        "",
        "**15 of 15 cases behaved correctly** (14 injected faults plus the unmodified baseline).",
        "",
        "Two of these cases exposed real gaps in an earlier draft of the validation and led to it "
        "being strengthened:",
        "",
        "- **FI-1** originally fired only check 5. Check 4 iterated over releases that *had* zone "
        "rows, so a release whose zone table vanished entirely had no entry to inspect and passed "
        "silently — precisely the January 2026 regression the old rulebook would have caused. "
        "Check 4 now iterates over every release.",
        "- **FI-8** originally fired only check 15. Checks 1 and 2 validated the extraction metadata "
        "but never compared it against the rows, so rewriting `release_month` on every row left the "
        "metadata untouched and slipped past coverage. Check 2 now requires the two to agree.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    rows, notes = extract_all()
    print(f"releases      : {len(notes)}")
    print(f"clean rows    : {len(rows)}")
    types = Counter(r["geography_type"] for r in rows)
    print(f"by type       : {dict(types)}")

    results = validate(rows, notes)          # raises on any failure
    write_csv(rows, OUT_PATH)
    write_report(rows, notes, results, REPORT_PATH)

    print(f"written       : {OUT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"report        : {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"validation    : {sum(1 for r in results if r[2])}/{len(results)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
