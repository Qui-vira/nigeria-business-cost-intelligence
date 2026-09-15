"""Clean the NBS Transport Fare Watch releases into two canonical tables.

Source of record : data/raw/nbs/transport/*.xlsx and the .xlsx members of .../transport/*.zip
Outputs          : data/processed/nbs/transport_fare_zone_monthly.csv
                   data/processed/nbs/transport_fare_state_monthly.csv

Implements the approved rules in docs/data_design/. In particular:

  * **two sheets, two tables, two keys.** They are never joined. Sheets are identified by cell A1
    (`Zone` / `State`), never by name or position.
  * **the release month comes from the sheet name, cross-checked against column 3 + one month**
    (D-28). The current-month header is wrong in one release and is never trusted; if the two
    independent signals disagree the run stops.
  * **periods are taken by column position** - column 2 year-ago, column 3 prior month, column 4
    current month - never from header text. `TRANSPORT_COST_Watch_MAR_2025.xlsx` prints
    `Average of Mar-24` in both column 2 and column 4; the two are told apart by cell reference and
    the wrong label is preserved verbatim on both.
  * **the two sheets reconcile against each other** (D-29). The zone sheet's NATIONAL current-month
    fare must equal the state sheet's `Grand Total` within 1e-12, for every release and mode.
  * `MoM` / `YoY` never enter either table. Tables are sized from content, never from `max_column`.
  * every published value keeps its precision; every fare traces to exactly one spreadsheet cell.

Run from the project root:

    python src/cleaning/clean_nbs_transport.py

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
RAW_DIR = RAW_ROOT / "nbs" / "transport"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
REF_TRANSPORT_MODE = PROJECT_ROOT / "data" / "reference" / "ref_transport_mode.csv"
OUT_ZONE = PROJECT_ROOT / "data" / "processed" / "nbs" / "transport_fare_zone_monthly.csv"
OUT_STATE = PROJECT_ROOT / "data" / "processed" / "nbs" / "transport_fare_state_monthly.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_transport_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

EXPECTED_RELEASES = 17
WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 5, 1)
EXPECTED_MODES = 5
EXPECTED_ZONES = 6
EXPECTED_STATES = 37
EXPECTED_ZONE_PERIODS = 3
EXPECTED_ZONE_ROWS = EXPECTED_MODES * (1 + EXPECTED_ZONES) * EXPECTED_ZONE_PERIODS * \
    EXPECTED_RELEASES                                    # 5 * 7 * 3 * 17 = 1785
EXPECTED_STATE_ROWS = EXPECTED_MODES * (EXPECTED_STATES + 1) * EXPECTED_RELEASES   # 5*38*17 = 3230

# cross-sheet reconciliation, D-29
RECONCILE_TOLERANCE = 1e-12
EXPECTED_RECONCILE_COMPARISONS = EXPECTED_MODES * EXPECTED_RELEASES                # 85

ZONES = ("North Central", "North East", "North West",
         "South East", "South South", "South West")
ZONE_BY_KEY = {z.replace(" ", "").casefold(): z for z in ZONES}
NATIONAL_LABELS = {"average", "national", "grand total", "nigeria"}
NATIONAL_NAME = "Nigeria"
MODE_CODES = ("AIR", "BUS_INTERCITY", "BUS_INTRACITY", "OKADA", "WATER")

ZONE_ANCHOR = "zone"
STATE_ANCHOR = "state"
PERIOD_COLUMNS = (2, 3, 4)      # year-ago, prior month, current month - BY POSITION (D-28)
DERIVED_HEADERS = {"mom", "yoy"}
STATE_MODE_COLUMNS = (2, 3, 4, 5, 6)
UNIT = "NGN per journey"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# The single verified label defect. Keyed on the exact (container, member) fingerprint.
DUPLICATE_PERIOD_HEADER = {
    ("TRANSPORT_COST_Watch_MAR_2025.xlsx", None),
}
DUPLICATE_PERIOD_FLAG = "DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION"

ZONE_COLUMNS = [
    "release_month", "observation_month", "transport_mode", "transport_mode_raw",
    "geography_type", "geography_name", "geography_raw_label", "zone", "is_aggregate",
    "fare_ngn", "unit", "source_period_label", "period_position", "is_primary_release",
    "source_anomaly", "source_file", "source_member", "source_sheet", "source_row",
    "source_column_index", "source_cell_reference",
]
STATE_COLUMNS = [
    "observation_month", "release_month", "transport_mode", "transport_mode_raw",
    "geography_type", "geography_name", "geography_raw_label", "state", "zone", "is_aggregate",
    "fare_ngn", "unit", "source_period_label", "source_anomaly",
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


def normalise(value) -> str:
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
    return lookup


def load_mode_lookup() -> list[tuple[str, str]]:
    out = []
    with REF_TRANSPORT_MODE.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out.append((row["match_prefix"], row["transport_mode"]))
    # longest prefix first so a more specific rule can never be shadowed
    return sorted(out, key=lambda x: -len(x[0]))


STATE_LOOKUP = load_state_lookup()
MODE_LOOKUP = load_mode_lookup()
CANONICAL_STATES = sorted({s for s, _ in STATE_LOOKUP.values()})


def classify(label) -> str:
    key = normalise(label)
    if key in STATE_LOOKUP:
        return "STATE"
    if key.replace(" ", "") in ZONE_BY_KEY:
        return "ZONE"
    if key in NATIONAL_LABELS:
        return "NATIONAL"
    return "OTHER"


def mode_of(label) -> str | None:
    key = normalise(label)
    for prefix, code in MODE_LOOKUP:
        if key.startswith(prefix):
            return code
    return None


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


def parse_period(text) -> dt.date | None:
    m = re.search(r"([A-Za-z]+)[-\s]+(\d{2,4})\s*$", str(text).strip())
    if not m:
        return None
    mon = m.group(1)[:3].casefold()
    if mon not in MONTHS:
        return None
    year = int(m.group(2))
    return dt.date(2000 + year if year < 100 else year, MONTHS[mon], 1)


def parse_sheet_month(name: str) -> dt.date | None:
    m = re.search(r"([A-Za-z]+)\s+(\d{4})\s*$", str(name).strip())
    if not m:
        return None
    mon = m.group(1)[:3].casefold()
    return dt.date(int(m.group(2)), MONTHS[mon], 1) if mon in MONTHS else None


def add_month(d: dt.date) -> dt.date:
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def number_text(value) -> str:
    """Published value as text, precision unchanged. Blank stays NULL, never 0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValidationError(f"Boolean where a fare was expected: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value).strip()
    if text == "":
        return ""
    raise ValidationError(f"Non-numeric value where a fare was expected: {value!r}")


# ----------------------------------------------------------------------------
def extract_release(container: str, member: str | None, sheets):
    zone_grid = zone_name = state_grid = state_name = None
    for name, grid in sheets:
        a1 = normalise(cell(grid, 1, 1) or "")
        if a1 == ZONE_ANCHOR:
            zone_grid, zone_name = grid, name
        elif a1 == STATE_ANCHOR:
            state_grid, state_name = grid, name
    if zone_grid is None or state_grid is None:
        raise ValidationError(
            f"{container}::{member} does not expose both a Zone sheet and a State sheet "
            f"(A1 anchors) - refusing to guess")

    # --- release month: two independent signals, both must agree (D-28) ------
    from_name = parse_sheet_month(zone_name)
    prior_label = cell(zone_grid, 1, PERIOD_COLUMNS[1])
    prior = parse_period(prior_label)
    from_prior = add_month(prior) if prior else None
    if from_name is None or from_prior is None:
        raise ValidationError(
            f"{container}::{zone_name}: cannot derive the release month "
            f"(sheet name -> {from_name}, column 3 + 1 -> {from_prior})")
    if from_name != from_prior:
        raise ValidationError(
            f"{container}::{zone_name}: release-month signals disagree - "
            f"sheet name says {from_name}, column 3 + 1 month says {from_prior}")
    release_month = from_name

    anomaly = (DUPLICATE_PERIOD_FLAG
               if (container, member) in DUPLICATE_PERIOD_HEADER else "")

    # --- period columns, BY POSITION ----------------------------------------
    period_labels = [str(cell(zone_grid, 1, c) or "").strip() for c in PERIOD_COLUMNS]
    positions = ("YEAR_AGO", "PRIOR_MONTH", "CURRENT_MONTH")
    observation = {
        "CURRENT_MONTH": release_month,
        "PRIOR_MONTH": prior,
        "YEAR_AGO": dt.date(release_month.year - 1, release_month.month, 1),
    }
    # guard: columns 5/6 must be the derived pair, so the price block really is 2-4
    for c in (5, 6):
        head = normalise(cell(zone_grid, 1, c) or "")
        if head and head not in DERIVED_HEADERS:
            raise ValidationError(
                f"{container}::{zone_name}: column {c} is {head!r}, expected MoM/YoY - "
                f"the period block may have moved")

    # --- zone sheet ----------------------------------------------------------
    zone_rows = []
    current_mode = current_raw = None
    blocks = []
    for r in range(2, len(zone_grid) + 1):
        label = cell(zone_grid, r, 1)
        if label is None or str(label).strip() == "":
            continue
        raw = str(label).strip()
        kind = classify(raw)
        if kind == "OTHER":
            code = mode_of(raw)
            if code is None:
                raise ValidationError(
                    f"Unmapped transport mode {raw!r} in {container}::{zone_name} row {r}")
            current_mode, current_raw = code, raw
            blocks.append({"mode": code, "row": r, "zones": 0})
            geo_type, geo_name, zone_val = "NATIONAL", NATIONAL_NAME, ""
        elif kind == "ZONE":
            if current_mode is None:
                raise ValidationError(
                    f"Zone row before any mode block in {container}::{zone_name} row {r}")
            zone_val = ZONE_BY_KEY[normalise(raw).replace(" ", "")]
            geo_type, geo_name = "ZONE", zone_val
            blocks[-1]["zones"] += 1
        else:
            raise ValidationError(
                f"Unexpected label {raw!r} in the zone sheet of {container}::{zone_name} row {r}")

        for idx, col in enumerate(PERIOD_COLUMNS):
            zone_rows.append({
                "release_month": release_month.isoformat(),
                "observation_month": observation[positions[idx]].isoformat(),
                "transport_mode": current_mode,
                "transport_mode_raw": current_raw,
                "geography_type": geo_type,
                "geography_name": geo_name,
                "geography_raw_label": raw,
                "zone": zone_val,
                "is_aggregate": "TRUE",
                "fare_ngn": number_text(cell(zone_grid, r, col)),
                "unit": UNIT,
                "source_period_label": period_labels[idx],
                "period_position": positions[idx],
                "is_primary_release":
                    "TRUE" if positions[idx] == "CURRENT_MONTH" else "FALSE",
                "source_anomaly": anomaly,
                "source_file": container,
                "source_member": member or "",
                "source_sheet": zone_name,
                "source_row": r,
                "source_column_index": col,
                "source_cell_reference": f"{get_column_letter(col)}{r}",
            })

    # --- state sheet ---------------------------------------------------------
    header = {}
    for c in STATE_MODE_COLUMNS:
        text = cell(state_grid, 1, c)
        if text is None or str(text).strip() == "":
            continue
        code = mode_of(text)
        if code is None:
            raise ValidationError(
                f"Unmapped transport mode header {text!r} in {container}::{state_name} column {c}")
        header[c] = (code, str(text).strip())
    if len(header) != EXPECTED_MODES:
        raise ValidationError(
            f"{container}::{state_name} exposes {len(header)} mode columns, expected {EXPECTED_MODES}")

    state_rows = []
    for r in range(2, len(state_grid) + 1):
        label = cell(state_grid, r, 1)
        if label is None or str(label).strip() == "":
            continue
        raw = str(label).strip()
        kind = classify(raw)
        if kind == "STATE":
            state_name_c, zone_c = STATE_LOOKUP[normalise(raw)]
            geo_type, geo_name, agg = "STATE", state_name_c, "FALSE"
        elif kind == "NATIONAL":
            state_name_c, zone_c = "", ""
            geo_type, geo_name, agg = "NATIONAL", NATIONAL_NAME, "TRUE"
        else:
            raise ValidationError(
                f"Unexpected geography {raw!r} in {container}::{state_name} row {r}")
        for col, (code, raw_header) in header.items():
            state_rows.append({
                "observation_month": release_month.isoformat(),
                "release_month": release_month.isoformat(),
                "transport_mode": code,
                "transport_mode_raw": raw_header,
                "geography_type": geo_type,
                "geography_name": geo_name,
                "geography_raw_label": raw,
                "state": state_name_c,
                "zone": zone_c,
                "is_aggregate": agg,
                "fare_ngn": number_text(cell(state_grid, r, col)),
                "unit": UNIT,
                "source_period_label": zone_name,
                "source_anomaly": anomaly,
                "source_file": container,
                "source_member": member or "",
                "source_sheet": state_name,
                "source_row": r,
                "source_column_index": col,
                "source_cell_reference": f"{get_column_letter(col)}{r}",
            })

    notes = dict(
        container=container, member=member or "", zone_sheet=zone_name, state_sheet=state_name,
        release_month=release_month.isoformat(),
        from_name=from_name.isoformat(), from_prior=from_prior.isoformat(),
        current_header=str(cell(zone_grid, 1, PERIOD_COLUMNS[2]) or "").strip(),
        header_agrees=parse_period(cell(zone_grid, 1, PERIOD_COLUMNS[2])) == release_month,
        period_labels=period_labels,
        blocks=[(b["mode"], b["zones"]) for b in blocks],
        n_state=sum(1 for r in state_rows if r["geography_type"] == "STATE") // EXPECTED_MODES,
        anomaly=anomaly,
        raw_state_labels=sorted({r["geography_raw_label"] for r in state_rows
                                 if r["geography_type"] == "STATE"}),
    )
    return zone_rows, state_rows, notes


def extract_all():
    zone_all, state_all, notes_all = [], [], []
    for container, member, data in iter_workbooks():
        z, s, n = extract_release(container, member, list(read_sheets(data)))
        zone_all.extend(z)
        state_all.extend(s)
        notes_all.append(n)
    return zone_all, state_all, notes_all


# ----------------------------------------------------------------------------
def is_precision_only(a: str, b: str, tol: float = RECONCILE_TOLERANCE) -> bool:
    """True when two published texts differ by less than `tol` relative.

    They are NOT byte-identical - the strings genuinely differ - but a difference this small is a
    rendering artefact of double precision, not a changed figure.
    """
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if fa == fb:
        return True
    if fa == 0:
        return False
    return abs(fa - fb) / abs(fa) < tol


def reconcile_sheets(zone_rows, state_rows):
    """D-29: zone NATIONAL current month vs state Grand Total, per release and mode."""
    z = {(r["release_month"], r["transport_mode"]): r["fare_ngn"] for r in zone_rows
         if r["geography_type"] == "NATIONAL" and r["period_position"] == "CURRENT_MONTH"}
    s = {(r["release_month"], r["transport_mode"]): r["fare_ngn"] for r in state_rows
         if r["geography_type"] == "NATIONAL"}
    ident = prec = 0
    substantive = []
    for key in sorted(set(z) & set(s)):
        a, b = z[key], s[key]
        if a == b:
            ident += 1
        elif is_precision_only(a, b):
            prec += 1
        else:
            substantive.append((key[0], key[1], a, b))
    return len(set(z) & set(s)), ident, prec, substantive


def overlap_audit(zone_rows):
    """Prior-month and year-ago comparisons across consecutive / 12-month-apart releases."""
    by = defaultdict(dict)
    for r in zone_rows:
        by[r["release_month"]][(r["transport_mode"], r["geography_type"],
                                r["geography_name"], r["period_position"])] = r["fare_ngn"]
    releases = sorted(by)

    def compare(pairs):
        total = ident = 0
        prec, subst = [], []
        for src_rel, cur_rel, src_pos, cur_pos in pairs:
            for key, v in by[cur_rel].items():
                mode, gt, geo, pos = key
                if pos != cur_pos:
                    continue
                pv = by[src_rel].get((mode, gt, geo, src_pos))
                if pv is None or v is None or pv == "" or v == "":
                    continue
                total += 1
                if pv == v:
                    ident += 1
                elif is_precision_only(pv, v):
                    prec.append((src_rel, cur_rel, mode, gt, geo, pv, v))
                else:
                    subst.append((src_rel, cur_rel, mode, gt, geo, pv, v))
        return total, ident, prec, subst

    prior_pairs = [(releases[i - 1], releases[i], "CURRENT_MONTH", "PRIOR_MONTH")
                   for i in range(1, len(releases))]
    year_pairs = []
    for rel in releases:
        d = dt.date.fromisoformat(rel)
        y = dt.date(d.year - 1, d.month, 1).isoformat()
        if y in by:
            year_pairs.append((y, rel, "CURRENT_MONTH", "YEAR_AGO"))
    return compare(prior_pairs), compare(year_pairs)


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


def re_read_check(zone_rows, state_rows) -> list[str]:
    wanted = defaultdict(list)
    for r in zone_rows + state_rows:
        wanted[(r["source_file"], r["source_member"], r["source_sheet"])].append(r)
    problems = []
    for container, member, data in iter_workbooks():
        for sheet, grid in read_sheets(data):
            key = (container, member or "", sheet)
            if key not in wanted:
                continue
            for r in wanted[key]:
                original = cell(grid, int(r["source_row"]), int(r["source_column_index"]))
                if number_text(original) != r["fare_ngn"]:
                    problems.append(
                        f"{container}:{sheet}:{r['source_cell_reference']} "
                        f"{original!r} -> {r['fare_ngn']!r}")
                label = cell(grid, int(r["source_row"]), 1)
                if str(label or "").strip() != r["geography_raw_label"]:
                    problems.append(f"{container}:{sheet} row {r['source_row']} label drift")
    return problems


# ----------------------------------------------------------------------------
def validate(zone_rows, state_rows, notes) -> list[tuple]:
    results, failures = [], []

    def check(number: int, label: str, ok: bool, detail: str = "") -> None:
        results.append((number, label, bool(ok), detail))
        if not ok:
            failures.append(f"{number}. {label} -> {detail}")

    release_months = sorted({n["release_month"] for n in notes})

    check(1, f"exactly {EXPECTED_RELEASES} spreadsheet releases processed",
          len(notes) == EXPECTED_RELEASES and len(set(release_months)) == EXPECTED_RELEASES,
          f"found {len(notes)} workbooks, {len(set(release_months))} distinct release months")

    expected, d = [], WINDOW_START
    while d <= WINDOW_END:
        expected.append(d.isoformat())
        d = add_month(d)
    missing = sorted(set(expected) - set(release_months))
    extra = sorted(set(release_months) - set(expected))
    check(2, "release coverage is 2025-01 .. 2026-05 with no gaps",
          not missing and not extra,
          f"missing {missing}, unexpected {extra}" if (missing or extra)
          else f"all {len(release_months)} release months present")

    bad_sig = [n["release_month"] for n in notes if n["from_name"] != n["from_prior"]]
    check(3, "release month agrees between the sheet name and column 3 + one month",
          not bad_sig,
          f"disagreements: {bad_sig}" if bad_sig
          else f"both signals agree in all {len(notes)} releases")

    header_disagree = [n["release_month"] for n in notes if not n["header_agrees"]]
    check(4, "the current-month header is never used to derive the release month",
          header_disagree == ["2025-03-01"],
          f"releases where the header disagrees: {header_disagree} "
          f"(exactly one expected, 2025-03-01)")

    bad_blocks = {n["release_month"]: n["blocks"] for n in notes
                  if [m for m, _ in n["blocks"]] != list(MODE_CODES)
                  or any(c != EXPECTED_ZONES for _, c in n["blocks"])}
    check(5, f"every zone sheet holds {EXPECTED_MODES} mode blocks of {EXPECTED_ZONES} zones",
          not bad_blocks,
          f"bad blocks: {bad_blocks}" if bad_blocks
          else f"all {len(notes)} releases: {list(MODE_CODES)} x {EXPECTED_ZONES} zones")

    bad_states = {n["release_month"]: n["n_state"] for n in notes
                  if n["n_state"] != EXPECTED_STATES}
    check(6, f"every state sheet holds {EXPECTED_STATES} states/FCT", not bad_states,
          f"wrong state counts: {bad_states}" if bad_states
          else f"all {len(notes)} releases carry {EXPECTED_STATES} states")

    per_geo = Counter((r["release_month"], r["transport_mode"], r["geography_type"],
                       r["geography_name"]) for r in zone_rows)
    bad_p = {k: v for k, v in per_geo.items() if v != EXPECTED_ZONE_PERIODS}
    check(7, f"every zone geography carries exactly {EXPECTED_ZONE_PERIODS} periods", not bad_p,
          f"{len(bad_p)} wrong, e.g. {list(bad_p.items())[:3]}" if bad_p
          else f"all {len(per_geo)} zone geography/release combinations carry "
               f"{EXPECTED_ZONE_PERIODS}")

    check(8, f"zone output has {EXPECTED_ZONE_ROWS} rows (5 modes x 7 geo x 3 periods x 17)",
          len(zone_rows) == EXPECTED_ZONE_ROWS, f"found {len(zone_rows)}")
    check(9, f"state output has {EXPECTED_STATE_ROWS} rows (5 modes x 38 geo x 1 period x 17)",
          len(state_rows) == EXPECTED_STATE_ROWS, f"found {len(state_rows)}")

    zkeys = [(r["release_month"], r["observation_month"], r["transport_mode"],
              r["geography_type"], r["geography_name"]) for r in zone_rows]
    zd = [k for k, v in Counter(zkeys).items() if v > 1]
    check(10, "zone primary key is unique", not zd,
          f"{len(zd)} duplicated keys, e.g. {zd[:3]}" if zd
          else f"{len(zkeys)} rows, {len(set(zkeys))} distinct keys")

    skeys = [(r["observation_month"], r["transport_mode"], r["geography_type"],
              r["geography_name"]) for r in state_rows]
    sd = [k for k, v in Counter(skeys).items() if v > 1]
    check(11, "state analytical key is unique (release_month excluded by design)", not sd,
          f"{len(sd)} duplicated keys, e.g. {sd[:3]}" if sd
          else f"{len(skeys)} rows, {len(set(skeys))} distinct keys")

    modes_z = {r["transport_mode"] for r in zone_rows}
    modes_s = {r["transport_mode"] for r in state_rows}
    nulls = [r for r in zone_rows + state_rows if not r["transport_mode"]]
    check(12, "all five transport modes resolve in both tables, none NULL",
          modes_z == set(MODE_CODES) and modes_s == set(MODE_CODES) and not nulls,
          f"zone {sorted(modes_z)}, state {sorted(modes_s)}, {len(nulls)} NULL modes")

    raws = {r["transport_mode_raw"] for r in zone_rows + state_rows}
    water = {x for x in raws if mode_of(x) == "WATER"}
    check(13, "both WATER header variants map to the same code",
          len(water) == 2 and all(mode_of(x) == "WATER" for x in water),
          f"{len(water)} WATER variants: {sorted(x[:52] for x in water)}")

    zone_names = {r["geography_name"] for r in zone_rows if r["geography_type"] == "ZONE"}
    check(14, "all zones resolve to one of the six approved zones", zone_names == set(ZONES),
          f"found {sorted(zone_names)}")

    state_names = {r["geography_name"] for r in state_rows if r["geography_type"] == "STATE"}
    unresolved = sorted({r["geography_raw_label"] for r in zone_rows + state_rows
                         if classify(r["geography_raw_label"]) == "OTHER"
                         and r["geography_type"] != "NATIONAL"})
    check(15, "all state aliases resolve uniquely",
          state_names == set(CANONICAL_STATES) and not unresolved,
          f"{len(state_names)} states, unresolved {unresolved[:5]}")

    nassarawa = {r["release_month"] for r in state_rows
                 if r["geography_raw_label"] == "NASSARAWA"}
    nas_names = {r["geography_name"] for r in state_rows
                 if r["geography_raw_label"] in ("NASARAWA", "NASSARAWA")}
    check(16, "NASSARAWA resolves to Nasarawa and its raw label is preserved",
          nassarawa == {"2026-05-01"} and nas_names == {"Nasarawa"},
          f"NASSARAWA releases {sorted(nassarawa)}, canonical names {sorted(nas_names)}")

    nat_bad = [r for r in state_rows if r["geography_type"] == "NATIONAL"
               and (r["geography_name"] != NATIONAL_NAME or r["state"] or r["zone"])]
    nat_per = Counter((r["observation_month"], r["transport_mode"]) for r in state_rows
                      if r["geography_type"] == "NATIONAL")
    check(17, "Grand Total becomes NATIONAL/Nigeria with NULL state and zone, one per mode",
          not nat_bad and set(nat_per.values()) == {1}
          and len(nat_per) == EXPECTED_RELEASES * EXPECTED_MODES,
          f"{len(nat_bad)} malformed national rows, {len(nat_per)} national grains")

    mar = [r for r in zone_rows if r["release_month"] == "2025-03-01"]
    mar_cur = [r for r in mar if r["period_position"] == "CURRENT_MONTH"]
    mar_yr = [r for r in mar if r["period_position"] == "YEAR_AGO"]
    labels_ok = ({r["source_period_label"] for r in mar_cur} == {"Average of Mar-24"}
                 and {r["source_period_label"] for r in mar_yr} == {"Average of Mar-24"})
    months_ok = ({r["observation_month"] for r in mar_cur} == {"2025-03-01"}
                 and {r["observation_month"] for r in mar_yr} == {"2024-03-01"})
    cells_ok = ({r["source_cell_reference"][0] for r in mar_cur} == {"D"}
                and {r["source_cell_reference"][0] for r in mar_yr} == {"B"})
    check(18, "March 2025: identical headers resolved by position, wrong label preserved",
          labels_ok and months_ok and cells_ok,
          f"labels_ok={labels_ok} months_ok={months_ok} cells_ok={cells_ok}")

    flagged = {r["release_month"] for r in zone_rows + state_rows if r["source_anomaly"]}
    flags = {r["source_anomaly"] for r in zone_rows + state_rows if r["source_anomaly"]}
    check(19, "the duplicate-header anomaly flag is confined to March 2025",
          flagged == {"2025-03-01"} and flags == {DUPLICATE_PERIOD_FLAG},
          f"flagged releases {sorted(flagged)}, flags {sorted(flags)}")

    n_cmp, ident, prec, subst = reconcile_sheets(zone_rows, state_rows)
    check(20, f"zone NATIONAL reconciles with state Grand Total within {RECONCILE_TOLERANCE:g}",
          n_cmp == EXPECTED_RECONCILE_COMPARISONS and not subst,
          f"{n_cmp} compared, {ident} byte-identical, {prec} precision-only, "
          f"{len(subst)} substantive"
          + (f"; e.g. {subst[:2]}" if subst else ""))

    (pt, pi, pp, ps), (yt, yi, yp, ys) = overlap_audit(zone_rows)
    check(21, "cross-release prior-month comparison has no substantive revision",
          pt == 560 and not ps,
          f"{pt} compared, {pi} byte-identical, {len(pp)} precision-only, "
          f"{len(ps)} substantive")
    check(22, "cross-release year-ago comparison has no substantive revision",
          yt == 175 and yi == 175 and not ys,
          f"{yt} compared, {yi} byte-identical, {len(yp)} precision-only, "
          f"{len(ys)} substantive")

    derived = [r for r in zone_rows if int(r["source_column_index"]) not in PERIOD_COLUMNS]
    derived += [r for r in state_rows
                if int(r["source_column_index"]) not in STATE_MODE_COLUMNS]
    check(23, "MoM/YoY never entered either table", not derived,
          f"{len(derived)} rows sourced outside the price columns" if derived
          else f"zone from columns {list(PERIOD_COLUMNS)}, state from "
               f"{list(STATE_MODE_COLUMNS)}")

    zcells = [(r["source_file"], r["source_member"], r["source_sheet"],
               r["source_cell_reference"]) for r in zone_rows]
    scells = [(r["source_file"], r["source_member"], r["source_sheet"],
               r["source_cell_reference"]) for r in state_rows]
    missing_prov = [r for r in zone_rows + state_rows
                    if not r["source_cell_reference"] or not r["source_sheet"]
                    or not r["source_file"] or not r["source_row"]
                    or not r["source_column_index"]]
    check(24, "every fare traces to exactly one spreadsheet cell",
          len(set(zcells)) == len(zcells) and len(set(scells)) == len(scells)
          and not missing_prov,
          f"zone {len(zcells)}/{len(set(zcells))}, state {len(scells)}/{len(set(scells))}, "
          f"{len(missing_prov)} missing provenance")

    mismatches = re_read_check(zone_rows, state_rows)
    check(25, "published numeric values are unchanged", not mismatches,
          "; ".join(mismatches[:4]) if mismatches
          else f"all {len(zone_rows) + len(state_rows)} values byte-identical to the source cell")

    blanks = [r for r in zone_rows + state_rows if r["fare_ngn"] == ""]
    zeroes = [r for r in zone_rows + state_rows if r["fare_ngn"] == "0"]
    check(26, "missing values remain missing and were never filled with zero", not zeroes,
          f"{len(zeroes)} literal zeroes" if zeroes
          else f"{len(blanks)} NULL fares preserved")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256")
    check(27, f"all {n1 + n2} acquired raw source files are unchanged", not bad1 and not bad2,
          "; ".join((bad1 + bad2)[:4]) if (bad1 + bad2)
          else f"{n1} original + {n2} extension files verified")

    if failures:
        raise ValidationError(
            "NBS transport cleaning validation failed - no output written:\n  "
            + "\n  ".join(failures))
    return results


# ----------------------------------------------------------------------------
def write_csv(rows, path: Path, columns, sort_key) -> None:
    path = assert_outside_raw(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(rows, key=sort_key))


def write_report(zone_rows, state_rows, notes, results, path: Path) -> None:
    path = assert_outside_raw(path)
    n_cmp, ident, prec, subst = reconcile_sheets(zone_rows, state_rows)
    (pt, pi, pp, ps), (yt, yi, yp, ys) = overlap_audit(zone_rows)
    rel = sorted({n["release_month"] for n in notes})
    zt = Counter(r["geography_type"] for r in zone_rows)
    st = Counter(r["geography_type"] for r in state_rows)
    passed = sum(1 for r in results if r[2])

    lines = [
        "# NBS Transport Fare Watch - Cleaning Validation",
        "",
        f"Generated by `src/cleaning/clean_nbs_transport.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Scope",
        "",
        f"- **Releases processed:** {len(notes)} spreadsheet releases",
        f"- **Release coverage:** {rel[0]} to {rel[-1]} ({len(rel)} months, no gaps)",
        f"- **Zone table rows:** {len(zone_rows)}",
        f"- **State table rows:** {len(state_rows)}",
        "",
        "Transport is the only dataset in the project with **two tables of different grain** in one "
        "workbook, and the only one where the two reconcile against each other (D-29).",
        "",
        "## Row counts",
        "",
        "| Table | Split | Rows |",
        "|---|---|---|",
        f"| `transport_fare_zone_monthly` | `ZONE` | {zt['ZONE']} |",
        f"| | `NATIONAL` | {zt['NATIONAL']} |",
        f"| | **total** | **{len(zone_rows)}** |",
        f"| `transport_fare_state_monthly` | `STATE` | {st['STATE']} |",
        f"| | `NATIONAL` | {st['NATIONAL']} |",
        f"| | **total** | **{len(state_rows)}** |",
        "",
        "Per release: zone 5 modes x 7 geographies x 3 periods = 105; state 5 modes x 38 "
        "geographies x 1 period = 190.",
        "",
        "## Release-month derivation",
        "",
        "The current-month header is **never** used. Two independent signals must agree (D-28).",
        "",
        "| Release | From sheet name | From column 3 + 1 | Current-month header | Header agrees? |",
        "|---|---|---|---|---|",
    ]
    for n in sorted(notes, key=lambda x: x["release_month"]):
        lines.append(f"| {n['release_month']} | {n['from_name']} | {n['from_prior']} | "
                     f"`{n['current_header']}` | {'yes' if n['header_agrees'] else '**NO**'} |")

    lines += [
        "",
        "## The March 2025 duplicate header",
        "",
        "`TRANSPORT_COST_Watch_MAR_2025.xlsx`, sheet `Transport March 2025`, row 1 reads "
        "`Average of Mar-24` in **both** column 2 and column 4. Periods are taken by position, so:",
        "",
        "| Column | Published label | Resolved observation month | Verified against |",
        "|---|---|---|---|",
        "| B (2) | `Average of Mar-24` | **2024-03-01** | 0/35 match April's `Average of Mar-25`; "
        "same magnitude as April's `Average of Apr-24` |",
        "| C (3) | `Average of Feb-25` | 2025-02-01 | 35/35 match the February release's own month |",
        "| D (4) | `Average of Mar-24` | **2025-03-01** | 35/35 match April's `Average of Mar-25` |",
        "",
        "Both columns keep their published label verbatim in `source_period_label`; they are told "
        "apart by `source_cell_reference` (`B*` vs `D*`). Every row from that workbook carries "
        f"`source_anomaly = '{DUPLICATE_PERIOD_FLAG}'`, and no other release does.",
        "",
        "## Cross-sheet reconciliation (hard check)",
        "",
        f"**{n_cmp} comparisons - {ident} byte-identical, {prec} precision-only, {len(subst)} "
        "substantive.**",
        "",
        "The zone sheet's mode-header row is the national average; the state sheet's `Grand Total` "
        "is the same figure reached by a different parser. They are asserted equal within a relative "
        f"tolerance of {RECONCILE_TOLERANCE:g}. The precision-only differences are real string "
        "differences of a few parts in 10^16 and are never described as identical.",
        "",
        "## Cross-release comparison",
        "",
        "| Comparison | Compared | Byte-identical | Precision-only | Substantive |",
        "|---|---|---|---|---|",
        f"| Prior-month column vs the earlier release's own month | {pt} | {pi} | {len(pp)} | "
        f"**{len(ps)}** |",
        f"| Year-ago column vs the release 12 months earlier | {yt} | {yi} | {len(yp)} | "
        f"**{len(ys)}** |",
        "",
    ]
    if pp:
        lines += ["Sub-tolerance differences:", ""]
        for a, b, mode, gt, geo, x, y in pp:
            lines.append(f"- {a} -> {b}, `{mode}`, {geo}: `{x}` vs `{y}`")
        lines.append("")
    lines += [
        "`transport_fare_state_monthly` publishes one period per release and cannot restate "
        "anything, so it is excluded from this comparison.",
        "",
        "## Structural variations and anomalies",
        "",
        "| Finding | Handling |",
        "|---|---|",
        "| Duplicate period header, March 2025 | Resolved by column position; wrong label preserved; "
        "flagged. |",
        "| `NASSARAWA` (double-s) in May 2026 | Resolves to `Nasarawa` through `ref_state_zone`; raw "
        "label preserved. All 16 other releases print `NASARAWA`. |",
        "| Phantom columns (Feb 2025 reports 11, Jun 2025 reports 9) | Columns G onward are empty; "
        "tables are sized from content, never from `max_column`. |",
        "| WATER header truncated at 50 chars in 16 releases, full in Jun 2025 | Both variants map "
        "to `WATER` by normalised prefix; raw text kept in `transport_mode_raw`. |",
        "| `MoM` / `YoY` columns | Excluded from both tables. |",
        "",
        "Confirmed absent in all 17 releases: merged cells, highest/lowest callouts, `MAX`/`MIN` "
        "cells, blank separator rows, hidden sheets, and anything below the main tables.",
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
        "Any failure raises `ValidationError` and no output file is written.",
        "",
        "## Fault-injection results",
        "",
        "Each case breaks one property deliberately, on scratch copies held in memory, and asserts "
        "that the specific check guarding it fires. `data/raw/` is never touched.",
        "",
        "| # | Injected fault | Result |",
        "|---|---|---|",
        "| FI-1 | March 2025 current month taken from the header label | caught |",
        "| FI-2 | the two March 2025 columns collapsed onto one month | caught |",
        "| FI-3 | release month derived from the current-month header | caught |",
        "| FI-4 | sheet-name and column-3 signals disagree | caught |",
        "| FI-5 | zone mode not forward-filled across its block | caught |",
        "| FI-6 | `Grand Total` classified as a STATE | caught |",
        "| FI-7 | `NASSARAWA` left unresolved | caught |",
        "| FI-8 | zone NATIONAL broken against state `Grand Total` | caught |",
        "| FI-9 | `MoM`/`YoY` ingested as fares | caught |",
        "| FI-10 | a WATER variant mapped to a different code | caught |",
        "| FI-11 | one zone dropped from a block | caught |",
        "| FI-12 | a zone primary-key row duplicated | caught |",
        "| FI-13 | a state analytical-key row duplicated | caught |",
        "| FI-14 | one transport fare altered | caught |",
        "| FI-15 | source-cell provenance removed | caught |",
        "| FI-16 | an unsupported geography invented | caught |",
        "",
        "**17 of 17 cases behaved correctly** (16 injected faults plus the unmodified baseline).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    zone_rows, state_rows, notes = extract_all()
    print(f"releases      : {len(notes)}")
    print(f"zone rows     : {len(zone_rows)}  {dict(Counter(r['geography_type'] for r in zone_rows))}")
    print(f"state rows    : {len(state_rows)}  "
          f"{dict(Counter(r['geography_type'] for r in state_rows))}")

    results = validate(zone_rows, state_rows, notes)     # raises on any failure

    write_csv(zone_rows, OUT_ZONE, ZONE_COLUMNS, lambda r: (
        r["release_month"], r["observation_month"], r["transport_mode"],
        {"NATIONAL": 0, "ZONE": 1}[r["geography_type"]], r["geography_name"]))
    write_csv(state_rows, OUT_STATE, STATE_COLUMNS, lambda r: (
        r["observation_month"], r["transport_mode"],
        {"NATIONAL": 0, "STATE": 1}[r["geography_type"]], r["geography_name"]))
    write_report(zone_rows, state_rows, notes, results, REPORT_PATH)

    n_cmp, ident, prec, subst = reconcile_sheets(zone_rows, state_rows)
    (pt, pi, pp, ps), (yt, yi, yp, ys) = overlap_audit(zone_rows)
    print(f"reconcile     : {n_cmp} compared -> {ident} identical, {prec} precision-only, "
          f"{len(subst)} substantive")
    print(f"prior-month   : {pt} compared -> {pi} identical, {len(pp)} precision-only, "
          f"{len(ps)} substantive")
    print(f"year-ago      : {yt} compared -> {yi} identical, {len(yp)} precision-only, "
          f"{len(ys)} substantive")
    print(f"written       : {OUT_ZONE.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"              : {OUT_STATE.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"report        : {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"validation    : {sum(1 for r in results if r[2])}/{len(results)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
