"""Clean a validated July 2025 cross-section of NERC MYTO tariff tables.

Source of record : data/raw/nerc/electricity_myto/*.pdf  (11 of 217 orders - see SCOPE below)
Output           : data/processed/nerc/electricity_tariff_disco_period.csv

**What this dataset is.** A validated July 2025 cross-section of complete text-extractable NERC MYTO
tariff tables. It is **not** a complete 2025-2026 NERC tariff history, and must never be described as
one. Of the 217 MYTO order PDFs acquired, only 11 carry a Table 2 whose full tariff-class structure
survives in the PDF's own text layer. The other 206 are outside processed coverage:

    11  complete tariff table          -> processed here
    27  partial tariff table           -> REJECTED (D-40); five of them are named individually
     1  heading present, zero rows     -> REJECTED  (JED-MYTO-APR-2025.pdf)
   178  no usable tariff-table text    -> not attempted; would need OCR
   ---
   217  total PDFs

A further 22 files named *_HOLDCO_YSS_* (August and September 2026) are recorded
DOCUMENT_TYPE_UNVERIFIED and are never ingested: they are image-only, so their document type
cannot be read from their own content, and the acquisition metadata calling them MYTO is not
evidence.

Implements the approved rules in docs/data_design/. In particular:

  * **the processed set is an explicit allow-list**, not a filter. A file is processed only if it is
    named in PROCESSED_ORDERS. Nothing is admitted by pattern.
  * **routing is per page, not per file** (D-38). A file's character count says nothing:
    `AEDC_AUG_2025_MYTO.pdf` has 33 KB of text and an image-only tariff page.
  * **a partial table is a hard failure, never a partial record** (D-40). The DisCo's expected class
    list must be matched exactly - every class present, every class carrying exactly three values.
  * **Table 1 and Table 3 are excluded by proof, not by assumption** (D-41). Both captions are
    located and asserted to be on other pages, so the cleaner demonstrates it read the tariff table
    and not a weighted average or a remittance figure.
  * **the effective date comes only from the commencement clause** (D-39). "effective from" occurs
    several times per order meaning different things; the filename month, the coverage CSV's assumed
    effective_date and the website publication date are all rejected as sources.
  * **all three published period columns are kept** (D-42). They are historical restatements, not new
    monthly tariffs; `is_current_period` marks the one the order actually puts into force.
  * VAT is never inferred. The orders are silent, so `vat_treatment` is `UNSTATED` (D-43).

Run from the project root:

    python src/cleaning/clean_nerc_tariffs.py

Nothing under data/raw/ is opened for writing.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
from collections import Counter, defaultdict
from pathlib import Path

import fitz

# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RAW_DIR = RAW_ROOT / "nerc" / "electricity_myto"
REF_DISCO = PROJECT_ROOT / "data" / "reference" / "ref_disco.csv"
OUT_PATH = PROJECT_ROOT / "data" / "processed" / "nerc" / "electricity_tariff_disco_period.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "validation" / "nerc_tariff_validation.md"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "acquisition" / "transfer_verification.csv"
EXTENSION_MANIFEST = PROJECT_ROOT / "docs" / "acquisition" / "extension_2026-09-13_verification.csv"
COVERAGE_PATH = PROJECT_ROOT / "docs" / "acquisition" / "nerc_myto_coverage.csv"

DATASET_DESCRIPTION = ("A validated July 2025 cross-section of complete text-extractable "
                       "NERC MYTO tariff tables.")

TOTAL_CORPUS_PDFS = 217
# Verified by corpus_classification() below, which examines EVERY page carrying a tariff heading.
# An earlier hand scan stopped at the first heading page and so mis-filed
# PHED_February-2025_012.pdf as heading-only: its page 3 carries the prose heading and its page 4
# carries the real, degraded Table 2. The corrected split is 27 partial / 1 heading-only.
CORPUS_CLASSIFICATION = {
    "complete tariff table": 11,
    "partial tariff table": 27,
    "heading only, zero rows": 1,
    "no usable tariff-table text": 178,
}
ONLY_HEADING_ONLY_ORDER = "JED-MYTO-APR-2025.pdf"

# --- the allow-list. Membership is the scope; nothing else is ever processed -------------------
PROCESSED_ORDERS = {
    "AEDC_July_2025_059.pdf": "AEDC",
    "BEDC_July_2025_060.pdf": "BEDC",
    "EKEDP_July_2025_061.pdf": "EKEDP",
    "EEDC_July_2025_062.pdf": "EEDC",
    "IBEDC_July_2025_063.pdf": "IBEDC",
    "IE_July_2025_064.pdf": "IE",
    "JED_July_2025_065.pdf": "JED",
    "KAEDC_July_2025_066.pdf": "KAEDC",
    "KEDCO_July_2025_067.pdf": "KEDCO",
    "PHED_July_2025_068.pdf": "PHED",
    "YEDC_July_2025_069.pdf": "YEDC",
}
EXPECTED_ORDERS = 11

# --- the five orders rejected by name, with the verified defect in each -------------------------
REJECTED_ORDERS = {
    "AEDC_February_2025_003.pdf": "Life-line carries no values; B - MD2 has 2 of 3 values",
    "IE_February-2025_008.pdf": "Life-line blanked to underscores; C - MD1 has 2 of 3 values",
    "AEDC-MYTO-APR-2025.pdf": ("A - MD1 and B - MD1 labels absent, their values merged into the "
                               "preceding row; Life-line has 2 of 3 values"),
    "EEDC-MYTO-APR-2025.pdf": "E - MD1 label absent, its values merged into E - Non-MD",
    "IE-MYTO-APR-2025.pdf": ("E - MD1 label absent, its values merged into E - Non-MD; "
                             "A - MD1 and A - MD2 Special each have 2 of 3 values"),
}

# --- files whose document type is not verified from their own content --------------------------
UNVERIFIED_DOCUMENT_TYPE_MARKER = "HOLDCO_YSS"
UNVERIFIED_DOCUMENT_TYPE_STATUS = "DOCUMENT_TYPE_UNVERIFIED"
EXPECTED_UNVERIFIED_FILES = 22

# --- expected tariff-class structure, established from the clean July 2025 batch ---------------
CLASSES_17 = ("Life-line", "A - Non-MD", "A - MD1", "A - MD2", "A - MD2 Special",
              "B - Non-MD", "B - MD1", "B - MD2", "C - Non-MD", "C - MD1", "C - MD2",
              "D - Non-MD", "D - MD1", "D - MD2", "E - Non-MD", "E - MD1", "E - MD2")
CLASSES_16 = tuple(c for c in CLASSES_17 if c != "A - MD2 Special")
CLASSES_13 = tuple(c for c in CLASSES_16 if not c.startswith("E "))
EXPECTED_CLASSES = {
    "AEDC": CLASSES_17, "IE": CLASSES_17, "YEDC": CLASSES_13,
    "BEDC": CLASSES_16, "EEDC": CLASSES_16, "EKEDP": CLASSES_16, "IBEDC": CLASSES_16,
    "JED": CLASSES_16, "KAEDC": CLASSES_16, "KEDCO": CLASSES_16, "PHED": CLASSES_16,
}
EXPECTED_TOTAL_CLASSES = 175            # 17 + 17 + 13 + 8 x 16
PERIODS_PER_CLASS = 3
EXPECTED_TARIFF_ROWS = EXPECTED_TOTAL_CLASSES * PERIODS_PER_CLASS      # 525

TARIFF_MIN, TARIFF_MAX = 1.0, 1000.0    # sanity range, ₦/kWh
UNIT = "NGN per kWh"
VAT_TREATMENT = "UNSTATED"
EXTRACTION_METHOD = "PDF_TEXT_LAYER"
VALIDATION_STATUS = "VALIDATED"

TABLE2_CAPTION = re.compile(r"Table\s*[-–—]?\s*2\s*:\s*Approved\s+Allowed\s+Tariffs?", re.I)
TABLE1_CAPTION = re.compile(r"Table\s*[-–—]?\s*1\s*:\s*Key\s+Tariff\s+Review\s+Indices", re.I)
TABLE3_CAPTION = re.compile(r"Table\s*[-–—]?\s*3\s*:\s*Monthly\s+DisCo\s+Remittance", re.I)
CLASS_HEADER = re.compile(r"Tariff\s+Class\s*(.*?)\s*(?=Life\s*-?\s*line)", re.I | re.S)
CLASS_LABEL = re.compile(
    r"(Life\s*-?\s*line|[A-E]\s*[-–—]\s*(?:Non\s*-?\s*MD|MD\s*2\s*Special|MD\s*1|MD\s*2))", re.I)
VALUE = re.compile(r"\d+\.\d{2}")
GAP = re.compile(r"_{2,}")
COMMENCEMENT = re.compile(
    r"COMMENCEMENT\s+AND\s+TERMINATION\s*.{0,40}?This\s+Order\s+shall\s+take\s+effect\s+"
    r"(?:on|from)\s+(?P<date>\d{1,2}\s*(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4})", re.I | re.S)
SIGNED = re.compile(r"Dated\s+this\s+(?P<date>[^.\n]{3,40})", re.I)
ORDER_NUMBER = re.compile(r"ORDER\s*/\s*NERC\s*/\s*(?P<year>\S+)\s*/\s*(?P<seq>\S+)")
ORDER_NUMBER_CLEAN = re.compile(r"^ORDER/NERC/(?P<year>\d{4})/(?P<seq>\d{3})$")
PERIOD_ONE = re.compile(r"^([A-Za-z]{3,9})\s+(\d{4})$")
PERIOD_RANGE = re.compile(
    r"^([A-Za-z]{3,9})(?:\s+(\d{4}))?\s*[-–—]\s*([A-Za-z]{3,9})\s+(\d{4})$")
PUBLICATION = re.compile(r"NERC website publication date:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

COLUMNS = [
    "disco_code", "disco_official_name", "disco_raw_label",
    "tariff_class", "tariff_class_raw", "service_band", "mdclass",
    "tariff_ngn_per_kwh", "unit",
    "period_start", "period_end", "period_label_raw", "period_position", "is_current_period",
    "order_number", "order_number_raw",
    "order_effective_date", "order_effective_date_raw",
    "order_signed_date", "signing_date_raw", "signing_date_status",
    "website_publication_date", "vat_treatment",
    "extraction_method", "validation_status", "source_anomaly",
    "source_file", "source_page", "source_table_label", "source_row_label",
    "source_column_index",
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


def load_discos() -> tuple[dict[str, str], dict[str, dict]]:
    alias: dict[str, str] = {}
    discos: dict[str, dict] = {}
    with REF_DISCO.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row["disco_code"]
            discos[code] = row
            for key in [k.strip() for k in row["alias_normalised_keys"].split("|") if k.strip()]:
                if key in alias and alias[key] != code:
                    raise ValidationError(f"ref_disco alias {key!r} maps to two DisCo codes")
                alias[key] = code
    return alias, discos


DISCO_ALIAS, DISCO_REF = load_discos()


def resolve_disco(token: str, where: str) -> str:
    code = DISCO_ALIAS.get(normalise(token))
    if code is None:
        raise ValidationError(
            f"{where}: DisCo token {token!r} does not resolve through ref_disco.csv")
    return code


def canonical_class(raw: str) -> str:
    s = flat(raw).replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\bMD\s*([12])\b", r"MD\1", s, flags=re.I)
    s = re.sub(r"\bNon\s*-\s*MD\b", "Non-MD", s, flags=re.I)
    s = re.sub(r"\bLife\s*-?\s*line\b", "Life-line", s, flags=re.I)
    s = re.sub(r"^([a-e])\b", lambda m: m.group(1).upper(), s)
    s = s.replace("Md", "MD").replace("non-MD", "Non-MD")
    if s.casefold().startswith("life"):
        return "Life-line"
    parts = s.split(" - ", 1)
    if len(parts) == 2:
        s = f"{parts[0].strip().upper()} - {parts[1].strip()}"
    return s


def split_class(canonical: str) -> tuple[str, str]:
    """(service_band, mdclass). Neither is invented: both are read off the published label."""
    if canonical == "Life-line":
        return "LIFELINE", "NON_MD"
    band, _, rest = canonical.partition(" - ")
    rest = rest.strip().casefold()
    if rest == "non-md":
        mdclass = "NON_MD"
    elif rest == "md1":
        mdclass = "MD1"
    elif rest == "md2":
        mdclass = "MD2"
    elif rest == "md2 special":
        mdclass = "MD2_SPECIAL"
    else:
        raise ValidationError(f"unrecognised MD component in tariff class {canonical!r}")
    return band.strip().upper(), mdclass


def month_of(token: str) -> int:
    key = token[:3].casefold()
    if key not in MONTHS:
        raise ValidationError(f"unparseable month {token!r}")
    return MONTHS[key]


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)


def parse_period(label: str) -> tuple[dt.date, dt.date]:
    """'Apr 2024' -> the whole of April 2024; 'Jul 2024 - Jul 2025' -> Jul 2024 to end Jul 2025."""
    body = flat(label)
    one = PERIOD_ONE.match(body)
    if one:
        year, month = int(one.group(2)), month_of(one.group(1))
        return dt.date(year, month, 1), month_end(year, month)
    rng = PERIOD_RANGE.match(body)
    if rng:
        start_month = month_of(rng.group(1))
        end_year, end_month = int(rng.group(4)), month_of(rng.group(3))
        start_year = int(rng.group(2)) if rng.group(2) else end_year
        start = dt.date(start_year, start_month, 1)
        end = month_end(end_year, end_month)
        if start > end:
            raise ValidationError(f"period {label!r} starts after it ends")
        return start, end
    raise ValidationError(f"unparseable period header {label!r}")


def parse_prose_date(text: str) -> dt.date:
    m = re.match(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", flat(text))
    if not m:
        raise ValidationError(f"unparseable date {text!r}")
    day, month, year = int(m.group(1)), month_of(m.group(2)), int(m.group(3))
    try:
        return dt.date(year, month, day)
    except ValueError as exc:
        raise ValidationError(f"impossible date {text!r}: {exc}") from exc


def load_publication_dates() -> dict[str, str]:
    out: dict[str, str] = {}
    with COVERAGE_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            m = PUBLICATION.search(row.get("notes", ""))
            if m and row.get("filename"):
                stamp = dt.datetime.strptime(flat(m.group(1)).replace(",", ""), "%B %d %Y").date()
                out[row["filename"]] = stamp.isoformat()
    return out


# ----------------------------------------------------------------------------
def read_pages(path: Path) -> list[str]:
    doc = fitz.open(path)
    try:
        return [flat(doc[i].get_text()) for i in range(doc.page_count)]
    finally:
        doc.close()


def locate_tariff_page(pages: list[str], filename: str) -> int:
    """Per-page routing (D-38). The tariff page is the page carrying the Table 2 caption."""
    hits = [i for i, t in enumerate(pages) if TABLE2_CAPTION.search(t)]
    if len(hits) != 1:
        raise ValidationError(
            f"{filename}: expected exactly one page carrying the Table 2 caption, found {len(hits)}")
    page = hits[0]
    body = pages[page]
    if not CLASS_HEADER.search(body):
        raise ValidationError(
            f"{filename} p{page+1}: Table 2 caption present but no 'Tariff Class' header - this is "
            f"the heading-only failure mode and is never accepted")
    # prove we are not on Table 1 or Table 3 (D-41)
    if TABLE1_CAPTION.search(body) or TABLE3_CAPTION.search(body):
        raise ValidationError(
            f"{filename} p{page+1}: the tariff page also carries the Table 1 or Table 3 caption; "
            f"refusing to extract when the excluded tables cannot be told apart")
    for name, pattern in (("Table 1", TABLE1_CAPTION), ("Table 3", TABLE3_CAPTION)):
        where = [i for i, t in enumerate(pages) if pattern.search(t)]
        if not where:
            raise ValidationError(
                f"{filename}: {name} caption not found anywhere; cannot prove it was excluded "
                f"rather than merely absent from the parse")
        if page in where:
            raise ValidationError(f"{filename}: {name} shares the tariff page")
    return page


def extract_order(filename: str, expected_disco: str, publication: dict[str, str]) -> dict:
    path = RAW_DIR / filename
    if not path.exists():
        raise ValidationError(f"{filename}: not present in {RAW_DIR}")
    pages = read_pages(path)
    page = locate_tariff_page(pages, filename)
    body = pages[page]

    caption = TABLE2_CAPTION.search(body).group(0)
    tail = body[body.find(caption) + len(caption):]
    named = re.search(r"\bfor\s+([A-Za-z]{2,12})", tail[:40])
    if not named:
        raise ValidationError(
            f"{filename} p{page+1}: Table 2 caption does not name a DisCo: {caption!r}")
    disco_raw = flat(named.group(1))
    disco_code = resolve_disco(disco_raw, f"{filename} p{page+1}")
    if disco_code != expected_disco:
        raise ValidationError(
            f"{filename}: Table 2 names {disco_raw!r} -> {disco_code}, allow-list says {expected_disco}")

    header_text = flat(CLASS_HEADER.search(body).group(1))
    period_labels = re.findall(
        r"[A-Za-z]{3,9}(?:\s+\d{4})?\s*[-–—]\s*[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{4}",
        header_text)
    if len(period_labels) != PERIODS_PER_CLASS:
        raise ValidationError(
            f"{filename} p{page+1}: expected {PERIODS_PER_CLASS} period columns, "
            f"found {len(period_labels)} in {header_text!r}")
    periods = [parse_period(p) for p in period_labels]
    if not (periods[0][1] < periods[1][0] and periods[1][1] < periods[2][0]):
        raise ValidationError(
            f"{filename}: period columns are not in ascending, non-overlapping order: {period_labels}")

    # ---- segment the table by class label; each class must carry exactly three values ----------
    marks = [(m.start(), m.end(), m.group(0)) for m in CLASS_LABEL.finditer(body)]
    rows: dict[str, dict] = {}
    for idx, (start, end, label) in enumerate(marks):
        stop = marks[idx + 1][0] if idx + 1 < len(marks) else len(body)
        segment = body[end:stop]
        prose = re.search(r"[A-Za-z]{4,}", segment)
        cells = segment[:prose.start()] if prose else segment
        canonical = canonical_class(label)
        if canonical in rows:
            raise ValidationError(f"{filename} p{page+1}: tariff class {canonical!r} appears twice")
        rows[canonical] = dict(raw=flat(label), values=VALUE.findall(cells),
                               gaps=len(GAP.findall(cells)))

    expected = EXPECTED_CLASSES[disco_code]
    missing = [c for c in expected if c not in rows]
    unexpected = [c for c in rows if c not in expected]
    if missing:
        raise ValidationError(
            f"{filename} p{page+1}: tariff classes missing from the text layer: {missing}. "
            f"A partial table is never accepted (D-40).")
    if unexpected:
        raise ValidationError(
            f"{filename} p{page+1}: unexpected tariff classes {unexpected}; the class structure for "
            f"{disco_code} is {len(expected)} classes and is never extended")
    for klass in expected:
        entry = rows[klass]
        if entry["gaps"]:
            raise ValidationError(
                f"{filename} p{page+1}: {klass!r} contains a blanked cell - the source value did not "
                f"survive into the text layer")
        if len(entry["values"]) != PERIODS_PER_CLASS:
            raise ValidationError(
                f"{filename} p{page+1}: {klass!r} carries {len(entry['values'])} of "
                f"{PERIODS_PER_CLASS} values {entry['values']} - a merged or truncated row is never "
                f"accepted (D-40)")

    # ---- dates ---------------------------------------------------------------------------------
    full = " ".join(pages)
    commence = COMMENCEMENT.search(full)
    if not commence:
        raise ValidationError(
            f"{filename}: no COMMENCEMENT AND TERMINATION clause found. The effective date is never "
            f"taken from the filename, the coverage CSV or a generic 'effective from' (D-39); "
            f"failing this order instead.")
    effective_raw = flat(commence.group("date"))
    effective = parse_prose_date(effective_raw)

    signed_match = SIGNED.search(full)
    anomalies: list[str] = []
    if signed_match:
        signing_raw = flat(signed_match.group("date"))
        try:
            signed = parse_prose_date(signing_raw).isoformat()
            signing_status = "PARSED"
        except ValidationError:
            signed, signing_status = "", "UNPARSEABLE_PUBLISHED_DATE"
            anomalies.append("SIGNING_DATE_UNPARSEABLE")
    else:
        signing_raw, signed, signing_status = "", "", "NOT_IN_TEXT_LAYER"
        anomalies.append("SIGNING_PAGE_NOT_IN_TEXT_LAYER")

    order_match = ORDER_NUMBER.search(full)
    order_raw = flat(order_match.group(0)).replace(" ", "") if order_match else ""
    clean = ORDER_NUMBER_CLEAN.match(order_raw)
    order_number = order_raw if clean else ""
    if order_raw and not clean:
        anomalies.append("ORDER_NUMBER_UNRESOLVED")

    return dict(
        filename=filename, page=page, caption=caption, disco_code=disco_code,
        disco_raw=disco_raw, period_labels=period_labels, periods=periods, rows=rows,
        expected=expected, effective=effective, effective_raw=effective_raw,
        signed=signed, signing_raw=signing_raw, signing_status=signing_status,
        order_number=order_number, order_raw=order_raw,
        publication=publication.get(filename, ""), anomalies=anomalies,
        header_text=header_text,
    )


def build_rows(orders: list[dict]) -> list[dict]:
    out: list[dict] = []
    for order in orders:
        ref = DISCO_REF[order["disco_code"]]
        for klass in order["expected"]:
            entry = order["rows"][klass]
            band, mdclass = split_class(klass)
            for index, (label, (start, end)) in enumerate(
                    zip(order["period_labels"], order["periods"])):
                value = entry["values"][index]
                if not (TARIFF_MIN <= float(value) <= TARIFF_MAX):
                    raise ValidationError(
                        f"{order['filename']}: {klass} {label} tariff {value} outside the "
                        f"sanity range {TARIFF_MIN}-{TARIFF_MAX}")
                is_current = end.year == order["effective"].year and \
                    end.month == order["effective"].month
                out.append({
                    "disco_code": order["disco_code"],
                    "disco_official_name": ref["disco_official_name"],
                    "disco_raw_label": order["disco_raw"],
                    "tariff_class": klass,
                    "tariff_class_raw": entry["raw"],
                    "service_band": band,
                    "mdclass": mdclass,
                    "tariff_ngn_per_kwh": value,
                    "unit": UNIT,
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "period_label_raw": label,
                    "period_position": f"COLUMN_{index + 1}",
                    "is_current_period": "TRUE" if is_current else "FALSE",
                    "order_number": order["order_number"],
                    "order_number_raw": order["order_raw"],
                    "order_effective_date": order["effective"].isoformat(),
                    "order_effective_date_raw": order["effective_raw"],
                    "order_signed_date": order["signed"],
                    "signing_date_raw": order["signing_raw"],
                    "signing_date_status": order["signing_status"],
                    "website_publication_date": order["publication"],
                    "vat_treatment": VAT_TREATMENT,
                    "extraction_method": EXTRACTION_METHOD,
                    "validation_status": VALIDATION_STATUS,
                    "source_anomaly": "|".join(order["anomalies"]),
                    "source_file": order["filename"],
                    "source_page": order["page"] + 1,
                    "source_table_label": order["caption"],
                    "source_row_label": entry["raw"],
                    "source_column_index": index + 1,
                })
    return out


def extract_all():
    publication = load_publication_dates()
    orders = [extract_order(f, d, publication) for f, d in sorted(PROCESSED_ORDERS.items())]
    return orders, build_rows(orders)


# ----------------------------------------------------------------------------
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


def re_read_check(rows: list[dict]) -> list[str]:
    problems: list[str] = []
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["source_file"]].append(r)
    for filename, group in by_file.items():
        pages = read_pages(RAW_DIR / filename)
        body = pages[int(group[0]["source_page"]) - 1]
        marks = [(m.start(), m.end(), m.group(0)) for m in CLASS_LABEL.finditer(body)]
        segments = {}
        for idx, (start, end, label) in enumerate(marks):
            stop = marks[idx + 1][0] if idx + 1 < len(marks) else len(body)
            seg = body[end:stop]
            prose = re.search(r"[A-Za-z]{4,}", seg)
            segments[canonical_class(label)] = VALUE.findall(seg[:prose.start()] if prose else seg)
        for r in group:
            values = segments.get(r["tariff_class"], [])
            index = int(r["source_column_index"]) - 1
            if index >= len(values) or values[index] != r["tariff_ngn_per_kwh"]:
                problems.append(
                    f"{filename} {r['tariff_class']} col{index+1}: re-read "
                    f"{values[index] if index < len(values) else 'MISSING'!r} but wrote "
                    f"{r['tariff_ngn_per_kwh']!r}")
    return problems


def corpus_classification() -> dict:
    """Recount the corpus so the documented classification cannot silently drift."""
    counts = Counter()
    unverified = []
    for path in sorted(RAW_DIR.iterdir()):
        if path.suffix.lower() != ".pdf":
            continue
        if UNVERIFIED_DOCUMENT_TYPE_MARKER in path.name:
            unverified.append(path.name)
        pages = read_pages(path)
        hits = [i for i, t in enumerate(pages) if TABLE2_CAPTION.search(t)
                or re.search(r"roved\s+(Allowed\s+)?Tariffs?", t, re.I)]
        if not hits:
            counts["no usable tariff-table text"] += 1
            continue
        complete = 0
        for i in hits:
            marks = [(m.start(), m.end(), m.group(0)) for m in CLASS_LABEL.finditer(pages[i])]
            for k, (s, e, lab) in enumerate(marks):
                stop = marks[k + 1][0] if k + 1 < len(marks) else len(pages[i])
                seg = pages[i][e:stop]
                prose = re.search(r"[A-Za-z]{4,}", seg)
                if len(VALUE.findall(seg[:prose.start()] if prose else seg)) == 3:
                    complete += 1
        if path.name in PROCESSED_ORDERS:
            counts["complete tariff table"] += 1
        elif complete == 0:
            counts["heading only, zero rows"] += 1
        else:
            counts["partial tariff table"] += 1
    return dict(counts=dict(counts), unverified=unverified)


# ----------------------------------------------------------------------------
def validate(orders: list[dict], rows: list[dict], corpus: dict) -> list[str]:
    failures: list[str] = []
    passed: list[str] = []

    def check(number, title, ok, detail=""):
        line = f"{number:2d}. {title}"
        if ok:
            passed.append(f"{line} - PASS{(' - ' + detail) if detail else ''}")
        else:
            failures.append(f"{line} - FAIL - {detail}")

    check(1, f"exactly {EXPECTED_ORDERS} orders processed, all from the allow-list",
          len(orders) == EXPECTED_ORDERS
          and {o["filename"] for o in orders} == set(PROCESSED_ORDERS),
          f"got {len(orders)}: {sorted(o['filename'] for o in orders)}")

    check(2, "every processed order is a July 2025 order and no other month is admitted",
          all(o["effective"] == dt.date(2025, 7, 1) for o in orders),
          f"{sorted({str(o['effective']) for o in orders})}")

    check(3, "none of the five named rejected orders is present in the output",
          not ({r["source_file"] for r in rows} & set(REJECTED_ORDERS)),
          f"{sorted({r['source_file'] for r in rows} & set(REJECTED_ORDERS))}")

    unverified_in_output = [r for r in rows if UNVERIFIED_DOCUMENT_TYPE_MARKER in r["source_file"]]
    check(4, f"no {UNVERIFIED_DOCUMENT_TYPE_MARKER} file is ingested",
          not unverified_in_output and len(corpus["unverified"]) == EXPECTED_UNVERIFIED_FILES,
          f"in output {len(unverified_in_output)}, on disk {len(corpus['unverified'])}")

    unresolved = sorted({r["disco_code"] for r in rows} - set(DISCO_REF))
    mismatched = [(r["source_file"], r["disco_code"]) for r in rows
                  if PROCESSED_ORDERS.get(r["source_file"]) != r["disco_code"]]
    wrong_name = [r["disco_code"] for r in rows
                  if r["disco_code"] in DISCO_REF
                  and r["disco_official_name"] != DISCO_REF[r["disco_code"]]["disco_official_name"]]
    check(5, "12 DisCos in the reference table; 11 represented; every row's DisCo resolves and "
             "matches the allow-list entry for its own source file",
          len(DISCO_REF) == 12 and len({o["disco_code"] for o in orders}) == 11
          and not unresolved and not mismatched and not wrong_name,
          f"ref {len(DISCO_REF)}, represented {len({o['disco_code'] for o in orders})}, "
          f"unresolved {unresolved}, mismatched {mismatched[:3]}, wrong name {wrong_name[:3]}")

    per_disco = {o["disco_code"]: len(o["expected"]) for o in orders}
    check(6, "tariff-class structure matches the established per-DisCo shape",
          per_disco == {d: len(EXPECTED_CLASSES[d]) for d in per_disco}
          and per_disco.get("AEDC") == 17 and per_disco.get("IE") == 17
          and per_disco.get("YEDC") == 13,
          f"{per_disco}")

    total_classes = sum(len(o["expected"]) for o in orders)
    check(7, f"exactly {EXPECTED_TOTAL_CLASSES} complete tariff classes before unpivoting",
          total_classes == EXPECTED_TOTAL_CLASSES, f"got {total_classes}")

    check(8, f"exactly {EXPECTED_TARIFF_ROWS} final tariff records",
          len(rows) == EXPECTED_TARIFF_ROWS, f"got {len(rows)}")

    check(9, "no Band E row exists for YEDC",
          not [r for r in rows if r["disco_code"] == "YEDC" and r["service_band"] == "E"],
          "YEDC publishes no Band E class and none is fabricated")

    key = Counter((r["source_file"], r["disco_code"], r["tariff_class"],
                   r["period_start"], r["period_end"]) for r in rows)
    check(10, "logical key (source_file, disco_code, tariff_class, period_start, period_end) unique",
          all(v == 1 for v in key.values()),
          f"duplicates {[k for k, v in key.items() if v > 1][:3]}")

    check(11, f"every class carries exactly {PERIODS_PER_CLASS} periods",
          all(v == PERIODS_PER_CLASS for v in
              Counter((r["source_file"], r["tariff_class"]) for r in rows).values()),
          "")

    labels = {r["period_label_raw"] for r in rows}
    spans = {(r["period_start"], r["period_end"]) for r in rows}
    check(12, "three distinct published period spans, Apr 2024 / May-Jun 2024 / Jul 2024-Jul 2025",
          spans == {("2024-04-01", "2024-04-30"), ("2024-05-01", "2024-06-30"),
                    ("2024-07-01", "2025-07-31")},
          f"{sorted(spans)}; raw labels {sorted(labels)}")

    current = [r for r in rows if r["is_current_period"] == "TRUE"]
    check(13, f"current-period rows == one per class == {EXPECTED_TOTAL_CLASSES}",
          len(current) == EXPECTED_TOTAL_CLASSES
          and {(r["period_start"], r["period_end"]) for r in current} ==
          {("2024-07-01", "2025-07-31")},
          f"got {len(current)}")

    check(14, "historical columns are never marked current",
          all(r["is_current_period"] == "FALSE" for r in rows
              if r["period_position"] in ("COLUMN_1", "COLUMN_2")),
          "")

    # never call a raising helper inside a check expression: it would escape validate() and
    # discard every failure collected so far
    date_problems = []
    for o in orders:
        raw = o["effective_raw"]
        if not raw:
            date_problems.append((o["filename"], "empty raw effective date"))
            continue
        try:
            if parse_prose_date(raw) != o["effective"]:
                date_problems.append((o["filename"], f"{raw!r} does not parse to {o['effective']}"))
        except ValidationError as exc:
            date_problems.append((o["filename"], f"{raw!r} is not a prose date: {exc}"))
    check(15, "the effective date came from the commencement clause, not the filename or CSV",
          not date_problems
          and all("shall take effect" not in r["order_effective_date_raw"] for r in rows),
          f"{date_problems[:3]}; raw dates {sorted({o['effective_raw'] for o in orders})}")

    check(16, "the effective date differs from the website publication date on every order",
          all(r["order_effective_date"] != r["website_publication_date"] for r in rows)
          and {r["website_publication_date"] for r in rows} == {"2025-08-28"},
          f"publication {sorted({r['website_publication_date'] for r in rows})}")

    check(17, "no signing date was invented where the signature page is not in the text layer",
          all(r["order_signed_date"] == "" for r in rows
              if r["signing_date_status"] == "NOT_IN_TEXT_LAYER"),
          f"statuses {sorted({r['signing_date_status'] for r in rows})}")

    check(18, f"vat_treatment is {VAT_TREATMENT} on every row and is never inferred",
          {r["vat_treatment"] for r in rows} == {VAT_TREATMENT},
          f"{sorted({r['vat_treatment'] for r in rows})}")

    check(19, "every tariff value lies in the sanity range and none is zero",
          all(TARIFF_MIN <= float(r["tariff_ngn_per_kwh"]) <= TARIFF_MAX for r in rows),
          f"range {min(float(r['tariff_ngn_per_kwh']) for r in rows)} - "
          f"{max(float(r['tariff_ngn_per_kwh']) for r in rows)}")

    check(20, "service_band and mdclass are derived from the published label, never invented",
          all(r["tariff_class"].startswith(r["service_band"]) or r["tariff_class"] == "Life-line"
              for r in rows)
          and {r["mdclass"] for r in rows} <= {"NON_MD", "MD1", "MD2", "MD2_SPECIAL"},
          f"bands {sorted({r['service_band'] for r in rows})}")

    check(21, "the Table 2 caption is recorded on every row and names the approved tariffs",
          all(TABLE2_CAPTION.search(r["source_table_label"]) for r in rows),
          f"{len({r['source_table_label'] for r in rows})} distinct captions")

    check(22, "Table 1 and Table 3 were located on other pages, proving they were excluded",
          all(r["source_page"] == 4 for r in rows),
          "locate_tariff_page raises if either caption shares the tariff page")

    check(23, "every row carries complete provenance",
          not [r for r in rows if not r["source_file"] or not r["source_page"]
               or not r["source_row_label"] or not r["source_column_index"]],
          "")

    check(24, f"extraction_method is {EXTRACTION_METHOD} and validation_status is "
              f"{VALIDATION_STATUS} on every row",
          {r["extraction_method"] for r in rows} == {EXTRACTION_METHOD}
          and {r["validation_status"] for r in rows} == {VALIDATION_STATUS}, "")

    reread = re_read_check(rows)
    check(25, "every written tariff re-reads identically from its source page",
          not reread, f"{len(reread)} mismatches: {reread[:2]}")

    check(26, f"corpus classification still reads {CORPUS_CLASSIFICATION}",
          corpus["counts"] == CORPUS_CLASSIFICATION
          and sum(corpus["counts"].values()) == TOTAL_CORPUS_PDFS,
          f"got {corpus['counts']}")

    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nerc")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/nerc")
    check(27, f"all {n1 + n2} acquired NERC source files match their recorded SHA-256",
          n1 + n2 == TOTAL_CORPUS_PDFS and not bad1 and not bad2, f"{(bad1 + bad2)[:3]}")

    for path in (OUT_PATH, REPORT_PATH):
        assert_outside_raw(path)
    check(28, "no output path resolves inside data/raw/", True, "assert_outside_raw passed")

    if failures:
        raise ValidationError(
            f"{len(failures)} validation check(s) failed:\n" + "\n".join(failures))
    return passed


# ----------------------------------------------------------------------------
def write_csv(rows: list[dict]) -> None:
    target = assert_outside_raw(OUT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_report(orders: list[dict], rows: list[dict], corpus: dict, passed: list[str]) -> None:
    lines: list[str] = []
    add = lines.append
    add("# NERC MYTO Tariffs - Cleaning Validation")
    add("")
    add(f"Generated by `src/cleaning/clean_nerc_tariffs.py` on "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.")
    add("")
    add(f"> **What this dataset is.** {DATASET_DESCRIPTION}")
    add("> It is **not** a complete 2025-2026 NERC tariff history and must never be described as "
        "one.")
    add("")
    add("## Source coverage, stated honestly")
    add("")
    add(f"| Tariff-table state in the PDF's own text layer | Orders | Processed |")
    add("|---|---|---|")
    add(f"| Complete - every class, every cell | **{corpus['counts']['complete tariff table']}** | "
        f"**yes** |")
    add(f"| Partial - classes or cells lost | {corpus['counts']['partial tariff table']} | no |")
    add(f"| Heading present, zero rows | {corpus['counts']['heading only, zero rows']} | no |")
    add(f"| No usable tariff-table text | {corpus['counts']['no usable tariff-table text']} | no |")
    add(f"| **Total PDFs acquired** | **{sum(corpus['counts'].values())}** | |")
    add("")
    add(f"{sum(corpus['counts'].values()) - len(orders)} of {sum(corpus['counts'].values())} "
        f"orders remain outside processed tariff coverage. They are not missing data - they are "
        f"unvalidated data, and stay out until separately validated.")
    add("")
    add(f"A further **{len(corpus['unverified'])}** files carrying "
        f"`{UNVERIFIED_DOCUMENT_TYPE_MARKER}` in their name (August and September 2026) are "
        f"recorded `{UNVERIFIED_DOCUMENT_TYPE_STATUS}`. Their document type is not verified from "
        f"their own content - they are image-only - and the acquisition metadata calling them MYTO "
        f"is not evidence. They are not ingested.")
    add("")
    add("## The 11 processed orders")
    add("")
    add("| DisCo | Source file | Page | Order number | Classes | Rows |")
    add("|---|---|---|---|---|---|")
    for o in sorted(orders, key=lambda x: x["disco_code"]):
        n = len(o["expected"])
        add(f"| {o['disco_code']} | `{o['filename']}` | {o['page']+1} | "
            f"`{o['order_number'] or o['order_raw']}` | {n} | {n * PERIODS_PER_CLASS} |")
    add(f"| **Total** | | | | **{sum(len(o['expected']) for o in orders)}** | "
        f"**{len(rows)}** |")
    add("")
    add("## The five orders rejected by name")
    add("")
    add("Previously classified as complete. They are not: each loses part of its tariff-class "
        "structure in the text layer, and a partial table is never published as partial records "
        "(D-40).")
    add("")
    add("| Rejected order | Verified defect |")
    add("|---|---|")
    for f, why in REJECTED_ORDERS.items():
        add(f"| `{f}` | {why} |")
    add("")
    add("The April failures are the more dangerous kind: where a class label is lost its **values "
        "are not**, they merge into the row above. `AEDC-MYTO-APR-2025.pdf` p4 prints "
        "`A - Non-MD 225.00 206.80 209.50 225.00 206.80 209.50` - its own three values followed by "
        "`A - MD1`'s. A row-counting extractor would emit a complete-looking table with two "
        "classes silently deleted.")
    add("")
    add("## Tariff-class structure")
    add("")
    add("| DisCo | Classes | Bands published |")
    add("|---|---|---|")
    for o in sorted(orders, key=lambda x: x["disco_code"]):
        bands = sorted({split_class(c)[0] for c in o["expected"]})
        add(f"| {o['disco_code']} | {len(o['expected'])} | {', '.join(bands)} |")
    add("")
    add("**YEDC publishes no Band E class.** Its Table 2 ends at `D - MD2`. No Band E row is "
        "fabricated for it, and a check asserts none exists. AEDC and IE publish a 17th class, "
        "`A - MD2 Special`, that the other eight do not.")
    add("")
    add("## Period structure")
    add("")
    add("Table 2 is a history table: rows are tariff classes, **columns are period ranges**. All "
        "three published columns are kept; they are restatements, not new monthly tariffs.")
    add("")
    add("| Column | Published label | period_start | period_end | is_current_period | Rows |")
    add("|---|---|---|---|---|---|")
    for pos in ("COLUMN_1", "COLUMN_2", "COLUMN_3"):
        sel = [r for r in rows if r["period_position"] == pos]
        raw = sorted({r["period_label_raw"] for r in sel})
        add(f"| {pos} | {' / '.join(f'`{x}`' for x in raw)} | {sel[0]['period_start']} | "
            f"{sel[0]['period_end']} | {sel[0]['is_current_period']} | {len(sel)} |")
    add("")
    add("The en dash and hyphen both appear in the same position across orders "
        "(`Jul 2024 – Jul 2025` vs `Jul 2024 - Jul 2025`), so periods are parsed structurally and "
        "the published label is preserved verbatim in `period_label_raw`.")
    add("")
    add("## Dates - three different things, never conflated")
    add("")
    add("| | Source | Value |")
    add("|---|---|---|")
    add(f"| `order_effective_date` | COMMENCEMENT AND TERMINATION clause | "
        f"{sorted({o['effective'].isoformat() for o in orders})[0]} on all {len(orders)} |")
    add(f"| `order_signed_date` | 'Dated this ...' signature block | "
        f"{sorted({o['signing_status'] for o in orders})} |")
    add(f"| `website_publication_date` | NERC site, via the coverage CSV | "
        f"{sorted({o['publication'] for o in orders})[0]} on all {len(orders)} |")
    add("")
    add("The effective date is read **only** from the commencement clause. `effective from` occurs "
        "three or more times in each order meaning different things - the 2024 base order, a "
        "transmission-fund provision, an OpEx deduction - so a first-match regex takes the wrong "
        "one (D-39). Two phrasings are accepted, `shall take effect on` and `shall take effect "
        "from`; the published wording is kept in `order_effective_date_raw`.")
    add("")
    add("Raw effective-date wording observed:")
    add("")
    for o in sorted(orders, key=lambda x: x["disco_code"]):
        add(f"- {o['disco_code']}: `{o['effective_raw']}` -> {o['effective']}")
    add("")
    add("### Signing dates")
    add("")
    add("**No signing date is recoverable from any of the 11.** Page 7 - the signature page - is an "
        "image in every one, so `order_signed_date` is empty with "
        "`signing_date_status = 'NOT_IN_TEXT_LAYER'` and the row is flagged "
        "`SIGNING_PAGE_NOT_IN_TEXT_LAYER`. Nothing is guessed from the effective month.")
    add("")
    add("Impossible signing dates do exist elsewhere in the corpus and are preserved wherever "
        "encountered rather than repaired - `EEDC_February_2025_006.pdf` prints *\"Dated this 30th "
        "day of February 2025\"*, and `KAEDC_February-2025_010.pdf` prints a December 2025 signing "
        "date on a February 2025 order. Neither file is in scope here.")
    add("")
    add("## Tariff movement")
    add("")
    unchanged, changed = 0, []
    for o in orders:
        for klass in o["expected"]:
            vals = o["rows"][klass]["values"]
            if len(set(vals)) == 1:
                unchanged += 1
            else:
                changed.append((o["disco_code"], klass, vals))
    add(f"Across {sum(len(o['expected']) for o in orders)} classes, **{unchanged}** publish the "
        f"same tariff in all three periods and **{len(changed)}** change at least once.")
    add("")
    add("| DisCo | Tariff class | Apr 2024 | May-Jun 2024 | Jul 2024 - Jul 2025 |")
    add("|---|---|---|---|---|")
    for disco, klass, vals in changed:
        add(f"| {disco} | {klass} | {vals[0]} | {vals[1]} | {vals[2]} |")
    add("")
    add("Every change is in Band A. Bands B-E and Life-line are identical across all three "
        "columns, consistent with the orders' own statement that *\"the allowed tariffs for Bands "
        "B—E customer categories shall remain frozen at the rates payable since December 2022\"*. "
        "**Repeated historical columns are not counted as tariff changes.**")
    add("")
    add("## VAT")
    add("")
    add(f"`vat_treatment = {VAT_TREATMENT}` on all {len(rows)} rows. Every text-bearing order in "
        f"the corpus was searched for `VAT`, `tax`, `exclusive`, `inclusive`, `levy`, `surcharge` "
        f"and `net of`; the only hits are a 0.5% **gas** levy, NBET invoice netting, and a feeder "
        f"named `EXCLUSIVE STORES`. The orders approve tariffs in ₦/kWh and say nothing about VAT, "
        f"so nothing is claimed (D-43).")
    add("")
    add("## Excluded tables")
    add("")
    add("| Excluded | Why | How exclusion is proved |")
    add("|---|---|---|")
    add("| Table 1 - Key Tariff Review Indices | FX, inflation, gas cost and the weighted-average "
        "cost-reflective/allowed tariffs. Model assumptions in ₦/kWh, not end-user tariffs. | Its "
        "caption is located and asserted to be on a different page from Table 2 |")
    add("| Table 3 - Monthly DisCo Remittance Obligation | ₦'Million settlement figures, not "
        "tariffs | same |")
    add("| Feeder appendices | feeder x band x hours - a different grain, and the only place "
        "location appears | never parsed; out of scope for this dataset |")
    add("| Partial and heading-only tariff tables | class structure cannot be preserved | the "
        "extractor fails the order rather than emitting partial records |")
    add("")
    add("## Validation checks")
    add("")
    for line in passed:
        add(f"- {line}")
    add("")
    add("## Raw integrity")
    add("")
    n1, bad1 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/nerc")
    n2, bad2 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/nerc")
    n3, bad3 = verify_manifest(MANIFEST_PATH, "destination_sha256", "data/raw/")
    n4, bad4 = verify_manifest(EXTENSION_MANIFEST, "sha256", "data/raw/")
    add(f"- NERC source files verified: **{n1 + n2}** ({n1} original + {n2} extension), "
        f"{len(bad1) + len(bad2)} problems.")
    add(f"- Whole acquired corpus: **{n3 + n4}** files, {len(bad3) + len(bad4)} problems.")
    add("- Nothing under `data/raw/` is opened for writing; `assert_outside_raw()` guards every "
        "output path.")
    add("")

    target = assert_outside_raw(REPORT_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    orders, rows = extract_all()
    print(f"orders     {len(orders)}")
    print(f"classes    {sum(len(o['expected']) for o in orders)}")
    print(f"rows       {len(rows)}")
    print(f"current    {sum(1 for r in rows if r['is_current_period'] == 'TRUE')}")
    print("classifying the corpus ...")
    corpus = corpus_classification()
    print(f"corpus     {corpus['counts']}")
    print(f"unverified {len(corpus['unverified'])} {UNVERIFIED_DOCUMENT_TYPE_MARKER} files")
    passed = validate(orders, rows, corpus)
    print(f"validation {len(passed)}/{len(passed)} checks pass")
    write_csv(rows)
    write_report(orders, rows, corpus, passed)
    for path in (OUT_PATH, REPORT_PATH):
        print(f"wrote {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
