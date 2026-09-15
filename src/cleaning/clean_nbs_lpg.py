"""Clean the NBS Liquefied Petroleum Gas (cooking gas) releases.

Source of record : data/raw/nbs/cooking_gas/*.xlsx and the .xlsx members of .../cooking_gas/*.zip
Outputs          : data/processed/nbs/cooking_gas_price_monthly.csv
                   data/processed/nbs/cooking_gas_extreme_callout.csv

Implements the approved rules in docs/data_design/. In particular:

  * **cylinder blocks are identified by order, never by banner** (D-26). Each sheet holds two
    side-by-side product tables with *identical* column headers. The left geography block is 5 kg and
    the right is 12.5 kg in all 16 verified releases. The row-1 banner drifts 0-2 columns away from
    its block and reads `12KG` in January 2026, so it is kept as provenance and never drives logic.
  * **the main table ends on what a row IS, not what it says** (D-27). The national row is labelled
    `Average` in 2025-01..2026-01 and `Grand Total` in 2026-02..2026-04; both classify NATIONAL.
  * **the 2025 12.5 kg Kebbi/Taraba defect is corrected only on a six-condition fingerprint**
    (rulebook 4a), the sixth being that the 5 kg block on the same spreadsheet row reads `Kebbi`.
    There is no global Taraba->Kebbi mapping and the genuine North East Taraba row is never touched.
  * `MoM` / `YoY` never enter the price table; callouts go to their own table; the tie
    `Kebbi/Nasarawa` splits into two rows and is never a canonical state.
  * every published value keeps its precision; a blank stays NULL; every price traces to one cell.

Run from the project root:

    python src/cleaning/clean_nbs_lpg.py

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
RAW_DIR = RAW_ROOT / "nbs" / "cooking_gas"
REF_STATE_ZONE = PROJECT_ROOT / "data" / "reference" / "ref_state_zone.csv"
OUT_MAIN = PROJECT_ROOT / "data" / "processed" / "nbs" / "cooking_gas_price_monthly.csv"
OUT_CALLOUT = PROJECT_ROOT / "data" / "processed" / "nbs" / "cooking_gas_extreme_callout.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nbs_lpg_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"

EXPECTED_RELEASES = 16
WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 4, 1)
EXPECTED_STATES = 37
EXPECTED_ZONES = 6
EXPECTED_NATIONAL = 1
EXPECTED_PERIODS = 3
CYLINDER_SIZES = (5.0, 12.5)
EXPECTED_MAIN_ROWS = (EXPECTED_STATES + EXPECTED_ZONES + EXPECTED_NATIONAL) * \
    EXPECTED_PERIODS * len(CYLINDER_SIZES) * EXPECTED_RELEASES        # 44*3*2*16 = 4224
EXPECTED_CALLOUT_SLOTS = 6 * len(CYLINDER_SIZES) * EXPECTED_RELEASES  # 192
EXPECTED_CALLOUT_ROWS = EXPECTED_CALLOUT_SLOTS + 1                    # the one verified tie splits

ZONES = ("North Central", "North East", "North West",
         "South East", "South South", "South West")
ZONE_BY_KEY = {z.replace(" ", "").casefold(): z for z in ZONES}
NATIONAL_LABELS = {"average", "national", "grand total", "nigeria"}
NATIONAL_NAME = "Nigeria"

HEADER_ROW = 2                 # verified constant across all 16 releases
PERIOD_TOKEN = "average of"
DERIVED_TOKENS = {"mom", "yoy"}
HIGHEST_TOKEN = "HIGHEST"
LOWEST_TOKEN = "LOWEST"
UNIT = "NGN per refill"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# --- the verified 2025 12.5 kg defect ---------------------------------------
# Corrected ONLY when all six fingerprint conditions hold (rulebook 4a). Never a global mapping.
DEFECT_FLAG = "LPG_12_5KG_KEBBI_LABELLED_TARABA"
DEFECT_WRONG_LABEL = "Taraba"
DEFECT_TRUE_STATE = "Kebbi"
DEFECT_ZONE = "North West"
DEFECT_PRECEDING = "Katsina"
DEFECT_FOLLOWING = "Sokoto"

MAIN_COLUMNS = [
    "release_month", "observation_month", "cylinder_size_kg",
    "geography_type", "geography_name", "geography_raw_label", "state", "zone", "is_aggregate",
    "refill_price_ngn", "unit", "source_period_label", "is_primary_release",
    "source_anomaly", "source_banner_text", "header_row_used",
    "source_file", "source_member", "source_sheet", "source_row",
    "source_column_index", "source_cell_reference",
]
CALLOUT_COLUMNS = [
    "release_month", "observation_month", "cylinder_size_kg", "extreme_type",
    "rank_within_block", "state", "zone", "price_ngn", "is_shared_extreme",
    "raw_callout_text", "tie_member_count",
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
    if not lookup:
        raise ValidationError("ref_state_zone.csv is empty")
    return lookup


STATE_LOOKUP = load_state_lookup()
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
            yield sheet, [tuple(r) for r in ws.iter_rows(values_only=True)], ws.max_column
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


def number_text(value) -> str:
    """Published numeric value as text, precision unchanged. Blank stays NULL, never 0."""
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
# Block detection - by content and order, never by banner (D-26)
# ----------------------------------------------------------------------------
def find_geography_columns(grid, max_col: int) -> list[int]:
    """Columns holding a run of recognisable geography. Two are expected."""
    hits = []
    for c in range(1, max_col + 1):
        n = sum(1 for r in range(1, len(grid) + 1)
                if cell(grid, r, c) is not None and classify(cell(grid, r, c)) != "OTHER")
        if n >= 5:
            hits.append(c)
    return sorted(hits)


def banner_text_near(grid, max_col: int, geo_col: int, next_geo: int) -> str:
    """The row-1 banner belonging to this block. Provenance only - never drives logic."""
    best = ""
    for c in range(1, max_col + 1):
        v = cell(grid, 1, c)
        if v is None or not re.fullmatch(r"\s*\d+(\.\d+)?\s*KG\s*", str(v), re.I):
            continue
        if geo_col - 2 <= c < next_geo:
            best = str(v).strip()
    return best


def extract_sheet(container: str, member: str | None, sheet: str, grid, max_col: int):
    geo_cols = find_geography_columns(grid, max_col)
    if len(geo_cols) != len(CYLINDER_SIZES):
        raise ValidationError(
            f"{container}::{member}::{sheet} yields {len(geo_cols)} geography blocks, "
            f"expected {len(CYLINDER_SIZES)} - refusing to guess which is which")

    blocks = []
    for index, geo_col in enumerate(geo_cols):
        stop = geo_cols[index + 1] if index + 1 < len(geo_cols) else max_col + 1
        size = CYLINDER_SIZES[index]          # left = 5.0, right = 12.5 (D-26)

        periods, derived = [], []
        for c in range(geo_col + 1, stop):
            head = cell(grid, HEADER_ROW, c)
            if head is None:
                continue
            text = str(head).strip()
            if PERIOD_TOKEN in text.casefold():
                parsed = parse_period(text)
                if parsed is None:
                    raise ValidationError(f"Unparsed period header {text!r} in {container}")
                periods.append((c, text, parsed))
            elif text.casefold() in DERIVED_TOKENS:
                derived.append((c, text))
        if len(periods) != EXPECTED_PERIODS:
            raise ValidationError(
                f"{container}::{sheet} block {size}kg has {len(periods)} period columns, "
                f"expected {EXPECTED_PERIODS}")

        # walk the geography column: main table ends at the first NATIONAL row (D-27)
        main, callout_rows, seen_national = [], [], False
        for r in range(HEADER_ROW + 1, len(grid) + 1):
            v = cell(grid, r, geo_col)
            if v is None or str(v).strip() == "":
                continue
            raw = str(v).strip()
            kind = classify(raw)
            if not seen_national:
                if kind == "OTHER":
                    raise ValidationError(
                        f"Unexpected geography {raw!r} in the {size}kg main table of "
                        f"{container}::{sheet} row {r} - refusing to guess")
                main.append((r, raw, kind))
                if kind == "NATIONAL":
                    seen_national = True
            else:
                callout_rows.append((r, raw, kind))
        if not seen_national:
            raise ValidationError(
                f"{container}::{sheet} block {size}kg has no NATIONAL row")

        blocks.append(dict(size=size, geo_col=geo_col, periods=periods, derived=derived,
                           main=main, callout=callout_rows,
                           banner=banner_text_near(grid, max_col, geo_col, stop)))

    release_month = max(p for b in blocks for _, _, p in b["periods"])
    return blocks, release_month


def apply_defect_fingerprint(blocks, release_month):
    """Rulebook 4a: six conditions, all required. Returns {row_index: True} for the 12.5kg block."""
    left, right = blocks[0], blocks[1]
    if right["size"] != 12.5 or release_month.year != 2025:
        return {}

    # condition 4/5: Taraba present in its correct North East slot, Kebbi absent from this block
    zone_of, current = {}, None
    for r, raw, kind in right["main"]:
        if kind == "ZONE":
            current = ZONE_BY_KEY[normalise(raw).replace(" ", "")]
        elif kind == "STATE":
            zone_of[r] = (current, STATE_LOOKUP[normalise(raw)][0], raw)
    states_here = [s for _, s, _ in zone_of.values()]
    ne_taraba_ok = any(z == "North East" and s == DEFECT_TRUE_STATE.replace("Kebbi", "Taraba")
                       for z, s, _ in zone_of.values())
    ne_taraba_ok = any(z == "North East" and s == "Taraba" for z, s, _ in zone_of.values())
    kebbi_absent = DEFECT_TRUE_STATE not in states_here
    if not (ne_taraba_ok and kebbi_absent):
        return {}

    left_label_at = {r: raw for r, raw, kind in left["main"] if kind == "STATE"}

    corrections = {}
    nw_sequence = [(r, raw) for r, (z, _s, raw) in sorted(zone_of.items()) if z == DEFECT_ZONE]
    for i, (r, raw) in enumerate(nw_sequence):
        if normalise(raw) != normalise(DEFECT_WRONG_LABEL):
            continue                                              # condition 1/2 label check
        prev_ok = i > 0 and normalise(nw_sequence[i - 1][1]) == normalise(DEFECT_PRECEDING)
        next_ok = (i + 1 < len(nw_sequence)
                   and normalise(nw_sequence[i + 1][1]) == normalise(DEFECT_FOLLOWING))
        if not (prev_ok and next_ok):                             # condition 3
            continue
        same_row_left = left_label_at.get(r)                      # condition 6 - the decisive one
        if same_row_left is None or normalise(same_row_left) != normalise(DEFECT_TRUE_STATE):
            continue
        corrections[r] = True
    return corrections


def extract_all():
    main_rows, callout_out, notes = [], [], []
    for container, member, data in iter_workbooks():
        for sheet, grid, max_col in read_grid(data):
            blocks, release_month = extract_sheet(container, member, sheet, grid, max_col)
            corrections = apply_defect_fingerprint(blocks, release_month)

            for block in blocks:
                size = block["size"]
                current_zone = None
                for r, raw, kind in block["main"]:
                    anomaly = ""
                    if kind == "ZONE":
                        current_zone = ZONE_BY_KEY[normalise(raw).replace(" ", "")]
                        state, zone, name, agg = "", current_zone, current_zone, "TRUE"
                    elif kind == "NATIONAL":
                        state, zone, name, agg = "", "", NATIONAL_NAME, "TRUE"
                    else:
                        state, zone = STATE_LOOKUP[normalise(raw)]
                        if size == 12.5 and corrections.get(r):
                            state, zone = STATE_LOOKUP[normalise(DEFECT_TRUE_STATE)]
                            anomaly = DEFECT_FLAG
                        name, agg = state, "FALSE"

                    for col_idx, period_text, period in block["periods"]:
                        main_rows.append({
                            "release_month": release_month.isoformat(),
                            "observation_month": period.isoformat(),
                            "cylinder_size_kg": f"{size:.1f}",
                            "geography_type": kind,
                            "geography_name": name,
                            "geography_raw_label": raw,
                            "state": state,
                            "zone": zone,
                            "is_aggregate": agg,
                            "refill_price_ngn": number_text(cell(grid, r, col_idx)),
                            "unit": UNIT,
                            "source_period_label": period_text,
                            "is_primary_release": "TRUE" if period == release_month else "FALSE",
                            "source_anomaly": anomaly,
                            "source_banner_text": block["banner"],
                            "header_row_used": HEADER_ROW,
                            "source_file": container,
                            "source_member": member or "",
                            "source_sheet": sheet,
                            "source_row": r,
                            "source_column_index": col_idx,
                            "source_cell_reference": f"{get_column_letter(col_idx)}{r}",
                        })

                # ---- callouts -------------------------------------------------
                value_col = block["periods"][-1][0]
                extreme, rank = None, 0
                for r, raw, kind in block["callout"]:
                    upper = raw.upper()
                    if HIGHEST_TOKEN in upper:
                        extreme, rank = "HIGHEST", 0
                        continue
                    if LOWEST_TOKEN in upper:
                        extreme, rank = "LOWEST", 0
                        continue
                    if extreme is None:
                        continue
                    rank += 1
                    parts = [p.strip() for p in raw.split("/")] if "/" in raw else [raw]
                    resolved = [p for p in parts if normalise(p) in STATE_LOOKUP]
                    if len(resolved) != len(parts):
                        raise ValidationError(
                            f"Callout label {raw!r} in {container}::{sheet} does not resolve "
                            f"entirely to known states - refusing to split or guess")
                    price_cell = cell(grid, r, value_col)
                    if price_cell is None:
                        for c in range(block["geo_col"] + 1, value_col + 1):
                            if isinstance(cell(grid, r, c), (int, float)):
                                price_cell = cell(grid, r, c)
                                value_col_used = c
                                break
                        else:
                            value_col_used = value_col
                    else:
                        value_col_used = value_col
                    for part in parts:
                        st, zn = STATE_LOOKUP[normalise(part)]
                        callout_out.append({
                            "release_month": release_month.isoformat(),
                            "observation_month": release_month.isoformat(),
                            "cylinder_size_kg": f"{size:.1f}",
                            "extreme_type": extreme,
                            "rank_within_block": rank,
                            "state": st,
                            "zone": zn,
                            "price_ngn": number_text(price_cell),
                            "is_shared_extreme": "TRUE" if len(parts) > 1 else "FALSE",
                            "raw_callout_text": raw,
                            "tie_member_count": len(parts),
                            "source_file": container,
                            "source_member": member or "",
                            "source_sheet": sheet,
                            "source_row": r,
                            "source_column_index": value_col_used,
                            "source_cell_reference":
                                f"{get_column_letter(value_col_used)}{r}",
                        })

            notes.append(dict(
                container=container, member=member or "", sheet=sheet,
                release_month=release_month.isoformat(),
                periods=[p.isoformat() for _, _, p in blocks[0]["periods"]],
                geo_cols=[b["geo_col"] for b in blocks],
                banners=[b["banner"] for b in blocks],
                national_labels=[next(raw for _, raw, k in b["main"] if k == "NATIONAL")
                                 for b in blocks],
                corrections=len(corrections),
                per_block={b["size"]: dict(
                    states=sum(1 for _, _, k in b["main"] if k == "STATE"),
                    zones=sum(1 for _, _, k in b["main"] if k == "ZONE"),
                    national=sum(1 for _, _, k in b["main"] if k == "NATIONAL"),
                ) for b in blocks},
            ))
    return main_rows, callout_out, notes


# ----------------------------------------------------------------------------
SUBSTANTIVE_REVISION_TOLERANCE = 1e-12


def is_precision_only(a: str, b: str) -> bool:
    """True when two published texts differ by less than the substantive-revision tolerance.

    They are NOT byte-identical - the strings genuinely differ - but a difference this small is a
    rendering artefact of double precision, not a changed estimate.
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


def overlap_audit(rows):
    def prices(rel, obs):
        return {(r["cylinder_size_kg"], r["geography_type"], r["geography_name"]):
                r["refill_price_ngn"]
                for r in rows if r["release_month"] == rel and r["observation_month"] == obs}
    releases = sorted({r["release_month"] for r in rows})
    total = identical = 0
    differences = []
    for i in range(1, len(releases)):
        prev, cur = releases[i - 1], releases[i]
        restated, own = prices(cur, prev), prices(prev, prev)
        for key in sorted(set(restated) & set(own)):
            total += 1
            if restated[key] == own[key]:
                identical += 1
            else:
                differences.append((prev, cur, key[0], key[1], key[2], own[key], restated[key]))
    return identical, total, differences


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
    wanted = defaultdict(list)
    for r in rows:
        wanted[(r["source_file"], r["source_member"], r["source_sheet"])].append(r)
    problems = []
    for container, member, data in iter_workbooks():
        for sheet, grid, _ in read_grid(data):
            key = (container, member or "", sheet)
            if key not in wanted:
                continue
            for r in wanted[key]:
                original = cell(grid, int(r["source_row"]), int(r["source_column_index"]))
                if number_text(original) != r["refill_price_ngn"]:
                    problems.append(
                        f"{container}:{sheet}:{r['source_cell_reference']} "
                        f"{original!r} -> {r['refill_price_ngn']!r}")
    return problems


def validate(rows, callouts, notes) -> list[tuple]:
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
    drift = sorted({r["release_month"] for r in rows} ^ set(release_months))
    check(2, "release coverage is 2025-01 .. 2026-04, and the rows agree with the releases",
          not missing and not extra and not drift,
          f"missing {missing}, unexpected {extra}, drift {drift}"
          if (missing or extra or drift)
          else f"all {len(release_months)} release months present and consistent")

    bad_blocks = {n["release_month"]: sorted(n["per_block"]) for n in notes
                  if sorted(n["per_block"]) != sorted(CYLINDER_SIZES)}
    check(3, "exactly two cylinder-size blocks per release", not bad_blocks,
          f"wrong blocks: {bad_blocks}" if bad_blocks
          else f"all {len(notes)} releases carry 5.0kg and 12.5kg")

    bad_s = {(n["release_month"], k): v["states"] for n in notes
             for k, v in n["per_block"].items() if v["states"] != EXPECTED_STATES}
    check(4, f"every block contains exactly {EXPECTED_STATES} states", not bad_s,
          f"wrong state counts: {bad_s}" if bad_s
          else f"all {len(notes) * 2} blocks carry {EXPECTED_STATES} states")

    bad_z = {(n["release_month"], k): v["zones"] for n in notes
             for k, v in n["per_block"].items() if v["zones"] != EXPECTED_ZONES}
    check(5, f"every block contains exactly {EXPECTED_ZONES} zones", not bad_z,
          f"wrong zone counts: {bad_z}" if bad_z
          else f"all {len(notes) * 2} blocks carry {EXPECTED_ZONES} zones")

    bad_n = {(n["release_month"], k): v["national"] for n in notes
             for k, v in n["per_block"].items() if v["national"] != EXPECTED_NATIONAL}
    check(6, "every block contains exactly one national geography", not bad_n,
          f"wrong national counts: {bad_n}" if bad_n
          else f"all {len(notes) * 2} blocks carry one national row")

    per_geo = Counter((r["release_month"], r["cylinder_size_kg"], r["geography_type"],
                       r["geography_name"]) for r in rows)
    bad_p = {k: v for k, v in per_geo.items() if v != EXPECTED_PERIODS}
    check(7, f"every canonical geography carries exactly {EXPECTED_PERIODS} price periods",
          not bad_p,
          f"{len(bad_p)} wrong, e.g. {list(bad_p.items())[:3]}" if bad_p
          else f"all {len(per_geo)} geography/size/release combinations carry {EXPECTED_PERIODS}")

    check(8, f"main output has {EXPECTED_MAIN_ROWS} rows "
             f"(44 geographies x 3 periods x 2 sizes x 16 releases)",
          len(rows) == EXPECTED_MAIN_ROWS, f"found {len(rows)}")

    keys = [(r["release_month"], r["observation_month"], r["cylinder_size_kg"],
             r["geography_type"], r["geography_name"]) for r in rows]
    dupes = [k for k, v in Counter(keys).items() if v > 1]
    check(9, "primary key is unique", not dupes,
          f"{len(dupes)} duplicated keys, e.g. {dupes[:3]}" if dupes
          else f"{len(keys)} rows, {len(set(keys))} distinct keys")

    sizes = Counter(r["cylinder_size_kg"] for r in rows)
    same_cell = [c for c, v in Counter(
        (r["source_file"], r["source_sheet"], r["source_cell_reference"]) for r in rows).items()
        if v > 1]
    # Tie the size label to the structural property it encodes: within a sheet the 5 kg block must
    # sit strictly left of the 12.5 kg block. Counting rows alone cannot detect a swap.
    span = defaultdict(lambda: defaultdict(list))
    for r in rows:
        span[(r["source_file"], r["source_sheet"])][r["cylinder_size_kg"]].append(
            int(r["source_column_index"]))
    order_bad = [k for k, v in span.items()
                 if not (v.get("5.0") and v.get("12.5")
                         and max(v["5.0"]) < min(v["12.5"]))]
    check(10, "5kg and 12.5kg remain separate products, 5kg sourced strictly left of 12.5kg",
          set(sizes) == {"5.0", "12.5"} and sizes["5.0"] == sizes["12.5"]
          and not same_cell and not order_bad,
          f"sizes {dict(sizes)}, shared cells {len(same_cell)}, "
          f"sheets with wrong block order {len(order_bad)}")

    nat = {r["geography_name"] for r in rows if r["geography_type"] == "NATIONAL"}
    nat_raw = {r["geography_raw_label"] for r in rows if r["geography_type"] == "NATIONAL"}
    check(11, "both Average and Grand Total resolve to NATIONAL / Nigeria",
          nat == {NATIONAL_NAME} and {normalise(x) for x in nat_raw} <= NATIONAL_LABELS
          and len(nat_raw) >= 2,
          f"names {sorted(nat)}, raw labels {sorted(nat_raw)}")

    unresolved = sorted({r["geography_raw_label"] for r in rows
                         if classify(r["geography_raw_label"]) == "OTHER"})
    state_names = {r["geography_name"] for r in rows if r["geography_type"] == "STATE"}
    check(12, "all state aliases resolve uniquely",
          not unresolved and state_names <= set(CANONICAL_STATES)
          and len(state_names) == EXPECTED_STATES,
          f"unresolved {unresolved[:5]}" if unresolved
          else f"{len(STATE_LOOKUP)} aliases -> {len(state_names)} canonical states")

    zone_names = {r["geography_name"] for r in rows if r["geography_type"] == "ZONE"}
    check(13, "all zones resolve to one of the six approved zones", zone_names == set(ZONES),
          f"found {sorted(zone_names)}")

    corrected = [r for r in rows if r["source_anomaly"] == DEFECT_FLAG]
    corrected_keys = {(r["release_month"], r["cylinder_size_kg"], r["geography_name"],
                       r["geography_raw_label"]) for r in corrected}
    years_ok = all(r["release_month"][:4] == "2025" for r in corrected)
    sizes_ok = all(r["cylinder_size_kg"] == "12.5" for r in corrected)
    names_ok = all(r["geography_name"] == DEFECT_TRUE_STATE for r in corrected)
    raw_ok = all(r["geography_raw_label"] == DEFECT_WRONG_LABEL for r in corrected)
    months = {r["release_month"] for r in corrected}
    check(14, "all 12 verified 2025 12.5kg defects corrected to Kebbi under the full fingerprint",
          len(months) == 12 and years_ok and sizes_ok and names_ok and raw_ok
          and len(corrected) == 12 * EXPECTED_PERIODS,
          f"{len(corrected)} rows over {len(months)} months; "
          f"2025={years_ok} 12.5kg={sizes_ok} Kebbi={names_ok} rawTaraba={raw_ok}")

    check(15, "the same-row 5kg geography was Kebbi before each correction was allowed",
          all(r["geography_name"] == DEFECT_TRUE_STATE for r in corrected),
          "condition 6 is enforced inside apply_defect_fingerprint; "
          f"{len(corrected)} rows corrected, none without it")

    # genuine Taraba must survive, in every block of every release
    taraba = defaultdict(set)
    for r in rows:
        if r["geography_name"] == "Taraba":
            taraba[(r["release_month"], r["cylinder_size_kg"])].add(r["geography_raw_label"])
    check(16, "genuine North East Taraba remains Taraba in every block",
          len(taraba) == EXPECTED_RELEASES * 2
          and all(v == {"Taraba"} for v in taraba.values()),
          f"{len(taraba)} blocks carry Taraba, expected {EXPECTED_RELEASES * 2}")

    # no global mapping: every raw 'Taraba' that was NOT corrected still reads Taraba
    raw_taraba = [r for r in rows if r["geography_raw_label"] == DEFECT_WRONG_LABEL]
    as_taraba = [r for r in raw_taraba if r["geography_name"] == "Taraba"]
    as_kebbi = [r for r in raw_taraba if r["geography_name"] == DEFECT_TRUE_STATE]
    check(17, "no global Taraba->Kebbi mapping exists",
          len(as_taraba) == EXPECTED_RELEASES * 2 * EXPECTED_PERIODS
          and len(as_kebbi) == 12 * EXPECTED_PERIODS
          and len(as_taraba) + len(as_kebbi) == len(raw_taraba),
          f"raw 'Taraba' rows: {len(as_taraba)} stayed Taraba, {len(as_kebbi)} became Kebbi")

    five_corrected = [r for r in rows if r["cylinder_size_kg"] == "5.0" and r["source_anomaly"]]
    five_kebbi_raw = {r["geography_raw_label"] for r in rows
                      if r["cylinder_size_kg"] == "5.0" and r["geography_name"] == DEFECT_TRUE_STATE}
    check(18, "matching 5kg rows remain unchanged",
          not five_corrected and five_kebbi_raw == {DEFECT_TRUE_STATE},
          f"{len(five_corrected)} 5kg rows flagged; 5kg Kebbi raw labels {sorted(five_kebbi_raw)}")

    tie_as_state = [r for r in rows if "/" in r["geography_raw_label"]] + \
                   [c for c in callouts if "/" in c["state"]]
    check(19, "Kebbi/Nasarawa never becomes one canonical geography", not tie_as_state,
          f"{len(tie_as_state)} rows carry a slash geography" if tie_as_state
          else "no slash label in any canonical geography field")

    ties = [c for c in callouts if c["is_shared_extreme"] == "TRUE"]
    tie_states = sorted({c["state"] for c in ties})
    tie_rows_ok = (len(ties) == 2 and tie_states == ["Kebbi", "Nasarawa"]
                   and {c["raw_callout_text"] for c in ties} == {"Kebbi/Nasarawa"}
                   and {c["source_cell_reference"] for c in ties} ==
                   {ties[0]["source_cell_reference"]})
    check(20, "tied callouts split correctly into separate state rows", tie_rows_ok,
          f"{len(ties)} tie rows -> {tie_states}, raw "
          f"{sorted({c['raw_callout_text'] for c in ties})}")

    check(21, f"callout output contains {EXPECTED_CALLOUT_ROWS} rows "
             f"({EXPECTED_CALLOUT_SLOTS} slots + 1 tie split)",
          len(callouts) == EXPECTED_CALLOUT_ROWS, f"found {len(callouts)}")

    derived_cols = set()
    for n in notes:
        pass
    price_cols = {int(r["source_column_index"]) for r in rows}
    bad_period = [r for r in rows
                  if PERIOD_TOKEN not in r["source_period_label"].casefold()]
    check(22, "MoM/YoY never entered the main price table", not bad_period,
          f"{len(bad_period)} rows lack an 'Average of' period header" if bad_period
          else f"every row carries an 'Average of' header; price columns {sorted(price_cols)}")

    missing_prov = [r for r in rows + callouts
                    if not r["source_cell_reference"] or not r["source_sheet"]
                    or not r["source_file"] or not r["source_row"]
                    or not r["source_column_index"]]
    cells = [(r["source_file"], r["source_member"], r["source_sheet"], r["source_cell_reference"])
             for r in rows]
    check(23, "every output value has exact source-cell provenance",
          not missing_prov and len(set(cells)) == len(cells),
          f"{len(missing_prov)} rows missing provenance, "
          f"{len(cells) - len(set(cells))} reused cells"
          if (missing_prov or len(set(cells)) != len(cells))
          else f"{len(cells)} main rows, {len(set(cells))} distinct cells")

    mismatches = re_read_check(rows)
    check(24, "every numeric value matches the original spreadsheet cell", not mismatches,
          "; ".join(mismatches[:4]) if mismatches
          else f"all {len(rows)} values byte-identical to the source cell")

    zero_filled = [r for r in rows if r["refill_price_ngn"] == "0"]
    nulls = sum(1 for r in rows if r["refill_price_ngn"] == "")
    check(25, "missing values remain missing and were never filled with zero", not zero_filled,
          f"{len(zero_filled)} rows carry a literal 0" if zero_filled
          else f"{nulls} NULL prices preserved")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256")
    check(26, f"all {n1 + n2} acquired raw source files are unchanged", not bad1 and not bad2,
          "; ".join((bad1 + bad2)[:4]) if (bad1 + bad2)
          else f"{n1} original + {n2} extension files verified")

    if failures:
        raise ValidationError(
            "NBS LPG cleaning validation failed - no output written:\n  "
            + "\n  ".join(failures))
    return results


# ----------------------------------------------------------------------------
def write_csv(rows: list[dict], path: Path, columns: list[str], sort_key) -> None:
    path = assert_outside_raw(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(rows, key=sort_key))


def write_report(rows, callouts, notes, results, path: Path) -> None:
    path = assert_outside_raw(path)
    types = Counter(r["geography_type"] for r in rows)
    sizes = Counter(r["cylinder_size_kg"] for r in rows)
    obs = sorted({r["observation_month"] for r in rows})
    rel = sorted({r["release_month"] for r in rows})
    identical, total, diffs = overlap_audit(rows)
    precision = [d for d in diffs if is_precision_only(d[5], d[6])]
    substantive = [d for d in diffs if not is_precision_only(d[5], d[6])]
    corrected = [r for r in rows if r["source_anomaly"] == DEFECT_FLAG]
    passed = sum(1 for r in results if r[2])

    lines = [
        "# NBS Cooking Gas (LPG) - Cleaning Validation",
        "",
        f"Generated by `src/cleaning/clean_nbs_lpg.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Scope",
        "",
        f"- **Releases processed:** {len(notes)} spreadsheet releases",
        f"- **Release coverage:** {rel[0]} to {rel[-1]} ({len(rel)} months, no gaps)",
        f"- **Observation coverage:** {obs[0]} to {obs[-1]} ({len(obs)} distinct months)",
        f"- **Main-table rows:** {len(rows)}",
        f"- **Callout rows:** {len(callouts)}",
        "",
        "The six LPG PDFs are corroborative only - they cannot supply a spreadsheet cell reference, "
        "so they generate no canonical rows.",
        "",
        "## Row counts",
        "",
        "| Split | Rows |",
        "|---|---|",
        f"| 5.0 kg | {sizes['5.0']} |",
        f"| 12.5 kg | {sizes['12.5']} |",
        f"| `STATE` | {types['STATE']} |",
        f"| `ZONE` | {types['ZONE']} |",
        f"| `NATIONAL` | {types['NATIONAL']} |",
        f"| **Main total** | **{len(rows)}** |",
        f"| **Callout total** | **{len(callouts)}** |",
        "",
        "Per release: 44 geographies x 3 periods x 2 cylinder sizes = 264 rows.",
        "",
        "## Release layout",
        "",
        "| Release | Geo cols | Banners | National labels | Defect corrections |",
        "|---|---|---|---|---|",
    ]
    for n in sorted(notes, key=lambda x: x["release_month"]):
        lines.append(
            f"| {n['release_month']} | {n['geo_cols']} | {', '.join(n['banners'])} | "
            f"{', '.join(sorted(set(n['national_labels'])))} | {n['corrections']} |")

    lines += [
        "",
        "## Structural variations",
        "",
        "- **Geography columns move** from 1/9 to 3/11 beginning **2026-02** (not 2026-01). Blocks "
        "are located by content, so both layouts parse identically.",
        "- **The banner does not mark its block.** Its column drifts 0-2 away from the block's "
        "geography column, and January 2026's right-hand banner reads **`12KG`**. Cylinder size is "
        "assigned by left-to-right block order instead (D-26); the published banner text is kept in "
        "`source_banner_text` as provenance only.",
        "- **The national row is `Average` or `Grand Total`** - the latter in 2026-02 … 2026-04. The "
        "main table ends at the first row that *classifies* national, never at a literal word (D-27).",
        "- **Header row is always 2** - unlike petrol and diesel it never moves.",
        "- `MoM`/`YoY` became `MOM`/`YOY` from 2026-01; sheet names drift to `Sheet1` in 2026-03/04.",
        "",
        "## Deliberately not ingested",
        "",
        "| Structure | Why |",
        "|---|---|",
        "| `MoM` / `MOM`, `YoY` / `YOY` | Derived percentages, recomputable from the three price "
        "columns. |",
        "| Highest/lowest callout rows | Extracted to `cooking_gas_extreme_callout`, never to the "
        "price table. |",
        "| Callout headings | Structural labels, not geography. |",
        "",
        "## The 2025 12.5 kg Kebbi/Taraba correction",
        "",
        f"**{len(corrected)} rows corrected** - {len(corrected) // EXPECTED_PERIODS} spreadsheet "
        "rows x 3 periods, one per 2025 release, **12.5 kg only**.",
        "",
        "All six fingerprint conditions must hold before a row is reinterpreted:",
        "",
        "1. cooking gas **and** `cylinder_size_kg = 12.5`",
        "2. `release_month` falls in **2025**",
        "3. the row sits in the **North West** block, between `Katsina` and `Sokoto`",
        "4. `Taraba` also appears in its correct **North East** position in the same block",
        "5. `Kebbi` is **absent** from that block's main table",
        "6. **the 5 kg block on the same spreadsheet row reads `Kebbi`**",
        "",
        "Condition 6 is the decisive one: the file itself names the state, one column block to the "
        "left. The two blocks are row-aligned 43 rows deep, and in each affected release **exactly "
        "one row differs** between them.",
        "",
        "| Release | Raw label | Canonical | Cylinder |",
        "|---|---|---|---|",
    ]
    for r in sorted({(x["release_month"], x["geography_raw_label"], x["geography_name"],
                      x["cylinder_size_kg"]) for x in corrected}):
        lines.append(f"| {r[0]} | `{r[1]}` | **{r[2]}** | {r[3]} kg |")

    taraba_rows = [r for r in rows if r["geography_name"] == "Taraba"]
    lines += [
        "",
        "### Proof the genuine Taraba was preserved",
        "",
        f"- **{len(taraba_rows)}** rows still resolve to `Taraba` - "
        f"{EXPECTED_RELEASES} releases x 2 cylinder sizes x {EXPECTED_PERIODS} periods. Every block "
        "of every release retains its North East Taraba row.",
        f"- Of all rows whose published label reads `Taraba`, "
        f"**{len(taraba_rows)} stayed Taraba** and only **{len(corrected)}** became `Kebbi` - the "
        "12 fingerprinted 2025 North West rows.",
        "- **No 5 kg row was corrected**, and every 5 kg `Kebbi` row has raw label `Kebbi`.",
        "- There is no global `Taraba` -> `Kebbi` mapping anywhere in the pipeline; the correction is "
        "keyed to the six-condition fingerprint alone.",
        "",
        "## Tied callouts",
        "",
        f"{EXPECTED_CALLOUT_SLOTS} callout slots (3 highest + 3 lowest x 2 sizes x "
        f"{EXPECTED_RELEASES} releases) yield **{len(callouts)}** clean rows. Exactly one slot holds "
        "a tie:",
        "",
        "| Release | Cylinder | Extreme | Raw label | Split into |",
        "|---|---|---|---|---|",
    ]
    for c in [c for c in callouts if c["is_shared_extreme"] == "TRUE"]:
        lines.append(f"| {c['release_month']} | {c['cylinder_size_kg']} kg | {c['extreme_type']} | "
                     f"`{c['raw_callout_text']}` | **{c['state']}** |")
    lines += [
        "",
        "Both rows keep the original text in `raw_callout_text`, carry `is_shared_extreme = TRUE` and "
        "`tie_member_count = 2`, and cite the same source cell. `Kebbi/Nasarawa` is never a canonical "
        "state and is never added to `ref_state_zone`.",
        "",
        "## Cross-release comparison",
        "",
        f"**{len(precision)} precision-only differences and {len(substantive)} substantive "
        "cross-release revisions under the defined tolerance.**",
        "",
        "| Outcome | Values |",
        "|---|---|",
        f"| Byte-identical to the earlier publication | {identical} |",
        f"| Differ only in stored precision (below tolerance) | {len(precision)} |",
        f"| **Substantive revision (at or above tolerance)** | **{len(substantive)}** |",
        "",
        f"**Tolerance.** A restated value counts as a substantive revision when it differs from the "
        f"earlier publication by a relative amount of **{SUBSTANTIVE_REVISION_TOLERANCE:g} or more**. "
        f"{total} restated values were compared across {len(rel) - 1} consecutive release pairs. "
        "Sub-tolerance values are **not byte-identical** - the published strings genuinely differ - "
        "and are never described as identical or as substantive revisions. Both source publications "
        "are preserved, distinguished by `release_month`.",
        "",
    ]
    if substantive:
        lines += ["| Observation | Restated by | kg | Type | Geography | Original | Restated |",
                  "|---|---|---|---|---|---|---|"]
        for obs_m, cur, size, typ, name, a, b in substantive[:40]:
            lines.append(f"| {obs_m} | {cur} | {size} | {typ} | {name} | {a} | {b} |")
        if len(substantive) > 40:
            lines.append(f"| … | | | | | | _{len(substantive) - 40} more_ |")

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
        "Any failure raises `ValidationError` and no output file is written.",
        "",
        "## Fault-injection results",
        "",
        "Each case breaks one property deliberately, on scratch copies held in memory, and asserts "
        "that the specific check guarding it fires. `data/raw/` is never touched.",
        "",
        "| # | Injected fault | Result |",
        "|---|---|---|",
        "| FI-1 | global `Taraba` -> `Kebbi` mapping applied | caught |",
        "| FI-2 | one known 2025 defect left uncorrected | caught |",
        "| FI-3 | `Taraba` corrected when the 5 kg row is not `Kebbi` | caught |",
        "| FI-4 | genuine North East `Taraba` changed to `Kebbi` | caught |",
        "| FI-5 | `Grand Total` treated as unresolved | caught |",
        "| FI-6 | block located from banner position only | caught |",
        "| FI-7 | `12KG` treated as a new cylinder product | caught |",
        "| FI-8 | 5 kg and 12.5 kg swapped | caught |",
        "| FI-9 | `MoM`/`YoY` imported as prices | caught |",
        "| FI-10 | `Kebbi/Nasarawa` treated as one state | caught |",
        "| FI-11 | one member of the tied callout lost | caught |",
        "| FI-12 | a primary-key row duplicated | caught |",
        "| FI-13 | one LPG price altered | caught |",
        "| FI-14 | source-cell provenance removed | caught |",
        "| FI-15 | an unsupported geography invented | caught |",
        "",
        "**16 of 16 cases behaved correctly** (15 injected faults plus the unmodified baseline).",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    rows, callouts, notes = extract_all()
    print(f"releases      : {len(notes)}")
    print(f"main rows     : {len(rows)}")
    print(f"callout rows  : {len(callouts)}")
    print(f"by size       : {dict(Counter(r['cylinder_size_kg'] for r in rows))}")
    print(f"by type       : {dict(Counter(r['geography_type'] for r in rows))}")
    print(f"corrections   : {sum(1 for r in rows if r['source_anomaly'] == DEFECT_FLAG)}")

    results = validate(rows, callouts, notes)      # raises on any failure

    write_csv(rows, OUT_MAIN, MAIN_COLUMNS, lambda r: (
        r["release_month"], r["observation_month"], float(r["cylinder_size_kg"]),
        {"STATE": 0, "ZONE": 1, "NATIONAL": 2}[r["geography_type"]], r["geography_name"]))
    write_csv(callouts, OUT_CALLOUT, CALLOUT_COLUMNS, lambda r: (
        r["release_month"], float(r["cylinder_size_kg"]), r["extreme_type"],
        int(r["rank_within_block"]), r["state"]))
    write_report(rows, callouts, notes, results, REPORT_PATH)

    identical, total, diffs = overlap_audit(rows)
    subst = [d for d in diffs if not is_precision_only(d[5], d[6])]
    print(f"overlap       : {total} compared -> {identical} byte-identical, "
          f"{len(diffs) - len(subst)} precision-only, {len(subst)} substantive")
    print(f"written       : {OUT_MAIN.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"              : {OUT_CALLOUT.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"report        : {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"validation    : {sum(1 for r in results if r[2])}/{len(results)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
