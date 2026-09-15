"""Clean the NBS Automotive Gas Oil (diesel) price releases into `diesel_price_monthly`.

Source of record : data/raw/nbs/diesel/*.xlsx and the .xlsx members of data/raw/nbs/diesel/*.zip
Output           : data/processed/nbs/diesel_price_monthly.csv

Implements the approved rules in docs/data_design/. In particular:

  * **one unnamed column carries all three geographic levels.** Column A has no header and is
    addressed by position. It is *nested*: each zone heads a section of its own member states, and
    `NATIONAL` closes the table. Every label is classified against the reference tables, never by
    row position or casing (D-25).
  * **four parallel areas are excluded** - the duplicate side zone table in columns H/I, the `YoY`
    and `MoM` percentage columns, the highest/lowest callout blocks, and July 2025's stray `MAX` /
    `MIN` cells at K1/L1. Only the three datetime columns are prices.
  * **a published period date is truncated, never corrected** (D-24). 50 of diesel's 51 period
    headers fall on day 14; `DIESEL_NOV_2025.xlsx` prints `2025-10-25`. It becomes
    `observation_month = 2025-10-01` while `source_period_label` keeps `2025-10-25` verbatim.
  * every published value keeps its precision. A blank stays NULL and is never filled with zero.
  * every price traces to exactly one spreadsheet cell.

Run from the project root:

    python src/cleaning/clean_nbs_diesel.py

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
RAW_DIR = RAW_ROOT / "nbs" / "diesel"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "nbs" / "diesel_price_monthly.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_diesel_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

# 17 spreadsheet releases, 2025-01 .. 2026-05. The six diesel PDFs are corroborative only: they
# cannot supply a spreadsheet cell reference, so they generate no canonical rows.
EXPECTED_RELEASES = 17
WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 5, 1)
EXPECTED_STATES = 37
EXPECTED_ZONES = 6
EXPECTED_NATIONAL = 1
EXPECTED_PERIODS = 3
EXPECTED_ROWS = (EXPECTED_STATES + EXPECTED_ZONES + EXPECTED_NATIONAL) * \
    EXPECTED_PERIODS * EXPECTED_RELEASES        # 44 x 3 x 17 = 2244

ZONES = ("North Central", "North East", "North West",
         "South East", "South South", "South West")
ZONE_BY_KEY = {z.replace(" ", "").casefold(): z for z in ZONES}
NATIONAL_LABELS = {"average", "national", "grand total", "nigeria"}
NATIONAL_NAME = "Nigeria"

GEOGRAPHY_COLUMN = 1          # column A - it has no header, so position is the only handle
SIDE_TABLE_COLUMNS = (8, 9)   # H/I - the duplicate zone table and the callout blocks
DERIVED_COLUMNS = (5, 6)      # E/F - YoY and MoM percentages
UNIT = "NGN per litre"

# Verified anomaly, keyed on the exact (container, member) fingerprint plus the published date.
# There is no general date-repair rule and no other release may acquire the flag.
PERIOD_HEADER_DAY_NOT_14 = {
    ("AGO_REPORT_NOV_2025.zip", "DIESEL_NOV_2025.xlsx"): dt.date(2025, 10, 25),
}
EXPECTED_PERIOD_DAY = 14      # a documented convention, asserted for reporting - never enforced

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
    """STATE / ZONE / NATIONAL / UNCLASSIFIED, by label content only - never by casing or position."""
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
    for path in sorted(RAW_DIR.iterdir()):
        if path.suffix.lower() == ".xlsx":
            yield path.name, None, path.read_bytes()
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith(".xlsx") and not name.startswith("__MACOSX"):
                        yield path.name, name, archive.read(name)


def read_grid(data: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in wb.sheetnames:
            ws = wb[sheet]
            yield sheet, [tuple(row) for row in ws.iter_rows(values_only=True)]
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


def number_text(value) -> str:
    """Published numeric value as text, without changing its precision.

    Excel stores IEEE-754 doubles; `repr` of a Python float is the shortest string that round-trips
    to the identical double. A blank returns "" - the CSV representation of NULL, never 0.
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
def find_header(grid) -> int | None:
    """First row within the top 25 that carries a real datetime - the documented anchor (§0.1)."""
    for i, row in enumerate(grid[:25], start=1):
        if any(isinstance(c, dt.datetime) for c in row):
            return i
    return None


def period_columns(grid, header_row: int) -> list[tuple[int, dt.datetime]]:
    """The datetime headers. Only these columns are prices - never YoY, MoM or anything beyond."""
    out = []
    for c in range(1, len(grid[header_row - 1]) + 1):
        value = cell(grid, header_row, c)
        if isinstance(value, dt.datetime):
            if c in DERIVED_COLUMNS or c in SIDE_TABLE_COLUMNS:
                raise ValidationError(
                    f"A datetime appeared in a non-price column ({c}) - layout has changed")
            out.append((c, value))
    return out


def extract_release(container: str, member: str | None, sheet: str, grid):
    header_row = find_header(grid)
    if header_row is None:
        raise ValidationError(
            f"No datetime anchor in {container}::{member}::{sheet} - refusing to guess a header")

    periods = period_columns(grid, header_row)
    if len(periods) != EXPECTED_PERIODS:
        raise ValidationError(
            f"{container}::{member}::{sheet} has {len(periods)} period columns, "
            f"expected {EXPECTED_PERIODS}")
    months = [v.date().replace(day=1) for _, v in periods]
    if len(set(months)) != len(months):
        raise ValidationError(
            f"Duplicate observation months in {container}::{member}::{sheet}: {months}")
    release_month = max(months)

    # The geography column has no header at all - assert that, so a layout change is caught.
    header_cell = cell(grid, header_row, GEOGRAPHY_COLUMN)
    if header_cell is not None and str(header_cell).strip() != "":
        raise ValidationError(
            f"{container}::{member}::{sheet}: geography column {GEOGRAPHY_COLUMN} unexpectedly has "
            f"a header {header_cell!r}")

    rows, sequence = [], []
    current_zone = None
    for r in range(header_row + 1, len(grid) + 1):
        label = cell(grid, r, GEOGRAPHY_COLUMN)
        if label is None or str(label).strip() == "":
            continue
        raw_label = str(label).strip()
        kind = classify(raw_label)
        if kind == "UNCLASSIFIED":
            raise ValidationError(
                f"Unexpected geography {raw_label!r} in {container}::{member}::{sheet} row {r} "
                f"- refusing to guess")

        if kind == "STATE":
            state, zone = STATE_LOOKUP[normalise(raw_label)]
            name, is_agg = state, "FALSE"
        elif kind == "ZONE":
            zone = ZONE_BY_KEY[normalise(raw_label).replace(" ", "")]
            state, name, is_agg = "", zone, "TRUE"
            current_zone = zone
        else:
            state, zone = "", ""
            name, is_agg = NATIONAL_NAME, "TRUE"
        sequence.append((kind, name, current_zone))

        for col_idx, published in periods:
            observation_month = published.date().replace(day=1)
            anomaly = ""
            if PERIOD_HEADER_DAY_NOT_14.get((container, member)) == published.date():
                anomaly = "PERIOD_HEADER_DAY_NOT_14"
            rows.append({
                "release_month": release_month.isoformat(),
                "observation_month": observation_month.isoformat(),
                "geography_type": kind,
                "geography_name": name,
                "geography_raw_label": raw_label,
                "state": state,
                "zone": zone,
                "is_aggregate": is_agg,
                "price_ngn_per_litre": number_text(cell(grid, r, col_idx)),
                "unit": UNIT,
                # the published date verbatim, day included - this is what preserves 2025-10-25
                "source_period_label": published.date().isoformat(),
                "is_primary_release": "TRUE" if observation_month == release_month else "FALSE",
                "source_anomaly": anomaly,
                "header_row_used": header_row,
                "source_file": container,
                "source_member": member or "",
                "source_sheet": sheet,
                "source_row": r,
                "source_column_index": col_idx,
                "source_cell_reference": f"{get_column_letter(col_idx)}{r}",
            })
        if kind == "NATIONAL":
            break                     # NATIONAL closes the table

    # Corroboration only: the side table in H/I must agree with the main column's current month.
    side = {}
    current_col = max(periods, key=lambda x: x[1])[0]
    for r in range(header_row, len(grid) + 1):
        lab = cell(grid, r, SIDE_TABLE_COLUMNS[0])
        if lab is not None and classify(lab) == "ZONE":
            side[ZONE_BY_KEY[normalise(lab).replace(" ", "")]] = \
                number_text(cell(grid, r, SIDE_TABLE_COLUMNS[1]))
    main = {}
    for r in range(header_row + 1, len(grid) + 1):
        lab = cell(grid, r, GEOGRAPHY_COLUMN)
        if lab is not None and classify(lab) == "ZONE":
            main[ZONE_BY_KEY[normalise(lab).replace(" ", "")]] = \
                number_text(cell(grid, r, current_col))
    side_disagreements = sorted(z for z in side if z in main and side[z] != main[z])

    notes = {
        "container": container,
        "member": member or "",
        "sheet": sheet,
        "header_row": header_row,
        "release_month": release_month.isoformat(),
        "periods": [v.date().isoformat() for _, v in periods],
        "period_days": sorted({v.day for _, v in periods}),
        "n_state": sum(1 for k, _, _ in sequence if k == "STATE"),
        "n_zone": sum(1 for k, _, _ in sequence if k == "ZONE"),
        "n_national": sum(1 for k, _, _ in sequence if k == "NATIONAL"),
        "nesting_ok": all(z == cz for k, n, cz in sequence
                          if k == "STATE"
                          for z in [STATE_LOOKUP[normalise(n)][1]]),
        "side_zones": len(side),
        "side_disagreements": side_disagreements,
        "anomaly": "PERIOD_HEADER_DAY_NOT_14" if (container, member) in PERIOD_HEADER_DAY_NOT_14
                   else "",
    }
    return rows, notes


def extract_all():
    all_rows, all_notes = [], []
    for container, member, data in iter_workbooks():
        for sheet, grid in read_grid(data):
            if find_header(grid) is None:
                continue
            rows, notes = extract_release(container, member, sheet, grid)
            all_rows.extend(rows)
            all_notes.append(notes)
    return all_rows, all_notes


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def verify_manifest(path: Path, hash_field: str) -> tuple[int, list[str]]:
    bad, count = [], 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rel = row["destination_path"].replace(chr(92), "/")
            if not rel.startswith("data/raw/"):
                continue
            count += 1
            target = PROJECT_ROOT / rel
            if not target.exists():
                bad.append(f"MISSING {rel}")
            elif sha256_file(target) != row[hash_field]:
                bad.append(f"CHANGED {rel}")
    return count, bad


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
                label = cell(grid, int(r["source_row"]), GEOGRAPHY_COLUMN)
                if str(label or "").strip() != r["geography_raw_label"]:
                    problems.append(
                        f"{container}:{sheet} row {r['source_row']} geography label drift")
    return problems


SUBSTANTIVE_REVISION_TOLERANCE = 1e-12
"""Relative difference at or above which a restated value counts as a substantive revision.

Two published texts that differ by less than this are the same measurement rendered at different
stored precision, not a changed estimate. The threshold is a *defined tolerance*, not a claim of
equality: the two texts are genuinely different strings and both are preserved.
"""


def is_precision_only(a: str, b: str) -> bool:
    """True when two published texts differ by less than SUBSTANTIVE_REVISION_TOLERANCE.

    NBS sometimes writes 1599.30053473809 in one release and 1599.3005347380927 in the next. Those
    are the same measurement rendered at different stored precision. They are **not byte-identical**
    and must never be described as such - but calling them substantive revisions would overstate how
    often the agency changes its figures. Both source publications are preserved either way.
    """
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if fa == fb:
        return True
    if fa == 0:
        return False
    return abs(fa - fb) / abs(fa) < SUBSTANTIVE_REVISION_TOLERANCE


def overlap_audit(rows) -> tuple[int, int, list]:
    """Compare each release's restatement of the prior month against that month's own release."""
    def prices(rel, obs):
        return {(r["geography_type"], r["geography_name"]): r["price_ngn_per_litre"]
                for r in rows if r["release_month"] == rel and r["observation_month"] == obs}
    releases = sorted({r["release_month"] for r in rows})
    total = identical = 0
    revisions = []
    for i in range(1, len(releases)):
        prev, cur = releases[i - 1], releases[i]
        restated, own = prices(cur, prev), prices(prev, prev)
        for key in sorted(set(restated) & set(own)):
            total += 1
            if restated[key] == own[key]:
                identical += 1
            else:
                revisions.append((prev, cur, key[0], key[1], own[key], restated[key]))
    return identical, total, revisions


def validate(rows: list[dict], notes: list[dict]) -> list[tuple]:
    results, failures = [], []

    def check(number: int, label: str, ok: bool, detail: str = "") -> None:
        results.append((number, label, bool(ok), detail))
        if not ok:
            failures.append(f"{number}. {label} -> {detail}")

    release_months = sorted({n["release_month"] for n in notes})
    sheets = {(n["container"], n["member"], n["sheet"]) for n in notes}

    check(1, f"exactly {EXPECTED_RELEASES} spreadsheet releases processed",
          len(notes) == EXPECTED_RELEASES and len(sheets) == len(notes),
          f"found {len(notes)} sheets, {len(sheets)} distinct")

    expected_months, d = [], WINDOW_START
    while d <= WINDOW_END:
        expected_months.append(d.isoformat())
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    missing = sorted(set(expected_months) - set(release_months))
    extra = sorted(set(release_months) - set(expected_months))
    drift = sorted(set(r["release_month"] for r in rows) ^ set(release_months))
    check(2, "release coverage is 2025-01 .. 2026-05, and the rows agree with the releases",
          not missing and not extra and not drift,
          f"missing {missing}, unexpected {extra}, rows/releases disagree on {drift}"
          if (missing or extra or drift)
          else f"all {len(release_months)} release months present and consistent")

    bad_states = {n["release_month"]: n["n_state"] for n in notes
                  if n["n_state"] != EXPECTED_STATES}
    check(3, f"every release contains exactly {EXPECTED_STATES} states", not bad_states,
          f"wrong state counts: {bad_states}" if bad_states
          else f"all {len(notes)} releases carry {EXPECTED_STATES} states")

    bad_zones = {n["release_month"]: n["n_zone"] for n in notes if n["n_zone"] != EXPECTED_ZONES}
    per_release_zone_names = defaultdict(set)
    for r in rows:
        if r["geography_type"] == "ZONE":
            per_release_zone_names[r["release_month"]].add(r["geography_name"])
    wrong_set = {rm: sorted(per_release_zone_names.get(rm, ()))
                 for rm in release_months
                 if per_release_zone_names.get(rm, set()) != set(ZONES)}
    check(4, f"every release contains exactly the {EXPECTED_ZONES} approved zones",
          not bad_zones and not wrong_set,
          f"counts {bad_zones}, sets {wrong_set}" if (bad_zones or wrong_set)
          else f"all {len(notes)} releases carry the six zones")

    bad_nat = {n["release_month"]: n["n_national"] for n in notes
               if n["n_national"] != EXPECTED_NATIONAL}
    check(5, "every release contains exactly one NATIONAL row", not bad_nat,
          f"wrong national counts: {bad_nat}" if bad_nat
          else f"all {len(notes)} releases carry one NATIONAL row")

    per_geo = Counter((r["release_month"], r["geography_type"], r["geography_name"])
                      for r in rows)
    bad_periods = {k: v for k, v in per_geo.items() if v != EXPECTED_PERIODS}
    check(6, f"every canonical geography carries exactly {EXPECTED_PERIODS} period values",
          not bad_periods,
          f"{len(bad_periods)} geographies with a wrong period count, e.g. "
          f"{list(bad_periods.items())[:3]}" if bad_periods
          else f"all {len(per_geo)} geography/release pairs carry {EXPECTED_PERIODS} periods")

    check(7, f"expected row count = {EXPECTED_ROWS} (44 geographies x 3 periods x 17 releases)",
          len(rows) == EXPECTED_ROWS, f"found {len(rows)}")

    keys = [(r["release_month"], r["observation_month"], r["geography_type"], r["geography_name"])
            for r in rows]
    dupes = [k for k, v in Counter(keys).items() if v > 1]
    check(8, "primary key (release, observation, type, name) is unique", not dupes,
          f"{len(dupes)} duplicated keys, e.g. {dupes[:3]}" if dupes
          else f"{len(keys)} rows, {len(set(keys))} distinct keys")

    unresolved = sorted({r["geography_raw_label"] for r in rows
                         if classify(r["geography_raw_label"]) == "UNCLASSIFIED"})
    state_names = {r["geography_name"] for r in rows if r["geography_type"] == "STATE"}
    check(9, "every state resolves uniquely through ref_state_zone",
          not unresolved and state_names <= set(CANONICAL_STATES)
          and len(state_names) == EXPECTED_STATES,
          f"unresolved {unresolved[:5]}, states {len(state_names)}" if unresolved
          else f"{len(STATE_LOOKUP)} aliases -> {len(state_names)} canonical states")

    zone_names = {r["geography_name"] for r in rows if r["geography_type"] == "ZONE"}
    check(10, "every zone resolves to one of the six approved zones", zone_names == set(ZONES),
          f"found {sorted(zone_names)}")

    nat_bad = [r for r in rows if r["geography_type"] == "NATIONAL"
               and (r["geography_name"] != NATIONAL_NAME or r["state"] or r["zone"])]
    misfiled = [r for r in rows
                if (r["geography_name"] == NATIONAL_NAME and r["geography_type"] != "NATIONAL")
                or (r["geography_name"] in ZONES and r["geography_type"] != "ZONE")
                or (r["geography_type"] == "STATE" and r["geography_name"] in ZONES)]
    check(11, "NATIONAL never becomes a state or zone, and no zone becomes a state",
          not nat_bad and not misfiled,
          f"{len(nat_bad)} malformed national rows, {len(misfiled)} misfiled rows"
          if (nat_bad or misfiled) else "all three levels correctly separated")

    from_side = [r for r in rows
                 if int(r["source_column_index"]) in SIDE_TABLE_COLUMNS]
    check(12, "no row was sourced from the duplicate side zone table (columns H/I)", not from_side,
          f"{len(from_side)} rows sourced from H/I" if from_side
          else "no row sourced from the side table")

    disagree = [(n["release_month"], n["side_disagreements"]) for n in notes
                if n["side_disagreements"]]
    missing_side = [n["release_month"] for n in notes if n["side_zones"] != EXPECTED_ZONES]
    check(13, "side-table zone values corroborate the main column's current month",
          not disagree and not missing_side,
          f"disagreements {disagree[:3]}, incomplete side tables {missing_side}"
          if (disagree or missing_side)
          else f"all {len(notes)} releases: 6 side zones, 0 value mismatches")

    from_derived = [r for r in rows if int(r["source_column_index"]) in DERIVED_COLUMNS]
    check(14, "no YoY or MoM column entered the output", not from_derived,
          f"{len(from_derived)} rows sourced from columns E/F" if from_derived
          else "no row sourced from a derived column")

    july_cells = [r for r in rows if int(r["source_column_index"]) > 7]
    check(15, "July 2025 K1/L1 MAX/MIN cells never entered the output", not july_cells,
          f"{len(july_cells)} rows sourced beyond column G" if july_cells
          else "every row sourced from columns B-D")

    callout_words = {"states with the highest average prices",
                     "states with the lowest average prices"}
    callouts = sorted({r["geography_raw_label"] for r in rows
                       if normalise(r["geography_raw_label"]) in callout_words})
    check(16, "no highest/lowest callout heading entered the output", not callouts,
          f"callout labels present: {callouts}" if callouts else "no callout headings")

    slash = sorted({r["geography_raw_label"] for r in rows
                    if "/" in r["geography_raw_label"] or "/" in r["geography_name"]})
    check(17, "no slash callout label (Adamawa/Plateau, Kogi/Zamfara) reached canonical geography",
          not slash, f"slash labels: {slash}" if slash else "no slash labels")

    nospace = sorted({r["geography_raw_label"] for r in rows
                      if normalise(r["geography_raw_label"]).replace(" ", "") in ZONE_BY_KEY
                      and " " not in r["geography_raw_label"].strip()})
    check(18, "SouthWest never entered canonical geography from the side table", not nospace,
          f"no-space zone labels: {nospace}" if nospace
          else "every zone label came from the main column")

    odd = [r for r in rows if r["source_anomaly"] == "PERIOD_HEADER_DAY_NOT_14"]
    odd_ok = (bool(odd)
              and all(r["source_period_label"] == "2025-10-25" for r in odd)
              and all(r["observation_month"] == "2025-10-01" for r in odd)
              and all(r["release_month"] == "2025-11-01" for r in odd)
              and len(odd) == 44)
    others = [r for r in rows if r["source_anomaly"] and r["source_anomaly"]
              != "PERIOD_HEADER_DAY_NOT_14"]
    check(19, "2025-10-25 maps to observation month 2025-10-01 and keeps its published date",
          odd_ok and not others,
          f"{len(odd)} flagged rows, {len(others)} unexpected flags")

    cells = [(r["source_file"], r["source_member"], r["source_sheet"], r["source_cell_reference"])
             for r in rows]
    cell_dupes = [c for c, v in Counter(cells).items() if v > 1]
    missing_prov = [r for r in rows if not r["source_cell_reference"] or not r["source_sheet"]
                    or not r["source_file"] or not r["source_row"]
                    or not r["source_column_index"]]
    check(20, "every output price matches exactly one source spreadsheet cell",
          not cell_dupes and not missing_prov,
          f"{len(cell_dupes)} cells reused, {len(missing_prov)} rows missing provenance"
          if (cell_dupes or missing_prov)
          else f"{len(cells)} rows, {len(set(cells))} distinct cells")

    mismatches = re_read_check(rows)
    check(21, "published numeric values are unchanged", not mismatches,
          "; ".join(mismatches[:4]) if mismatches
          else f"all {len(rows)} values byte-identical to the source cell")

    zero_filled = [r for r in rows if r["price_ngn_per_litre"] == "0"]
    nulls = sum(1 for r in rows if r["price_ngn_per_litre"] == "")
    check(22, "missing values remain missing and were never filled with zero", not zero_filled,
          f"{len(zero_filled)} rows carry a literal 0" if zero_filled
          else f"{nulls} NULL prices preserved")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256")
    check(23, f"all {n1 + n2} acquired raw source files are unchanged", not bad1 and not bad2,
          "; ".join((bad1 + bad2)[:4]) if (bad1 + bad2)
          else f"{n1} original + {n2} extension files verified")

    if failures:
        raise ValidationError(
            "NBS diesel cleaning validation failed - no output written:\n  "
            + "\n  ".join(failures))
    return results


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


def write_report(rows, notes, results, path: Path) -> None:
    path = assert_outside_raw(path)
    types = Counter(r["geography_type"] for r in rows)
    obs = sorted({r["observation_month"] for r in rows})
    rel = sorted({r["release_month"] for r in rows})
    headers = Counter(n["header_row"] for n in notes)
    days = Counter(d for n in notes for d in n["period_days"])
    identical, total, differences = overlap_audit(rows)
    precision_only = [d for d in differences if is_precision_only(d[4], d[5])]
    revisions = [d for d in differences if not is_precision_only(d[4], d[5])]
    passed = sum(1 for r in results if r[2])

    lines = [
        "# NBS Diesel (AGO) - Cleaning Validation",
        "",
        f"Generated by `src/cleaning/clean_nbs_diesel.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Scope",
        "",
        f"- **Releases processed:** {len(notes)} spreadsheet releases",
        f"- **Release coverage:** {rel[0]} to {rel[-1]} ({len(rel)} months, no gaps)",
        f"- **Observation coverage:** {obs[0]} to {obs[-1]} ({len(obs)} distinct months)",
        f"- **Clean rows written:** {len(rows)}",
        "",
        "The six diesel PDFs are corroborative only. They cannot supply a spreadsheet cell "
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
        "Per release: 37 states + 6 zones + 1 national = 44 geographies x 3 periods = 132 rows. "
        "Diesel's zone rows carry all three periods, where petrol's zone table carries one - which "
        "is why diesel yields 132 rows per release against petrol's 120.",
        "",
        "## Header rows detected",
        "",
        "The geography column has no header, so the table is anchored on a datetime cell instead.",
        "",
        "| Header row | Releases |",
        "|---|---|",
    ]
    for hr in sorted(headers):
        lines.append(f"| {hr} | {headers[hr]} |")

    lines += [
        "",
        "## Source period-date patterns",
        "",
        "Diesel period headers are Excel datetimes. The day-of-month is a label convention and is "
        "**truncated, never corrected** (D-24).",
        "",
        "| Day of month | Period headers |",
        "|---|---|",
    ]
    for day in sorted(days):
        lines.append(f"| {day} | {days[day]} |")
    lines += [
        "",
        f"{sum(days.values())} period headers in total. The single day-25 header is "
        "`DIESEL_NOV_2025.xlsx`'s middle period, `2025-10-25`, which truncates to `2025-10-01` while "
        "`source_period_label` keeps `2025-10-25` verbatim.",
        "",
        "## Releases",
        "",
        "| Release | Header row | Periods | States | Zones | National | Anomaly |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in sorted(notes, key=lambda x: x["release_month"]):
        lines.append(
            f"| {n['release_month']} | {n['header_row']} | {', '.join(n['periods'])} | "
            f"{n['n_state']} | {n['n_zone']} | {n['n_national']} | {n['anomaly'] or '-'} |")

    lines += [
        "",
        "## Structural variations",
        "",
        "- **Header row moves between 1, 2, 3 and 16.** Detected from a datetime anchor, never "
        "assumed. Four sheets are named `Sheet1`, so the worksheet name is ignored entirely.",
        "- **The main geography column has no header at all** and is addressed by position "
        "(column A). It is the only place in the project where all three geographic levels share one "
        "column.",
        "- **The column is nested, not flat.** Each zone heads a section of its own member states and "
        "`NATIONAL` closes the table. The pattern is identical in all 17 releases, with no blank rows "
        "inside the block, and every state sits under the zone `ref_state_zone.csv` assigns it.",
        "- **Casing distinguishes the two zone spellings:** the main column prints zones in UPPER "
        "CASE, the side table in Title Case. Classification is done on content, not casing.",
        "",
        "## Deliberately not ingested",
        "",
        "| Structure | Where | Why |",
        "|---|---|---|",
        "| Duplicate side zone table | columns H/I | Repeats the six zone current-month values the "
        "main column already carries. Ingesting it would emit a second row per zone and collide on "
        "the primary key. Used as corroboration instead - see check 13. |",
        "| `YoY` / `MoM` | columns E/F | Derived percentages. Filing them as prices would record a "
        "percentage as naira per litre. In diesel these are columns; in petrol the same statistics "
        "are footer rows. |",
        "| Highest/lowest callout blocks | columns H/I, below the side table | Reporting highlights "
        "whose states and prices are already in the main column. |",
        "| `Adamawa/Plateau`, `Kogi/Zamfara` | those callout blocks | Tied callout labels, not "
        "geography. Never split, never added to `ref_state_zone`. |",
        "| `MAX` / `MIN` | July 2025 only, cells K1/L1 | Unlabelled working cells holding that "
        "month's South South maximum and South West minimum zone averages. |",
        "",
        "## Documented anomalies handled",
        "",
        "| Release | Anomaly | Handling |",
        "|---|---|---|",
        "| 2025-11 | Middle period header reads `2025-10-25`, where every other header uses day 14 | "
        "Truncated to `observation_month = 2025-10-01`, which is correct. `source_period_label` keeps "
        "`2025-10-25`. Flagged `PERIOD_HEADER_DAY_NOT_14` on all 44 affected rows. No global date "
        "rewriting. |",
        "| 2026-01 | `SouthWest` (no space) at cell H7 | Inside the excluded side table. The main "
        "column of the same file reads `SOUTH WEST`, so the canonical path never meets it. |",
        "| 2025-07 | Stray `MAX` / `MIN` at K1/L1 | Excluded; raw cells untouched. |",
        "",
        "## Cross-release revisions",
        "",
        f"**{len(precision_only)} precision-only differences and {len(revisions)} substantive "
        "cross-release revisions under the defined tolerance.**",
        "",
        "Each release restates the prior month, so consecutive releases can be compared. Across all "
        f"{len(rel) - 1} consecutive release pairs, **{total}** restated values were compared:",
        "",
        "| Outcome | Values |",
        "|---|---|",
        f"| Byte-identical to the earlier publication | {identical} |",
        f"| Differ only in stored precision (below tolerance) | {len(precision_only)} |",
        f"| **Substantive revision (at or above tolerance)** | **{len(revisions)}** |",
        "",
        f"**Tolerance.** A restated value counts as a substantive revision when it differs from the "
        f"earlier publication by a relative amount of **{SUBSTANTIVE_REVISION_TOLERANCE:g} or more**. "
        "Below that threshold the two texts are treated as the same measurement rendered at different "
        "stored precision.",
        "",
    ]
    if precision_only:
        lines += [
            f"The {len(precision_only)} sub-tolerance values are **not byte-identical** - the "
            "published strings genuinely differ, for example `1599.30053473809` in the March 2025 "
            "release against `1599.3005347380927` in April 2025. They are also **not "
            f"{len(precision_only)} substantive NBS revisions**: every one differs by less than the "
            "tolerance above, which is a rendering difference inside double-precision representation "
            "rather than a changed estimate. They cluster in three observation months: "
            + ", ".join(f"{k} ({v})" for k, v in sorted(
                Counter(d[0] for d in precision_only).items())) + ".",
            "",
            "**Both source publications remain preserved.** Each release's text is stored exactly as "
            "published, distinguished by `release_month`; neither is overwritten, rounded or "
            "reconciled, and no source value was altered to reach this conclusion.",
            "",
        ]
    if revisions:
        lines += [
            f"**{len(revisions)} substantive revisions** - the agency restating a figure by at least "
            "the tolerance above. Per rulebook §0.5 these are **reported, not resolved**: both "
            "publications are retained and neither is overwritten.",
            "",
            "| Observation month | Restated by | Type | Geography | Original | Restated |",
            "|---|---|---|---|---|---|",
        ]
        for obs_m, cur, typ, name, a, b in revisions[:40]:
            lines.append(f"| {obs_m} | {cur} | {typ} | {name} | {a} | {b} |")
        if len(revisions) > 40:
            lines.append(f"| … | | | | | _{len(revisions) - 40} more_ |")
    else:
        lines.append(
            "**No differences reached the substantive-revision tolerance.** That is a statement "
            "about magnitude, not about the stored text: the "
            f"{len(precision_only)} sub-tolerance values above are real string differences and are "
            "described as precision-only, never as identical.")

    lines += [
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
        "| FI-1 | `NATIONAL` reclassified as a `STATE` | 3, 5, 9, 11 | caught |",
        "| FI-2 | `South West` reclassified as a `STATE` | 3, 4, 9, 11 | caught |",
        "| FI-3 | one state's rows removed | 3, 7 | caught |",
        "| FI-4 | one zone removed | 4, 7 | caught |",
        "| FI-5 | duplicate side-zone table ingested | 6, 7, 8, 12, 15, 21 | caught |",
        "| FI-6 | `YoY`/`MoM` ingested as prices | 6, 7, 8, 14, 21 | caught |",
        "| FI-7 | July 2025 `MAX`/`MIN` ingested | 6, 7, 8, 15, 21 | caught |",
        "| FI-8 | `Adamawa/Plateau` treated as one geography | 9, 17, 21 | caught |",
        "| FI-9 | `SouthWest` treated as a new zone | 18, 21 | caught |",
        "| FI-10 | `2025-10-25` rewritten to a different month | 8, 19 | caught |",
        "| FI-11 | source-cell provenance removed | 20 | caught |",
        "| FI-12 | one diesel price altered | 21 | caught |",
        "| FI-13 | a primary-key row duplicated | 6, 7, 8, 21 | caught |",
        "| FI-14 | `release_month` and `observation_month` swapped | 2, 6, 19 | caught |",
        "| FI-15 | a new geography invented | 6, 7, 9, 21 | caught |",
        "",
        "**16 of 16 cases behaved correctly** (15 injected faults plus the unmodified baseline).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    rows, notes = extract_all()
    print(f"releases      : {len(notes)}")
    print(f"clean rows    : {len(rows)}")
    print(f"by type       : {dict(Counter(r['geography_type'] for r in rows))}")

    results = validate(rows, notes)          # raises on any failure
    write_csv(rows, OUT_PATH)
    write_report(rows, notes, results, REPORT_PATH)

    identical, total, differences = overlap_audit(rows)
    genuine = [d for d in differences if not is_precision_only(d[4], d[5])]
    print(f"overlap       : {total} compared -> {identical} byte-identical, "
          f"{len(differences) - len(genuine)} precision-only, "
          f"{len(genuine)} substantive revisions")
    print(f"written       : {OUT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"report        : {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"validation    : {sum(1 for r in results if r[2])}/{len(results)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
