"""Clean the CBN NFEM daily exchange-rate dataset into `fx_nfem_daily`.

Source of record : data/raw/cbn/exchange_rate/cbn_api_GetAllNFEM_Rates_snapshot_*.json
Output           : data/processed/cbn/fx_nfem_daily.csv

Implements the approved rules in docs/data_design/. In particular:

  * the raw API JSON is authoritative; the extracted CSV in the same folder is a
    derivative and is never read here
  * every published record is kept - nothing is deleted. Redundancy is *labelled*
    via record_status (ACTIVE / EXACT_DUPLICATE / DATE_CONFLICT)
  * blank and zero are different facts and stay different
  * no value is rounded, reformatted or filled
  * no row is invented for a date CBN did not publish

Three properties are proved rather than assumed:

  * **raw integrity** - the source JSON is SHA-256 hashed before processing and again
    afterwards, and both must equal the digest recorded at acquisition time. Existence
    of the file proves nothing about its contents.
  * **the missing dates** - the exact set of absent weekdays is compared against a
    reference list, in both the raw snapshot and the clean output. A matching *count*
    would still pass if the pipeline lost one real date and invented another.
  * **row reconciliation** - the complete set of in-window raw `source_id` values is
    compared against the clean `source_id` values, in both directions. Checking that
    each clean id exists *somewhere* in the full snapshot is weaker: an out-of-window
    record would slip through.

Run from the project root:

    python src/cleaning/clean_cbn_nfem.py

Nothing under data/raw/ is opened for writing. Every output path is asserted to
resolve outside data/raw/ before a file handle is created.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

# ----------------------------------------------------------------------------
# Paths - all relative to the project root, never absolute machine paths.
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_DIR = RAW_ROOT / "cbn" / "exchange_rate"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "cbn" / "fx_nfem_daily.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "cbn_nfem_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
PROVENANCE_PATH = RAW_DIR / "PROVENANCE_READ_ME.txt"

WINDOW_START = dt.date(2025, 1, 1)
WINDOW_END = dt.date(2026, 9, 13)        # project cutoff, extended from 2026-05-31
SOURCE_DATE_FORMAT = "%B-%d-%Y"          # e.g. 'January-02-2025'

# The window covered by the original acquisition evidence. Everything up to this date
# has an independent, pre-agreed list of missing weekdays written at acquisition time;
# everything after it was derived from the snapshot when the window was extended.
# The distinction matters and is kept visible rather than blurred - see
# EXPECTED_MISSING_WEEKDAYS_ACQUISITION / _EXTENSION below.
ACQUISITION_WINDOW_END = dt.date(2026, 5, 31)

# Expected physical counts for this snapshot and window. These are regression guards,
# not independent evidence: they were derived from the snapshot on 2026-09-13 when the
# cutoff moved. The checks that genuinely prove reconciliation (17, 18, 19) compare raw
# and clean *sets* and do not depend on any of these numbers.
EXPECTED_IN_WINDOW_RECORDS = 425
EXPECTED_ACTIVE = 419
EXPECTED_EXACT_DUPLICATE = 6
EXPECTED_DATE_CONFLICT = 0

# raw JSON field -> clean column name, per docs/data_design/data_dictionary.csv
RATE_FIELDS = {
    "weightedAvgRate": "nfem_rate_ngn_per_usd",
    "highestrate": "highest_rate_ngn_per_usd",
    "lowestrate": "lowest_rate_ngn_per_usd",
    "closingrate": "closing_rate_ngn_per_usd",
    "simpleAvgRate": "simple_avg_rate_ngn_per_usd",
}
SPARSE_FIELDS = {
    "interBank_Total_Turnover": "interbank_turnover_usd",
    "noOfDeals_InterBank": "interbank_deal_count",
    "nfeM_Total_Turnover": "nfem_turnover_usd",
}
COUNT_FIELDS = {"noOfDeals": "nfem_deal_count"}

OUTPUT_COLUMNS = [
    "source_id",
    "observation_date",
    "source_date_label",
    "nfem_rate_ngn_per_usd",
    "highest_rate_ngn_per_usd",
    "lowest_rate_ngn_per_usd",
    "closing_rate_ngn_per_usd",
    "simple_avg_rate_ngn_per_usd",
    "interbank_turnover_usd",
    "interbank_deal_count",
    "nfem_turnover_usd",
    "nfem_deal_count",
    "record_status",
    "duplicate_of_source_id",
    "geography_type",
    "source_file",
]

# every field that carries analytical meaning - i.e. everything except CBN's row id
ANALYTICAL_RAW_FIELDS = (
    ["ratedate"] + list(RATE_FIELDS) + list(SPARSE_FIELDS) + list(COUNT_FIELDS)
)

# ----------------------------------------------------------------------------
# Weekdays inside the project window for which CBN published no observation.
#
# The list is deliberately split in two, because the two halves carry different
# evidential weight and collapsing them would overstate the second:
#
#   _ACQUISITION (22 dates, 2025-01-01 .. 2026-05-31)
#       Independent evidence. Frozen from the approved acquisition record,
#       data/raw/cbn/exchange_rate/PROVENANCE_READ_ME.txt, section "WEEKDAYS WITH NO
#       CBN OBSERVATION (22) - NOT FILLED, LISTED FOR LATER INVESTIGATION", written
#       before any cleaning happened. Check 12 re-proves the raw snapshot still
#       reproduces exactly these 22 inside that sub-window.
#
#   _EXTENSION (2 dates, 2026-06-01 .. 2026-09-13)
#       Derived from the snapshot itself on 2026-09-13, when the cutoff moved. There is
#       no prior approved list for this period, so these dates prove that the *cleaner*
#       neither filled nor lost a date relative to the raw source - they are NOT an
#       independent cross-check of the source, and are not claimed to be.
#
# Either way, asserting `len(gaps) == N` is not sufficient: a pipeline that dropped one
# genuine trading day and invented a row on a holiday would still report N gaps.
#
# No row is ever created for any of these dates. They are absent because CBN published
# nothing, and absence is the honest representation of that.
# ----------------------------------------------------------------------------
EXPECTED_MISSING_WEEKDAYS_ACQUISITION = (
    "2025-01-01",
    "2025-03-31",
    "2025-04-01",
    "2025-04-18",
    "2025-04-21",
    "2025-05-01",
    "2025-06-06",
    "2025-06-09",
    "2025-06-12",
    "2025-07-15",
    "2025-09-05",
    "2025-10-01",
    "2025-12-25",
    "2025-12-26",
    "2026-01-01",
    "2026-03-19",
    "2026-03-20",
    "2026-04-03",
    "2026-04-06",
    "2026-05-01",
    "2026-05-27",
    "2026-05-28",
)

# Derived from the snapshot when the cutoff moved to 2026-09-13. No official holiday
# calendar has been consulted; these are simply weekdays CBN did not publish.
EXPECTED_MISSING_WEEKDAYS_EXTENSION = (
    "2026-06-12",
    "2026-08-25",
)

EXPECTED_MISSING_WEEKDAYS = (
    EXPECTED_MISSING_WEEKDAYS_ACQUISITION + EXPECTED_MISSING_WEEKDAYS_EXTENSION
)


class ValidationError(AssertionError):
    """Raised when a validation check fails, so a broken run cannot ship a clean file."""


# ----------------------------------------------------------------------------
# Integrity
# ----------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes, read in chunks and never held whole in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquisition_digest(source_path: Path) -> str:
    """The SHA-256 recorded for this file when it was acquired and transferred.

    Comparing against this proves the snapshot is the same one that was profiled and
    approved, not merely that it was left alone during this particular run.
    """
    wanted = source_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    with MANIFEST_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            recorded = row["destination_path"].replace(chr(92), "/")
            if recorded == wanted:
                return row["destination_sha256"]
    raise ValidationError(
        f"{wanted} has no row in {MANIFEST_PATH.name}; its acquisition digest is unknown"
    )


def assert_outside_raw(path: Path) -> Path:
    """Refuse to open any output path that resolves inside data/raw/.

    A structural guarantee rather than a convention: the cleaner cannot write to the
    source of record even if a path constant is mistyped.
    """
    resolved = path.resolve()
    raw_root = RAW_ROOT.resolve()
    if resolved == raw_root or raw_root in resolved.parents:
        raise ValidationError(f"Refusing to write inside data/raw/: {resolved}")
    return resolved


# ----------------------------------------------------------------------------
# Load
# ----------------------------------------------------------------------------
def find_source() -> Path:
    """Locate the raw API snapshot. The derivative CSV is deliberately ignored."""
    matches = sorted(RAW_DIR.glob("cbn_api_GetAllNFEM_Rates_snapshot_*.json"))
    if not matches:
        raise FileNotFoundError(f"No raw CBN API snapshot found in {RAW_DIR}")
    return matches[-1]                    # newest snapshot if several exist


def load_raw(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        records = json.load(fh)
    if not isinstance(records, list) or not records:
        raise ValidationError(f"Raw snapshot {path.name} is not a non-empty JSON array")
    return records


# ----------------------------------------------------------------------------
# Field-level conversion
# ----------------------------------------------------------------------------
def parse_date(label: str) -> dt.date:
    """Parse CBN's own 'Month-DD-YYYY' text. Explicit format - never guessed."""
    return dt.datetime.strptime(label, SOURCE_DATE_FORMAT).date()


def to_number(value) -> str:
    """Convert a published numeric string to a number without changing its precision.

    Returns the canonical text of the number, which for CBN's values is byte-identical
    to what was published (trailing zeros and all). Decimal is used rather than float
    so that no binary rounding can occur.

    A blank or absent value returns "" - the CSV representation of NULL. It is never
    turned into 0, because a missing measurement and a measured zero are different facts.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValidationError(f"Value {value!r} is not a valid number") from exc
    canonical = format(number, "f")       # plain decimal, no exponent notation
    if canonical != text:
        # Guard: the cleaner must never silently alter a published figure.
        raise ValidationError(
            f"Numeric conversion changed the published text: {text!r} -> {canonical!r}"
        )
    return canonical


# ----------------------------------------------------------------------------
# Transform
# ----------------------------------------------------------------------------
def in_window(records: list[dict]) -> list[dict]:
    """The raw records CBN dated inside the project window. One definition, used by
    both the transform and the validator, so the two cannot drift apart."""
    return [r for r in records
            if WINDOW_START <= parse_date(r["ratedate"]) <= WINDOW_END]


def build_rows(records: list[dict], source_name: str) -> list[dict]:
    """Convert in-window raw records into clean rows. No row is added or dropped."""
    rows = []
    for record in in_window(records):
        observation_date = parse_date(record["ratedate"])
        row = {
            "source_id": int(record["id"]),
            "observation_date": observation_date.isoformat(),
            "source_date_label": record["ratedate"],
            "record_status": "",                 # assigned by classify_duplicates
            "duplicate_of_source_id": "",
            "geography_type": "NATIONAL",        # a single national market rate
            "source_file": source_name,
        }
        for raw_key, column in {**RATE_FIELDS, **SPARSE_FIELDS, **COUNT_FIELDS}.items():
            row[column] = to_number(record.get(raw_key))
        rows.append(row)
    return rows


def analytical_signature(record: dict) -> tuple:
    """Everything except CBN's internal id, used to decide exact-duplicate status."""
    return tuple(str(record.get(field)) for field in ANALYTICAL_RAW_FIELDS)


def classify_duplicates(rows: list[dict], records: list[dict]) -> None:
    """Label each row ACTIVE / EXACT_DUPLICATE / DATE_CONFLICT. Deletes nothing."""
    by_id = {int(r["id"]): r for r in records}
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_date[row["observation_date"]].append(row)

    conflicts = []
    for date_key, same_date in by_date.items():
        if len(same_date) == 1:
            same_date[0]["record_status"] = "ACTIVE"
            continue

        signatures = {analytical_signature(by_id[r["source_id"]]) for r in same_date}
        if len(signatures) == 1:
            # Identical in every analytical field: keep the lowest id, label the rest.
            same_date.sort(key=lambda r: r["source_id"])
            keeper, *redundant = same_date
            keeper["record_status"] = "ACTIVE"
            for row in redundant:
                row["record_status"] = "EXACT_DUPLICATE"
                row["duplicate_of_source_id"] = keeper["source_id"]
        else:
            # Values disagree. Neither record may be chosen automatically.
            for row in same_date:
                row["record_status"] = "DATE_CONFLICT"
            conflicts.append((date_key, [r["source_id"] for r in same_date]))

    if conflicts:
        raise ValidationError(
            "DATE_CONFLICT found - two records share a date but differ in value. "
            "These require human review and must not be resolved automatically: "
            + "; ".join(f"{d} ids={ids}" for d, ids in conflicts)
        )


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def weekday_gaps(present: set[dt.date]) -> list[dt.date]:
    """Weekdays inside the window that are absent from `present`, in date order."""
    gaps, day = [], WINDOW_START
    while day <= WINDOW_END:
        if day.weekday() < 5 and day not in present:
            gaps.append(day)
        day += dt.timedelta(days=1)
    return gaps


def clean_gaps(rows: list[dict]) -> list[dt.date]:
    return weekday_gaps({dt.date.fromisoformat(r["observation_date"]) for r in rows})


def raw_gaps(records: list[dict]) -> list[dt.date]:
    return weekday_gaps({parse_date(r["ratedate"]) for r in in_window(records)})


def describe_set_difference(actual: set, expected: set) -> str:
    """Human-readable diff of two sets, so a failure says *which* items are wrong."""
    unexpected = sorted(str(x) for x in actual - expected)
    absent = sorted(str(x) for x in expected - actual)
    parts = []
    if unexpected:
        parts.append(f"unexpected: {unexpected[:10]}")
    if absent:
        parts.append(f"expected but not found: {absent[:10]}")
    return "; ".join(parts)


def validate(
    rows: list[dict],
    records: list[dict],
    source_path: Path,
    digest_before: str,
    digest_after: str,
    digest_acquired: str,
) -> list[tuple]:
    """Run every approved check. Any failure raises; nothing is written on failure."""
    results, failures = [], []

    def check(number: int, label: str, ok: bool, detail: str = "") -> None:
        results.append((number, label, bool(ok), detail))
        if not ok:
            failures.append(f"{number}. {label} -> {detail}")

    window_records = in_window(records)
    status = Counter(r["record_status"] for r in rows)
    by_id = {int(r["id"]): r for r in records}

    # 1 is a regression guard against a constant; 2 is structural - the clean output
    # must hold exactly as many physical rows as the raw window, whatever that is.
    distinct_window_dates = len({parse_date(r["ratedate"]) for r in window_records})
    check(1, f"raw in-window physical records = {EXPECTED_IN_WINDOW_RECORDS}",
          len(window_records) == EXPECTED_IN_WINDOW_RECORDS,
          f"found {len(window_records)}")
    check(2, "clean physical records = raw in-window physical records",
          len(rows) == len(window_records),
          f"clean {len(rows)}, raw {len(window_records)}")

    ids = [r["source_id"] for r in rows]
    check(3, "source_id is unique", len(ids) == len(set(ids)),
          f"{len(ids)} rows, {len(set(ids))} distinct ids")

    # ACTIVE must equal the number of distinct in-window dates: exactly one ACTIVE row
    # per date CBN published. Everything else is labelled redundancy. Both halves are
    # asserted - the structural identity and the frozen count.
    check(4, f"ACTIVE = one row per distinct published date = {EXPECTED_ACTIVE}",
          status["ACTIVE"] == distinct_window_dates
          and status["ACTIVE"] == EXPECTED_ACTIVE,
          f"ACTIVE {status['ACTIVE']}, distinct raw dates {distinct_window_dates}, "
          f"expected {EXPECTED_ACTIVE}")
    check(5, f"EXACT_DUPLICATE = in-window records - distinct dates = "
             f"{EXPECTED_EXACT_DUPLICATE}",
          status["EXACT_DUPLICATE"] == len(window_records) - distinct_window_dates
          and status["EXACT_DUPLICATE"] == EXPECTED_EXACT_DUPLICATE,
          f"EXACT_DUPLICATE {status['EXACT_DUPLICATE']}, "
          f"records - dates {len(window_records) - distinct_window_dates}, "
          f"expected {EXPECTED_EXACT_DUPLICATE}")
    check(6, f"DATE_CONFLICT = {EXPECTED_DATE_CONFLICT}",
          status["DATE_CONFLICT"] == EXPECTED_DATE_CONFLICT,
          f"found {status['DATE_CONFLICT']}")

    active_dates = [r["observation_date"] for r in rows if r["record_status"] == "ACTIVE"]
    check(7, "ACTIVE observation_date values are unique",
          len(active_dates) == len(set(active_dates)),
          f"{len(active_dates)} active rows, {len(set(active_dates))} distinct dates")

    active_by_id = {r["source_id"]: r for r in rows if r["record_status"] == "ACTIVE"}
    bad_links = []
    for row in rows:
        if row["record_status"] != "EXACT_DUPLICATE":
            continue
        target = active_by_id.get(row["duplicate_of_source_id"])
        if target is None:
            bad_links.append(f"id {row['source_id']} points at a non-ACTIVE row")
        elif target["observation_date"] != row["observation_date"]:
            bad_links.append(f"id {row['source_id']} date mismatch")
        elif analytical_signature(by_id[row["source_id"]]) != \
                analytical_signature(by_id[target["source_id"]]):
            bad_links.append(f"id {row['source_id']} values differ from its ACTIVE row")
        elif row["duplicate_of_source_id"] >= row["source_id"]:
            bad_links.append(f"id {row['source_id']} does not point at the lower id")
    check(8, "each EXACT_DUPLICATE points to an ACTIVE row, same date, identical values",
          not bad_links,
          "; ".join(bad_links) or f"all {status['EXACT_DUPLICATE']} links verified")

    published_zero = sum(1 for r in window_records if str(r["noOfDeals"]).strip() == "0")
    clean_zero = sum(1 for r in rows if r["nfem_deal_count"] == "0")
    check(9, "published zero deal counts remain zero", published_zero == clean_zero,
          f"raw {published_zero}, clean {clean_zero}")

    raw_null_turnover = sum(1 for r in window_records
                            if r["interBank_Total_Turnover"] in (None, ""))
    clean_null_turnover = sum(1 for r in rows if r["interbank_turnover_usd"] == "")
    check(10, "missing turnover remains NULL, never zero",
          raw_null_turnover == clean_null_turnover
          and not any(r["interbank_turnover_usd"] == "0" for r in rows),
          f"raw {raw_null_turnover}, clean {clean_null_turnover}")

    # --- the missing dates, as an exact set -----------------------------------
    # 11 guards the reference list itself: a typo in EXPECTED_MISSING_WEEKDAYS would
    # otherwise silently become the thing that 12 and 13 are measured against.
    expected_acquired = {dt.date.fromisoformat(d)
                         for d in EXPECTED_MISSING_WEEKDAYS_ACQUISITION}
    expected_missing = {dt.date.fromisoformat(d) for d in EXPECTED_MISSING_WEEKDAYS}
    reference_faults = []
    if len(expected_missing) != len(EXPECTED_MISSING_WEEKDAYS):
        reference_faults.append("the list contains a duplicate date")
    outside = sorted(d for d in expected_missing
                     if not (WINDOW_START <= d <= WINDOW_END))
    if outside:
        reference_faults.append(f"outside the project window: {outside}")
    weekend = sorted(d for d in expected_missing if d.weekday() >= 5)
    if weekend:
        reference_faults.append(f"not a weekday: {weekend}")
    straddling = sorted(d for d in expected_acquired if d > ACQUISITION_WINDOW_END)
    if straddling:
        reference_faults.append(
            f"claimed as acquisition evidence but after {ACQUISITION_WINDOW_END}: "
            f"{straddling}")
    check(11, "the expected-missing-weekday reference list is sound "
              "(unique in-window weekdays, evidence and extension kept separate)",
          not reference_faults,
          "; ".join(reference_faults)
          or f"{len(expected_missing)} unique weekday dates "
             f"({len(expected_acquired)} from the acquisition evidence, "
             f"{len(expected_missing) - len(expected_acquired)} derived at extension), "
             f"all inside {WINDOW_START}..{WINDOW_END}")

    # 12 keeps the independent cross-check alive: inside the originally acquired
    # sub-window the raw snapshot must still reproduce exactly the 22 dates that
    # PROVENANCE_READ_ME.txt recorded before any cleaning was written.
    raw_missing_acquired = {d for d in raw_gaps(records)
                            if d <= ACQUISITION_WINDOW_END}
    check(12, f"raw weekday gaps up to {ACQUISITION_WINDOW_END} are exactly the "
             f"{len(expected_acquired)} dates in the acquisition evidence",
          raw_missing_acquired == expected_acquired,
          describe_set_difference(raw_missing_acquired, expected_acquired)
          or f"all {len(raw_missing_acquired)} dates match PROVENANCE_READ_ME.txt")

    raw_missing = set(raw_gaps(records))
    check(13, f"raw in-window weekday gaps are exactly the "
             f"{len(expected_missing)} expected dates",
          raw_missing == expected_missing,
          describe_set_difference(raw_missing, expected_missing)
          or f"all {len(raw_missing)} dates match the reference list")

    cleaned_missing = set(clean_gaps(rows))
    check(14, f"clean weekday gaps are exactly the same {len(expected_missing)} dates "
             f"- none filled, none newly lost",
          cleaned_missing == expected_missing,
          describe_set_difference(cleaned_missing, expected_missing)
          or f"all {len(cleaned_missing)} dates match the reference list")

    missing_core = [c for c in RATE_FIELDS.values()
                    if any(r[c] == "" for r in rows)]
    check(15, "core rate fields have no missing values", not missing_core,
          ", ".join(missing_core) or "all five complete")

    # Every clean row must trace back to a real raw record. A row whose source_id is
    # not in the snapshot was fabricated somewhere in the pipeline. This is checked
    # before the precision comparison, which would otherwise fail with an unhelpful
    # KeyError rather than a clear validation message.
    untraceable = sorted({r["source_id"] for r in rows} - set(by_id))
    check(16, "every clean row traces back to a raw source record", not untraceable,
          f"source_id not present in the raw snapshot: {untraceable[:5]}"
          if untraceable else f"all {len(rows)} rows traceable")

    # --- row reconciliation, as an exact set of source_id values ---------------
    # Membership in the *full* snapshot is too weak: an out-of-window record carried
    # into the output would satisfy it. These three compare against the in-window set.
    raw_window_ids = {int(r["id"]) for r in window_records}
    clean_ids = set(ids)
    lost = sorted(raw_window_ids - clean_ids)
    extra = sorted(clean_ids - raw_window_ids)
    repeated = sorted(i for i, n in Counter(ids).items() if n > 1)

    check(17, "no in-window raw source_id is missing from the clean output", not lost,
          f"{len(lost)} lost: {lost[:10]}" if lost
          else f"all {len(raw_window_ids)} in-window raw ids present")
    check(18, "the clean output contains no source_id outside the raw in-window set",
          not extra,
          f"{len(extra)} extra: {extra[:10]}" if extra
          else "no extra ids")
    check(19, "raw and clean in-window source_id sets are identical, "
              "one physical row each",
          raw_window_ids == clean_ids and not repeated
          and len(ids) == len(window_records),
          describe_set_difference(clean_ids, raw_window_ids)
          or (f"ids appearing more than once: {repeated[:10]}" if repeated else "")
          or f"{len(raw_window_ids)} raw = {len(clean_ids)} clean, "
             f"{len(ids)} physical rows")

    rounded = []
    for row in rows:
        raw = by_id.get(row["source_id"])
        if raw is None:
            continue                      # already reported by check 16
        for raw_key, column in {**RATE_FIELDS, **SPARSE_FIELDS, **COUNT_FIELDS}.items():
            original = "" if raw.get(raw_key) is None else str(raw[raw_key]).strip()
            if row[column] != original:
                rounded.append(f"id {row['source_id']} {column}: {original!r} -> {row[column]!r}")
    check(20, "no numeric value was rounded or reformatted", not rounded,
          "; ".join(rounded[:5]) or "all values byte-identical to the published text")

    # --- raw integrity, by content rather than by existence --------------------
    check(21, "raw JSON SHA-256 is identical before and after processing",
          digest_before == digest_after,
          f"before {digest_before}, after {digest_after}"
          if digest_before != digest_after
          else f"unchanged: {digest_after}")
    check(22, "raw JSON SHA-256 matches the digest recorded at acquisition",
          digest_after == digest_acquired,
          f"acquired {digest_acquired}, now {digest_after}"
          if digest_after != digest_acquired
          else f"matches {MANIFEST_PATH.name}")

    outputs_outside_raw = []
    for path in (OUT_PATH, REPORT_PATH):
        try:
            assert_outside_raw(path)
        except ValidationError as exc:
            outputs_outside_raw.append(str(exc))
    check(23, "every output path resolves outside data/raw/", not outputs_outside_raw,
          "; ".join(outputs_outside_raw)
          or "data/processed/cbn/ and docs/validation/ only")

    if failures:
        raise ValidationError(
            "CBN cleaning validation failed - no output written:\n  "
            + "\n  ".join(failures)
        )
    return results


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def write_csv(rows: list[dict], path: Path) -> None:
    path = assert_outside_raw(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r["observation_date"], r["source_id"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)


def write_report(rows, records, results, source_path, digests, path: Path) -> None:
    path = assert_outside_raw(path)
    status = Counter(r["record_status"] for r in rows)
    window_records = in_window(records)
    gaps = clean_gaps(rows)
    passed = sum(1 for r in results if r[2])

    raw_window_ids = {int(r["id"]) for r in window_records}
    clean_ids = {r["source_id"] for r in rows}

    lines = [
        "# CBN NFEM Exchange Rate - Cleaning Validation",
        "",
        f"Generated by `src/cleaning/clean_cbn_nfem.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "## Source",
        "",
        f"- **Source of record:** `data/raw/cbn/exchange_rate/{source_path.name}`",
        "- The extracted CSV in the same folder is a documented derivative and was **not** read.",
        "- The raw file was opened read-only. Nothing under `data/raw/` was modified.",
        "",
        "## Raw source integrity (SHA-256)",
        "",
        "Existence of the source file proves nothing about its contents, so the snapshot is "
        "hashed at three points in the run and compared against the digest recorded when the "
        "file was acquired.",
        "",
        "| Stage | SHA-256 |",
        "|---|---|",
        f"| Recorded at acquisition (`docs/acquisition/transfer_verification.csv`) "
        f"| `{digests['acquired']}` |",
        f"| Before processing | `{digests['before']}` |",
        f"| After processing | `{digests['after']}` |",
        f"| After writing outputs | `{digests['after_write']}` |",
        "",
        "All four are identical. In addition, every output path is asserted to resolve "
        "outside `data/raw/` before a file handle is opened, so the cleaner cannot write to "
        "the source of record even if a path constant were mistyped.",
        "",
        "## Counts",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Project window | {WINDOW_START} to {WINDOW_END} |",
        f"| Raw physical records in the snapshot | {len(records)} |",
        f"| Raw records before the window start (out of project scope) | "
        f"{sum(1 for r in records if parse_date(r['ratedate']) < WINDOW_START)} |",
        f"| Raw records after the cutoff | "
        f"{sum(1 for r in records if parse_date(r['ratedate']) > WINDOW_END)} |",
        f"| Raw records inside the project window | {len(window_records)} |",
        f"| Earliest observation in the clean table | "
        f"{min(r['observation_date'] for r in rows)} |",
        f"| Latest observation in the clean table | "
        f"{max(r['observation_date'] for r in rows)} |",
        f"| Clean physical rows written | {len(rows)} |",
        f"| `ACTIVE` (analytical rows) | {status['ACTIVE']} |",
        f"| `EXACT_DUPLICATE` | {status['EXACT_DUPLICATE']} |",
        f"| `DATE_CONFLICT` | {status['DATE_CONFLICT']} |",
        f"| Weekdays with no published observation | {len(gaps)} |",
        "",
        "Every published record is retained. The six redundant records are **labelled, not "
        "deleted**, so the clean table still reconciles row-for-row with the raw snapshot.",
        "",
        "## Row reconciliation by `source_id`",
        "",
        "The complete set of in-window raw `source_id` values is compared against the clean "
        "`source_id` values in both directions. Checking only that each clean id appears "
        f"*somewhere* in the full {len(records)}-record snapshot would be weaker - an "
        "out-of-window record carried into the output would still pass.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Distinct in-window raw `source_id` values | {len(raw_window_ids)} |",
        f"| Distinct clean `source_id` values | {len(clean_ids)} |",
        f"| In the raw window but absent from the clean output | "
        f"{len(raw_window_ids - clean_ids)} |",
        f"| In the clean output but not in the raw window | "
        f"{len(clean_ids - raw_window_ids)} |",
        f"| Clean `source_id` values appearing on more than one physical row | "
        f"{sum(1 for _, n in Counter(r['source_id'] for r in rows).items() if n > 1)} |",
        "",
        "The two sets are identical and each id occupies exactly one physical row, so the "
        f"clean table holds the same {len(rows)} physical source records as the raw "
        "snapshot's in-window slice - no loss, no addition, no duplication.",
        "",
        "## Missing-value treatment",
        "",
        "- A blank in the source stays **NULL** (an empty field in the CSV). It is never "
        "converted to zero.",
        "- A published `0` stays **numeric zero**. It is a measurement, not an absence.",
        f"- {sum(1 for r in rows if r['nfem_deal_count'] == '0')} rows carry a published zero "
        "deal count; "
        f"{sum(1 for r in rows if r['interbank_turnover_usd'] == '')} rows have no interbank "
        "turnover.",
        "",
        "## Missing-date treatment",
        "",
        f"- {len(gaps)} weekdays inside the window have no CBN observation.",
        "- **No rows were created for them.** No interpolation, no forward-fill, no zero rows.",
        "- Absence of a row means CBN published nothing for that date.",
        "",
        "Validation compares the **exact set** of absent weekdays - in the raw snapshot and "
        "again in the clean output - against a reference list. A matching count alone would "
        "still pass if the pipeline dropped one genuine trading day and invented a row on a "
        "holiday.",
        "",
        "The reference list is in two parts, because they are not equally strong evidence:",
        "",
        f"- **{len(EXPECTED_MISSING_WEEKDAYS_ACQUISITION)} dates up to "
        f"{ACQUISITION_WINDOW_END}** come from the approved acquisition record, "
        "`data/raw/cbn/exchange_rate/PROVENANCE_READ_ME.txt`, written before any cleaning "
        "existed. This is an independent cross-check of the source, and it is re-proved on "
        "every run.",
        f"- **{len(EXPECTED_MISSING_WEEKDAYS_EXTENSION)} dates after "
        f"{ACQUISITION_WINDOW_END}** were derived from the snapshot itself when the cutoff "
        "moved to 2026-09-13. There is no prior approved list for this period, so these "
        "prove the *cleaner* neither filled nor lost a date relative to the raw source - "
        "they are **not** an independent check of the source, and are not presented as one.",
        "",
        "| # | Absent weekday | Day | Evidence |",
        "|---|---|---|---|",
    ]
    for index, day in enumerate(gaps, start=1):
        origin = ("acquisition record" if day <= ACQUISITION_WINDOW_END
                  else "derived at extension")
        lines.append(
            f"| {index} | {day.isoformat()} | {day.strftime('%A')} | {origin} |")
    lines += [
        "",
        "These dates are expected to be Nigerian public holidays or non-trading days. That "
        "attribution is **not yet verified against an official holiday calendar** and no "
        "analysis depends on it - the rows are simply absent.",
        "",
        "## Precision",
        "",
        "Numbers are parsed with `Decimal`, never floating point, and written back in their "
        "published form. A guard raises if any conversion would alter the published text, so "
        "trailing zeros and full precision survive unchanged.",
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
        "Any failure raises `ValidationError` and no output file is written, so a broken "
        "pipeline cannot silently produce a clean dataset.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
def main() -> int:
    source_path = find_source()

    # Hash the source before a single byte is parsed, so the "before" digest cannot
    # have been influenced by anything this run did.
    digest_before = sha256_file(source_path)
    digest_acquired = acquisition_digest(source_path)

    records = load_raw(source_path)
    print(f"source        : {source_path.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"raw sha256    : {digest_before}")
    print(f"raw records   : {len(records)}")

    rows = build_rows(records, source_path.name)
    print(f"in-window rows: {len(rows)}")

    classify_duplicates(rows, records)
    status = Counter(r["record_status"] for r in rows)
    print(f"status        : {dict(status)}")

    digest_after = sha256_file(source_path)

    results = validate(rows, records, source_path,
                       digest_before, digest_after, digest_acquired)  # raises on failure

    write_csv(rows, OUT_PATH)

    # Writing the output must not have touched the source either. If it somehow did,
    # discard the file just written so a failed run leaves no clean dataset behind.
    digest_after_write = sha256_file(source_path)
    if digest_after_write != digest_before:
        OUT_PATH.unlink(missing_ok=True)
        raise ValidationError(
            "The raw snapshot changed while outputs were being written - "
            f"{digest_before} -> {digest_after_write}. Output discarded."
        )

    write_report(
        rows, records, results, source_path,
        {"acquired": digest_acquired, "before": digest_before,
         "after": digest_after, "after_write": digest_after_write},
        REPORT_PATH,
    )

    print(f"written       : {OUT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"report        : {REPORT_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print(f"raw sha256    : {digest_after_write} (unchanged)")
    print(f"validation    : {sum(1 for r in results if r[2])}/{len(results)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
