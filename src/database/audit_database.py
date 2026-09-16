"""Independent audit of the PostgreSQL analytical layer.

Deliberately standalone. It imports NEITHER the cleaning pipelines NOR the
loader's own modules: it discovers the CSV files itself, parses and hashes them
itself, and compares what it finds against what the database holds. Expected
figures are written out here as literals so that agreement between the CSVs,
the database and this file is three-way rather than circular.

    python src/database/audit_database.py

It does NOT take the loader's word for anything. In particular it re-derives
staging field text itself rather than trusting load_audit.field_text_match,
which the loader wrote.

Nothing under data/raw/ is opened.
"""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_NAME = os.environ.get("NBCI_DATABASE", "nigeria_business_cost")
PGHOST = os.environ.get("PGHOST", "localhost")
PGUSER = os.environ.get("PGUSER", "postgres")

# --- what the design says must be true -------------------------------------
EXPECTED_FILES = 17
EXPECTED_PROCESSED_FACT_FILES = 12
EXPECTED_REFERENCE_FILES = 5
EXPECTED_FACT_ROWS = 29_032
EXPECTED_REFERENCE_ROWS = 176

# columns the loader adds; everything else in a staging table is source text
STAGING_METADATA_COLUMNS = {"stg_line_number", "stg_load_id"}

FACTS = {
    "fact_fx_rate_daily": 425,
    "fact_petrol_price_monthly": 2040,
    "fact_diesel_price_monthly": 2244,
    "fact_lpg_price_monthly": 4224,
    "fact_lpg_extreme_callout": 193,
    "fact_transport_fare_state_monthly": 3230,
    "fact_transport_fare_zone_monthly": 1785,
    "fact_food_price_national_monthly": 2142,
    "fact_food_price_zone_monthly": 4284,
    "fact_food_extreme_callout": 1428,
    "fact_cpi_state_monthly": 6512,
    "fact_electricity_tariff": 525,
}

DIMENSIONS = {
    "dim_zone": 6, "dim_state": 37, "dim_state_alias": 39,
    "dim_state_alias_observed": 77, "dim_geography": 44, "dim_month": 31,
    "dim_food_item": 42, "dim_transport_mode": 5, "dim_cpi_measure": 3,
    "dim_disco": 12, "dim_nerc_order": 11, "dim_tariff_class": 17,
    "dim_tariff_period": 3, "dim_anomaly_flag": 14,
}

# CSV -> (staging table, file kind), discovered independently of the loader
CSV_TO_STAGING = {
    "data/processed/cbn/fx_nfem_daily.csv": ("stg_fx_nfem_daily", "PROCESSED_FACT"),
    "data/processed/nbs/petrol_price_monthly.csv": ("stg_petrol_price_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/diesel_price_monthly.csv": ("stg_diesel_price_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/cooking_gas_price_monthly.csv": ("stg_cooking_gas_price_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/cooking_gas_extreme_callout.csv": ("stg_cooking_gas_extreme_callout", "PROCESSED_FACT"),
    "data/processed/nbs/transport_fare_state_monthly.csv": ("stg_transport_fare_state_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/transport_fare_zone_monthly.csv": ("stg_transport_fare_zone_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/food_price_national_monthly.csv": ("stg_food_price_national_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/food_price_zone_monthly.csv": ("stg_food_price_zone_monthly", "PROCESSED_FACT"),
    "data/processed/nbs/food_price_extreme_callout.csv": ("stg_food_price_extreme_callout", "PROCESSED_FACT"),
    "data/processed/nbs/cpi_state_monthly.csv": ("stg_cpi_state_monthly", "PROCESSED_FACT"),
    "data/processed/nerc/electricity_tariff_disco_period.csv": ("stg_electricity_tariff_disco_period", "PROCESSED_FACT"),
    "data/reference/ref_state_zone.csv": ("stg_ref_state_zone", "REFERENCE"),
    "data/reference/ref_state_alias_observed.csv": ("stg_ref_state_alias_observed", "REFERENCE"),
    "data/reference/ref_transport_mode.csv": ("stg_ref_transport_mode", "REFERENCE"),
    "data/reference/ref_food_item.csv": ("stg_ref_food_item", "REFERENCE"),
    "data/reference/ref_disco.csv": ("stg_ref_disco", "REFERENCE"),
}

AVAILABLE_WINDOW = ("2025-01-01", "2026-04-01", 16)
PRIMARY_WINDOW = ("2025-02-01", "2026-04-01", 15)

# --- numeric round-trip coverage -------------------------------------------
# Every numeric/integer cast the fact loader performs, classified. A published
# economic measure is not the same kind of claim as a provenance row number,
# so they are reported separately rather than blended.
CELL = ("f.source_file = s.source_file "
        "AND coalesce(f.source_member,'') = coalesce(s.source_member,'') "
        "AND f.source_sheet = s.source_sheet "
        "AND f.source_cell_reference = s.source_cell_reference")

FROM_SQL = {
    "fact_fx_rate_daily":
        "FROM core.fact_fx_rate_daily f "
        "JOIN staging.stg_fx_nfem_daily s ON f.source_id::text = s.source_id",
    "fact_petrol_price_monthly":
        "FROM core.fact_petrol_price_monthly f "
        f"JOIN staging.stg_petrol_price_monthly s ON {CELL}",
    "fact_diesel_price_monthly":
        "FROM core.fact_diesel_price_monthly f "
        f"JOIN staging.stg_diesel_price_monthly s ON {CELL}",
    "fact_lpg_price_monthly":
        "FROM core.fact_lpg_price_monthly f "
        f"JOIN staging.stg_cooking_gas_price_monthly s ON {CELL}",
    # one cell yields two rows for the documented tie, so the state
    # disambiguates and the join stays one-to-one
    "fact_lpg_extreme_callout":
        "FROM core.fact_lpg_extreme_callout f "
        "JOIN core.dim_geography g ON g.geography_id = f.geography_id "
        f"JOIN staging.stg_cooking_gas_extreme_callout s ON {CELL} "
        "AND g.geography_name = s.state",
    "fact_transport_fare_state_monthly":
        "FROM core.fact_transport_fare_state_monthly f "
        f"JOIN staging.stg_transport_fare_state_monthly s ON {CELL}",
    "fact_transport_fare_zone_monthly":
        "FROM core.fact_transport_fare_zone_monthly f "
        f"JOIN staging.stg_transport_fare_zone_monthly s ON {CELL}",
    "fact_food_price_national_monthly":
        "FROM core.fact_food_price_national_monthly f "
        f"JOIN staging.stg_food_price_national_monthly s ON {CELL}",
    "fact_food_price_zone_monthly":
        "FROM core.fact_food_price_zone_monthly f "
        f"JOIN staging.stg_food_price_zone_monthly s ON {CELL}",
    "fact_food_extreme_callout":
        "FROM core.fact_food_extreme_callout f "
        f"JOIN staging.stg_food_price_extreme_callout s ON {CELL}",
    "fact_cpi_state_monthly":
        "FROM core.fact_cpi_state_monthly f "
        f"JOIN staging.stg_cpi_state_monthly s ON {CELL}",
    "fact_electricity_tariff":
        "FROM core.fact_electricity_tariff f "
        "JOIN core.dim_nerc_order o    ON o.order_id = f.order_id "
        "JOIN core.dim_tariff_class tc ON tc.tariff_class_id = f.tariff_class_id "
        "JOIN core.dim_tariff_period tp ON tp.tariff_period_id = f.tariff_period_id "
        "JOIN staging.stg_electricity_tariff_disco_period s "
        "  ON s.order_number = o.order_number AND s.tariff_class = tc.tariff_class "
        " AND s.period_position = tp.period_position",
}

# (fact, fact column, staging column, classification)
#   MEASURE   - a published economic value
#   COUNT     - a published count or ordinal
#   DIMENSION - a published numeric dimension attribute
#   METADATA  - provenance / identifier, not an economic measure
NUMERIC_COLUMNS = [
    ("fact_fx_rate_daily", "nfem_rate_ngn_per_usd", "nfem_rate_ngn_per_usd", "MEASURE"),
    ("fact_fx_rate_daily", "highest_rate_ngn_per_usd", "highest_rate_ngn_per_usd", "MEASURE"),
    ("fact_fx_rate_daily", "lowest_rate_ngn_per_usd", "lowest_rate_ngn_per_usd", "MEASURE"),
    ("fact_fx_rate_daily", "closing_rate_ngn_per_usd", "closing_rate_ngn_per_usd", "MEASURE"),
    ("fact_fx_rate_daily", "simple_avg_rate_ngn_per_usd", "simple_avg_rate_ngn_per_usd", "MEASURE"),
    ("fact_fx_rate_daily", "interbank_turnover_usd", "interbank_turnover_usd", "MEASURE"),
    ("fact_fx_rate_daily", "nfem_turnover_usd", "nfem_turnover_usd", "MEASURE"),
    ("fact_fx_rate_daily", "interbank_deal_count", "interbank_deal_count", "COUNT"),
    ("fact_fx_rate_daily", "nfem_deal_count", "nfem_deal_count", "COUNT"),
    ("fact_fx_rate_daily", "source_id", "source_id", "METADATA"),
    ("fact_fx_rate_daily", "duplicate_of_source_id", "duplicate_of_source_id", "METADATA"),

    ("fact_petrol_price_monthly", "price_ngn_per_litre", "price_ngn_per_litre", "MEASURE"),
    ("fact_petrol_price_monthly", "header_row_used", "header_row_used", "METADATA"),
    ("fact_petrol_price_monthly", "source_row", "source_row", "METADATA"),
    ("fact_petrol_price_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_diesel_price_monthly", "price_ngn_per_litre", "price_ngn_per_litre", "MEASURE"),
    ("fact_diesel_price_monthly", "header_row_used", "header_row_used", "METADATA"),
    ("fact_diesel_price_monthly", "source_row", "source_row", "METADATA"),
    ("fact_diesel_price_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_lpg_price_monthly", "refill_price_ngn", "refill_price_ngn", "MEASURE"),
    ("fact_lpg_price_monthly", "cylinder_size_kg", "cylinder_size_kg", "DIMENSION"),
    ("fact_lpg_price_monthly", "header_row_used", "header_row_used", "METADATA"),
    ("fact_lpg_price_monthly", "source_row", "source_row", "METADATA"),
    ("fact_lpg_price_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_lpg_extreme_callout", "price_ngn", "price_ngn", "MEASURE"),
    ("fact_lpg_extreme_callout", "cylinder_size_kg", "cylinder_size_kg", "DIMENSION"),
    ("fact_lpg_extreme_callout", "rank_within_block", "rank_within_block", "COUNT"),
    ("fact_lpg_extreme_callout", "tie_member_count", "tie_member_count", "COUNT"),
    ("fact_lpg_extreme_callout", "source_row", "source_row", "METADATA"),
    ("fact_lpg_extreme_callout", "source_column_index", "source_column_index", "METADATA"),

    ("fact_transport_fare_state_monthly", "fare_ngn", "fare_ngn", "MEASURE"),
    ("fact_transport_fare_state_monthly", "source_row", "source_row", "METADATA"),
    ("fact_transport_fare_state_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_transport_fare_zone_monthly", "fare_ngn", "fare_ngn", "MEASURE"),
    ("fact_transport_fare_zone_monthly", "source_row", "source_row", "METADATA"),
    ("fact_transport_fare_zone_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_food_price_national_monthly", "avg_price_ngn", "avg_price_ngn", "MEASURE"),
    ("fact_food_price_national_monthly", "header_row_used", "header_row_used", "METADATA"),
    ("fact_food_price_national_monthly", "source_row", "source_row", "METADATA"),
    ("fact_food_price_national_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_food_price_zone_monthly", "avg_price_ngn", "avg_price_ngn", "MEASURE"),
    ("fact_food_price_zone_monthly", "header_row_used", "header_row_used", "METADATA"),
    ("fact_food_price_zone_monthly", "source_row", "source_row", "METADATA"),
    ("fact_food_price_zone_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_food_extreme_callout", "price_ngn", "price_ngn", "MEASURE"),
    ("fact_food_extreme_callout", "header_row_used", "header_row_used", "METADATA"),
    ("fact_food_extreme_callout", "source_row", "source_row", "METADATA"),
    ("fact_food_extreme_callout", "source_column_index", "source_column_index", "METADATA"),

    ("fact_cpi_state_monthly", "value", "value", "MEASURE"),
    ("fact_cpi_state_monthly", "source_row", "source_row", "METADATA"),
    ("fact_cpi_state_monthly", "source_column_index", "source_column_index", "METADATA"),

    ("fact_electricity_tariff", "tariff_ngn_per_kwh", "tariff_ngn_per_kwh", "MEASURE"),
    ("fact_electricity_tariff", "source_column_index", "source_column_index", "METADATA"),
]

# bridged fact table -> its primary key column
BRIDGE_PK = {
    "fact_petrol_price_monthly": "petrol_id",
    "fact_diesel_price_monthly": "diesel_id",
    "fact_lpg_price_monthly": "lpg_id",
    "fact_transport_fare_state_monthly": "transport_state_id",
    "fact_transport_fare_zone_monthly": "transport_zone_id",
    "fact_food_price_national_monthly": "food_national_id",
    "fact_food_price_zone_monthly": "food_zone_id",
    "fact_food_extreme_callout": "food_callout_id",
    "fact_cpi_state_monthly": "cpi_id",
    "fact_electricity_tariff": "tariff_id",
}
# the nine whose source_anomaly lives on the fact itself (NERC's is on the order)
BRIDGE_SYMMETRIC = [t for t in BRIDGE_PK if t != "fact_electricity_tariff"]

passed = 0
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    else:
        failures.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  [{detail}]")


def section(title: str) -> None:
    print(f"\n--- {title} ---")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_csv_fields(path: Path) -> tuple[list[str], list[list[str]]]:
    """Parse the CSV independently and keep every field as text."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, [row for row in reader]


def scalar(cur, sql: str, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    print(f"Independent database audit - {DB_NAME}")
    print("Imports no cleaning code and no loader module.")
    print("Staging field text is re-derived here, not taken from load_audit.")

    with psycopg.connect(host=PGHOST, user=PGUSER, dbname=DB_NAME) as conn, conn.cursor() as cur:
        version = scalar(cur, "SELECT version()")
        print(f"\n{version.split(',')[0]}")

        # ==============================================================
        # 1. LOAD-RUN COHERENCE - one run, not a per-file patchwork
        # ==============================================================
        section("1. Load-run coherence (a single complete run)")
        cur.execute("""
            SELECT load_run_id,
                   count(*)                                             AS rows,
                   count(DISTINCT source_path)                          AS files,
                   count(*) FILTER (WHERE file_kind='PROCESSED_FACT')   AS facts,
                   count(*) FILTER (WHERE file_kind='REFERENCE')        AS refs,
                   sum(csv_row_count) FILTER (WHERE file_kind='PROCESSED_FACT') AS fact_rows,
                   sum(csv_row_count) FILTER (WHERE file_kind='REFERENCE')      AS ref_rows,
                   bool_and(field_text_match)                           AS loader_ftm
            FROM staging.load_audit
            GROUP BY load_run_id
            ORDER BY max(load_id) DESC
            LIMIT 1""")
        run = cur.fetchone()
        if run is None:
            check("a load run exists", False, "load_audit is empty")
            return 1
        run_id, n_rows, n_files, n_facts, n_refs, fact_rows, ref_rows, loader_ftm = run
        print(f"        run_id = {run_id}")
        check("the newest run has exactly 17 audit rows", n_rows == EXPECTED_FILES, str(n_rows))
        check("the newest run has exactly 17 distinct source files",
              n_files == EXPECTED_FILES, str(n_files))
        check("12 PROCESSED_FACT files in that one run",
              n_facts == EXPECTED_PROCESSED_FACT_FILES, str(n_facts))
        check("5 REFERENCE files in that one run",
              n_refs == EXPECTED_REFERENCE_FILES, str(n_refs))
        check("that run's fact CSV rows total 29,032",
              fact_rows == EXPECTED_FACT_ROWS, f"{fact_rows:,}")
        check("that run's reference CSV rows total 176",
              ref_rows == EXPECTED_REFERENCE_ROWS, str(ref_rows))
        check("the audited file set equals the run's file set",
              scalar(cur, """SELECT count(*) FROM staging.load_audit
                             WHERE load_run_id = %s AND source_path <> ALL(%s)""",
                     (run_id, list(CSV_TO_STAGING))) == 0)

        # every staging row must belong to this run - no leftovers from an older load
        stray_total = 0
        for rel, (table, _) in CSV_TO_STAGING.items():
            stray = scalar(cur, f"""SELECT count(*) FROM staging.{table} t
                                    WHERE NOT EXISTS (
                                      SELECT 1 FROM staging.load_audit la
                                      WHERE la.load_id = t.stg_load_id
                                        AND la.load_run_id = %s)""", (run_id,))
            stray_total += stray
        check("every staging row belongs to that one run", stray_total == 0,
              f"{stray_total} stray rows")

        # ==============================================================
        # 2. INDEPENDENT FIELD-TEXT VERIFICATION (the auditor's own proof)
        # ==============================================================
        section("2. Staging field text re-derived independently from the CSVs")
        total_fields = 0
        for rel, (table, kind) in CSV_TO_STAGING.items():
            path = PROJECT_ROOT / rel
            header, csv_rows = read_csv_fields(path)

            # the staging table's source columns must be exactly the CSV header
            cur.execute("""SELECT a.attname FROM pg_attribute a
                           JOIN pg_class c ON c.oid = a.attrelid
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname='staging' AND c.relname=%s
                             AND a.attnum > 0 AND NOT a.attisdropped
                           ORDER BY a.attnum""", (table,))
            db_cols = [r[0] for r in cur.fetchall()]
            source_cols = [c for c in db_cols if c not in STAGING_METADATA_COLUMNS]
            if source_cols != header:
                check(f"{table} column set", False,
                      f"csv={len(header)} db={len(source_cols)} first diff="
                      f"{next((i for i, (a, b) in enumerate(zip(header, source_cols)) if a != b), None)}")
                continue

            collist = ", ".join(f'"{c}"' for c in header)
            cur.execute(f"SELECT {collist} FROM staging.{table} ORDER BY stg_line_number")
            db_rows = cur.fetchall()

            mismatches = 0
            first_bad = None
            nulls = 0
            if len(db_rows) != len(csv_rows):
                mismatches = abs(len(db_rows) - len(csv_rows))
                first_bad = f"row count csv={len(csv_rows)} db={len(db_rows)}"
            else:
                for line, (csv_row, db_row) in enumerate(zip(csv_rows, db_rows), start=1):
                    for col, want, got in zip(header, csv_row, db_row):
                        if got is None:
                            nulls += 1
                        if want != ("" if got is None else got):
                            mismatches += 1
                            if first_bad is None:
                                first_bad = (f"line {line} col {col}: "
                                             f"csv={want!r} db={got!r}")
                    total_fields += len(header)
            check(f"{table} field text", mismatches == 0 and nulls == 0,
                  f"{len(csv_rows):,} rows x {len(header)} cols"
                  + (f", {mismatches} mismatches: {first_bad}" if mismatches else "")
                  + (f", {nulls} unexpected SQL NULLs" if nulls else ""))
        check("every source field compared", total_fields > 0, f"{total_fields:,} fields")

        # secondary reconciliation only - NOT the proof
        check("(secondary) loader also recorded field_text_match = true for all 17",
              loader_ftm is True, str(loader_ftm))

        # ==============================================================
        # 3. FILE BYTES AND ROW COUNTS, scoped to that run
        # ==============================================================
        section("3. SHA-256 file integrity and row counts (same run)")
        for rel, (table, kind) in CSV_TO_STAGING.items():
            path = PROJECT_ROOT / rel
            _, csv_rows = read_csv_fields(path)
            digest = sha256_file(path)
            cur.execute("""SELECT file_sha256, csv_row_count, loaded_row_count, file_kind
                           FROM staging.load_audit
                           WHERE load_run_id = %s AND source_path = %s""", (run_id, rel))
            rec = cur.fetchone()
            db_rows = scalar(cur, f"SELECT count(*) FROM staging.{table}")
            ok = (rec is not None and rec[0] == digest and rec[1] == len(csv_rows)
                  and rec[2] == db_rows == len(csv_rows) and rec[3] == kind)
            check(f"{table}", ok,
                  f"rows={len(csv_rows):,} hash={'match' if rec and rec[0] == digest else 'MISMATCH'}"
                  f" kind={rec[3] if rec else '?'}")

        # ==============================================================
        # 4. FACTS
        # ==============================================================
        section("4. Fact tables")
        total = 0
        for table, want in FACTS.items():
            got = scalar(cur, f"SELECT count(*) FROM core.{table}")
            total += got
            check(f"core.{table}", got == want, f"{got:,}")
        check("TOTAL FACT ROWS", total == EXPECTED_FACT_ROWS, f"{total:,}")

        # ==============================================================
        # 5. DIMENSIONS
        # ==============================================================
        section("5. Dimensions")
        dim_total = 0
        for table, want in DIMENSIONS.items():
            got = scalar(cur, f"SELECT count(*) FROM core.{table}")
            dim_total += got
            check(f"core.{table}", got == want, f"{got}")
        check("dimension total", dim_total == sum(DIMENSIONS.values()), f"{dim_total}")

        # ==============================================================
        # 6. REFERENTIAL INTEGRITY
        # ==============================================================
        section("6. Referential integrity")
        fk_count = scalar(cur, """SELECT count(*) FROM pg_constraint c
                                  JOIN pg_namespace n ON n.oid=c.connamespace
                                  WHERE c.contype='f' AND n.nspname='core'""")
        unvalidated = scalar(cur, """SELECT count(*) FROM pg_constraint c
                                     JOIN pg_namespace n ON n.oid=c.connamespace
                                     WHERE c.contype='f' AND n.nspname='core'
                                       AND NOT c.convalidated""")
        check("foreign keys present", fk_count > 0, f"{fk_count} FKs")
        check("zero orphans (all FKs validated)", unvalidated == 0,
              f"{unvalidated} unvalidated")

        # ==============================================================
        # 7. CONSTRAINTS
        # ==============================================================
        section("7. Constraints")
        checks = scalar(cur, """SELECT count(*) FROM pg_constraint c
                                JOIN pg_namespace n ON n.oid=c.connamespace
                                WHERE c.contype='c' AND n.nspname='core'""")
        uniques = scalar(cur, """SELECT count(*) FROM pg_constraint c
                                 JOIN pg_namespace n ON n.oid=c.connamespace
                                 WHERE c.contype='u' AND n.nspname='core'""")
        bad_checks = scalar(cur, """SELECT count(*) FROM pg_constraint c
                                    JOIN pg_namespace n ON n.oid=c.connamespace
                                    WHERE c.contype='c' AND n.nspname='core'
                                      AND NOT c.convalidated""")
        check("CHECK constraints validated", bad_checks == 0, f"{checks} checks")
        check("UNIQUE constraints present", uniques >= 12, f"{uniques} uniques")
        check("one current tariff period per order+class",
              scalar(cur, """SELECT count(*) FROM (
                               SELECT order_id, tariff_class_id FROM core.fact_electricity_tariff
                               WHERE is_current_period
                               GROUP BY 1,2 HAVING count(*) > 1) x""") == 0)
        check("one ACTIVE FX row per date",
              scalar(cur, """SELECT count(*) FROM (
                               SELECT observation_date FROM core.fact_fx_rate_daily
                               WHERE record_status='ACTIVE'
                               GROUP BY 1 HAVING count(*) > 1) x""") == 0)

        # ==============================================================
        # 8. NUMERIC ROUND-TRIP - every cast, classified
        # ==============================================================
        section("8. Numeric round-trip: every numeric cast from staging to core")
        by_kind: dict[str, list[int]] = {}
        text_identical = 0
        for fact, fcol, scol, kind in NUMERIC_COLUMNS:
            frm = FROM_SQL[fact]
            cur.execute(f"""
                SELECT count(*),
                       count(*) FILTER (
                         WHERE f.{fcol}::numeric IS DISTINCT FROM nullif(s."{scol}",'')::numeric),
                       count(*) FILTER (
                         WHERE coalesce(f.{fcol}::text,'')
                               IS DISTINCT FROM coalesce(nullif(s."{scol}",'')::numeric::text,''))
                {frm}""")
            compared, semantic_bad, text_bad = cur.fetchone()
            expected = FACTS[fact]
            by_kind.setdefault(kind, [0, 0, 0])
            by_kind[kind][0] += 1
            by_kind[kind][1] += compared
            by_kind[kind][2] += semantic_bad
            if text_bad == 0:
                text_identical += 1
            check(f"[{kind:<9}] {fact}.{fcol}",
                  semantic_bad == 0 and compared == expected,
                  f"compared={compared:,}/{expected:,} semantic_bad={semantic_bad} "
                  f"text_bad={text_bad}")
        print()
        for kind in ("MEASURE", "COUNT", "DIMENSION", "METADATA"):
            if kind in by_kind:
                cols, comp, bad = by_kind[kind]
                print(f"        {kind:<10} {cols:>2} columns, {comp:>7,} values compared, "
                      f"{bad} mismatches")
        check("ALL PUBLISHED MEASURES round-trip (semantic equality)",
              by_kind.get("MEASURE", [0, 0, 0])[2] == 0,
              f"{by_kind.get('MEASURE', [0, 0, 0])[1]:,} measure values")
        check("published COUNT and DIMENSION values round-trip",
              by_kind.get("COUNT", [0, 0, 0])[2] == 0
              and by_kind.get("DIMENSION", [0, 0, 0])[2] == 0)
        check("provenance METADATA integers round-trip",
              by_kind.get("METADATA", [0, 0, 0])[2] == 0)
        check("(stronger) every numeric column is also TEXT-identical to staging",
              text_identical == len(NUMERIC_COLUMNS),
              f"{text_identical}/{len(NUMERIC_COLUMNS)} columns")

        # ==============================================================
        # 9. GEOGRAPHY ASSERTIONS DDL CANNOT EXPRESS
        # ==============================================================
        section("9. Geography-type assertions (not expressible as table CHECKs)")
        for fact, want_type in (("fact_cpi_state_monthly", "STATE"),
                                ("fact_food_extreme_callout", "STATE"),
                                ("fact_lpg_extreme_callout", "STATE"),
                                ("fact_food_price_zone_monthly", "ZONE"),
                                ("fact_food_price_national_monthly", "NATIONAL"),
                                ("fact_fx_rate_daily", "NATIONAL")):
            n = scalar(cur, f"""SELECT count(*) FROM core.{fact} f
                                JOIN core.dim_geography g USING (geography_id)
                                WHERE g.geography_type <> %s""", (want_type,))
            check(f"{fact} is {want_type}-only", n == 0, f"{n} offending rows")
        check("dim_geography = 37 STATE + 6 ZONE + 1 NATIONAL",
              scalar(cur, """SELECT count(*) FILTER (WHERE geography_type='STATE')  = 37
                              AND count(*) FILTER (WHERE geography_type='ZONE')     = 6
                              AND count(*) FILTER (WHERE geography_type='NATIONAL') = 1
                             FROM core.dim_geography"""))
        check("every state's zone agrees with ref_state_zone",
              scalar(cur, """SELECT count(*) FROM core.dim_geography g
                             JOIN core.dim_state s ON s.state_id = g.state_id
                             WHERE g.geography_type='STATE' AND g.zone_id <> s.zone_id""") == 0)

        # ==============================================================
        # 10. STATE COST PANEL
        # ==============================================================
        section("10. State cost panel - grain proved, not described")
        panel_rows = scalar(cur, "SELECT count(*) FROM mart.mv_state_cost_panel_monthly")
        cur.execute("""
            SELECT state_id, observation_month, metric_code, COUNT(*)
            FROM mart.mv_state_cost_panel_monthly
            GROUP BY state_id, observation_month, metric_code
            HAVING COUNT(*) > 1
        """)
        dup_groups = cur.fetchall()
        check("duplicate-group query returns 0 rows", len(dup_groups) == 0,
              f"{len(dup_groups)} groups"
              + (f", e.g. {dup_groups[0]}" if dup_groups else ""))
        metrics = scalar(cur, "SELECT count(DISTINCT metric_code) "
                              "FROM mart.mv_state_cost_panel_monthly")
        check("panel has 15 metric codes", metrics == 15, f"{metrics}")
        check("panel is non-empty", panel_rows > 0, f"{panel_rows:,} rows")
        cur.execute("""SELECT metric_code FROM mart.mv_state_cost_panel_monthly GROUP BY 1
                       HAVING count(DISTINCT unit) > 1
                           OR count(DISTINCT source_dataset) > 1""")
        impure = cur.fetchall()
        check("each metric_code -> exactly one unit and one source dataset",
              len(impure) == 0, str(impure))
        expected_codes = {
            "PETROL_PRICE_NGN_PER_LITRE", "DIESEL_PRICE_NGN_PER_LITRE",
            "LPG_REFILL_5KG_NGN", "LPG_REFILL_12_5KG_NGN",
            "TRANSPORT_AIR_NGN_PER_JOURNEY",
            "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
            "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
            "TRANSPORT_OKADA_NGN_PER_JOURNEY", "TRANSPORT_WATER_NGN_PER_JOURNEY",
            "CPI_ALL_ITEMS_INDEX", "CPI_FOOD_INDEX",
            "CPI_ALL_ITEMS_YOY_PCT", "CPI_FOOD_YOY_PCT",
            "CPI_ALL_ITEMS_MOM_PCT", "CPI_FOOD_MOM_PCT",
        }
        cur.execute("SELECT DISTINCT metric_code FROM mart.mv_state_cost_panel_monthly")
        actual_codes = {r[0] for r in cur.fetchall()}
        check("metric codes decompose every source dimension",
              actual_codes == expected_codes,
              f"missing={sorted(expected_codes - actual_codes)} "
              f"unexpected={sorted(actual_codes - expected_codes)}")
        check("LPG cylinder size is carried in the metric code",
              sum(1 for c in actual_codes if c.startswith("LPG_")) == 2)
        check("all 5 transport modes are carried in the metric code",
              sum(1 for c in actual_codes if c.startswith("TRANSPORT_")) == 5)
        check("CPI group x measure gives 6 distinct metric codes",
              sum(1 for c in actual_codes if c.startswith("CPI_")) == 6)
        check("no state-month exceeds 15 rows",
              scalar(cur, """SELECT count(*) FROM (
                               SELECT state_id, observation_month
                               FROM mart.mv_state_cost_panel_monthly
                               GROUP BY 1,2 HAVING count(*) > 15) x""") == 0)

        # ==============================================================
        # 11. ANOMALY BRIDGE - all ten bridged tables
        # ==============================================================
        section("11. Anomaly bridge")
        bridge_rows = scalar(cur, "SELECT count(*) FROM core.bridge_fact_anomaly")
        unknown = scalar(cur, """SELECT count(*) FROM core.bridge_fact_anomaly b
                                 LEFT JOIN core.dim_anomaly_flag a USING (flag_code)
                                 WHERE a.flag_code IS NULL""")
        check("bridge is non-empty", bridge_rows > 0, f"{bridge_rows:,} rows")
        check("every bridge flag is a known flag", unknown == 0, f"{unknown} unknown")

        for fact in BRIDGE_SYMMETRIC:
            from_text = scalar(cur, f"""
                SELECT count(*) FROM core.{fact},
                       unnest(regexp_split_to_array(source_anomaly,'[|;]')) AS flag
                WHERE source_anomaly IS NOT NULL AND source_anomaly <> ''""")
            in_bridge = scalar(cur, "SELECT count(*) FROM core.bridge_fact_anomaly "
                                    "WHERE fact_table = %s", (fact,))
            check(f"{fact} bridge symmetric", from_text == in_bridge,
                  f"text={from_text} bridge={in_bridge}")

        # EVERY bridged fact_id must resolve, for all ten tables
        unresolved_total = 0
        for fact, pk in BRIDGE_PK.items():
            n = scalar(cur, f"""SELECT count(*) FROM core.bridge_fact_anomaly b
                                WHERE b.fact_table = %s
                                  AND NOT EXISTS (SELECT 1 FROM core.{fact} f
                                                  WHERE f.{pk} = b.fact_id)""", (fact,))
            rows_for = scalar(cur, "SELECT count(*) FROM core.bridge_fact_anomaly "
                                   "WHERE fact_table = %s", (fact,))
            unresolved_total += n
            check(f"{fact}.{pk} resolves every bridge row", n == 0,
                  f"{rows_for:,} bridge rows, {n} unresolved")
        check("no bridge row anywhere is unresolved", unresolved_total == 0,
              f"{unresolved_total}")
        check("bridge covers only known fact tables",
              scalar(cur, """SELECT count(DISTINCT fact_table)
                             FROM core.bridge_fact_anomaly
                             WHERE fact_table <> ALL(%s)""",
                     (list(BRIDGE_PK),)) == 0)

        # ==============================================================
        # 12. ANALYSIS WINDOWS
        # ==============================================================
        section("12. Analysis windows (two separate concepts)")
        cur.execute("""SELECT window_name, window_start::text, window_end::text, month_count
                       FROM mart.v_analysis_windows ORDER BY 1""")
        rows = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
        check("available observation window",
              rows.get("AVAILABLE_OBSERVATION_WINDOW") == AVAILABLE_WINDOW,
              str(rows.get("AVAILABLE_OBSERVATION_WINDOW")))
        check("primary-release common window",
              rows.get("PRIMARY_RELEASE_COMMON_WINDOW") == PRIMARY_WINDOW,
              str(rows.get("PRIMARY_RELEASE_COMMON_WINDOW")))
        check("the two windows are different",
              rows.get("AVAILABLE_OBSERVATION_WINDOW") != rows.get("PRIMARY_RELEASE_COMMON_WINDOW"))

        # ==============================================================
        # 13. SECONDARY ASSERTIONS FROM THE CLEANING PHASE
        # ==============================================================
        section("13. Secondary assertions from the cleaning phase")
        cur.execute("""SELECT m.measure, count(*) FROM core.fact_cpi_state_monthly f
                       JOIN core.dim_cpi_measure m USING (cpi_measure_id)
                       GROUP BY 1 ORDER BY 1""")
        cpi_by_measure = dict(cur.fetchall())
        check("CPI by measure", cpi_by_measure == {"CHANGE_MOM_PCT": 1332,
                                                   "CHANGE_YOY_PCT": 1258,
                                                   "INDEX": 3922}, str(cpi_by_measure))
        check("CPI primary rows = 3848 (74 demoted)",
              scalar(cur, "SELECT count(*) FROM core.fact_cpi_state_monthly "
                          "WHERE is_primary_release") == 3848)
        check("CPI alignment-disputed rows = 74",
              scalar(cur, """SELECT count(*) FROM core.fact_cpi_state_monthly
                             WHERE 'STATE_VALUE_ALIGNMENT_DISPUTED' =
                                   ANY(source_anomaly_flags)""") == 74)
        for fact, want in (("fact_petrol_price_monthly", (1887, 102, 51)),
                           ("fact_diesel_price_monthly", (1887, 306, 51)),
                           ("fact_lpg_price_monthly", (3552, 576, 96))):
            cur.execute(f"""SELECT g.geography_type, count(*) FROM core.{fact} f
                            JOIN core.dim_geography g USING (geography_id)
                            GROUP BY 1 ORDER BY 1""")
            got = dict(cur.fetchall())
            check(f"{fact} geography split",
                  (got.get("STATE"), got.get("ZONE"), got.get("NATIONAL")) == want,
                  str(got))
        check("NERC: 11 orders, 175 classes x 3 periods",
              scalar(cur, "SELECT count(*) FROM core.dim_nerc_order") == 11 and
              scalar(cur, """SELECT count(*) FROM (
                               SELECT order_id, tariff_class_id
                               FROM core.fact_electricity_tariff
                               GROUP BY 1,2) x""") == 175)
        check("NERC: one effective date across all orders",
              scalar(cur, "SELECT count(DISTINCT order_effective_date) "
                          "FROM core.dim_nerc_order") == 1)
        check("CBN: 419 ACTIVE + 6 EXACT_DUPLICATE",
              scalar(cur, "SELECT count(*) FROM core.fact_fx_rate_daily "
                          "WHERE record_status='ACTIVE'") == 419 and
              scalar(cur, "SELECT count(*) FROM core.fact_fx_rate_daily "
                          "WHERE record_status='EXACT_DUPLICATE'") == 6)
        check("food: 195 NULL national prices, all NOT_REPORTED",
              scalar(cur, """SELECT count(*) FROM core.fact_food_price_national_monthly
                             WHERE avg_price_ngn IS NULL
                               AND value_status='NOT_REPORTED'""") == 195 and
              scalar(cur, """SELECT count(*) FROM core.fact_food_price_zone_monthly
                             WHERE avg_price_ngn IS NULL""") == 0)
        check("CBN band exceptions = 5 (documented, not constrained)",
              scalar(cur, "SELECT count(*) FROM mart.v_fx_band_exceptions") == 5)
        check("comparability warning on every CPI row",
              scalar(cur, """SELECT count(*) FROM core.fact_cpi_state_monthly
                             WHERE comparability_warning IS NULL
                                OR comparability_warning = ''""") == 0)
        check("no DisCo is mapped to a state",
              scalar(cur, "SELECT count(*) FROM core.dim_disco "
                          "WHERE state_mapping <> 'NOT_MAPPED'") == 0)

        # ==============================================================
        # 14. PERMISSION MODEL - real privileges, not schema USAGE
        # ==============================================================
        section("14. Permission model (actual table and sequence privileges)")

        # BI reader isolation
        check("nbci_bi_reader has no USAGE on staging",
              not scalar(cur, "SELECT has_schema_privilege('nbci_bi_reader','staging','USAGE')"))
        check("nbci_bi_reader has no USAGE on core",
              not scalar(cur, "SELECT has_schema_privilege('nbci_bi_reader','core','USAGE')"))
        check("nbci_bi_reader has USAGE on mart",
              scalar(cur, "SELECT has_schema_privilege('nbci_bi_reader','mart','USAGE')"))

        # ETL must actually be able to LOAD, not merely see the schema.
        # Schema USAGE is NOT write access - that conflation hid a defect in
        # which nbci_etl held zero privileges on all 45 tables.
        DML = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        for schema in ("staging", "core"):
            cur.execute("""SELECT c.relname FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = %s AND c.relkind = 'r'
                           ORDER BY 1""", (schema,))
            tables = [r[0] for r in cur.fetchall()]
            missing = []
            for t in tables:
                for priv in DML:
                    if not scalar(cur, "SELECT has_table_privilege('nbci_etl', %s, %s)",
                                  (f"{schema}.{t}", priv)):
                        missing.append(f"{t}:{priv}")
            ok_tables = len(tables) - len({m.split(":")[0] for m in missing})
            check(f"nbci_etl holds {'/'.join(DML)} on all {len(tables)} {schema} tables",
                  not missing,
                  f"{ok_tables}/{len(tables)} tables fully privileged"
                  + (f"; {len(missing)} missing grants, e.g. {missing[:3]}" if missing else ""))

        # sequences behind identity columns
        cur.execute("""SELECT n.nspname, c.relname FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname IN ('staging','core') AND c.relkind = 'S'
                       ORDER BY 1,2""")
        seqs = cur.fetchall()
        seq_missing = [f"{s}.{q}" for s, q in seqs
                       if not scalar(cur, "SELECT has_sequence_privilege('nbci_etl', %s, %s)",
                                     (f"{s}.{q}", "USAGE"))]
        check(f"nbci_etl holds USAGE on all {len(seqs)} staging/core sequences",
              not seq_missing,
              f"{len(seqs) - len(seq_missing)}/{len(seqs)} sequences"
              + (f"; missing {seq_missing[:3]}" if seq_missing else ""))

        # THE READER MUST ACTUALLY BE ABLE TO READ MART.
        # Schema USAGE alone would leave it able to see the schema and
        # select nothing - which is exactly the bug this check now catches.
        cur.execute("""SELECT table_name FROM information_schema.views
                       WHERE table_schema='mart'
                       UNION ALL
                       SELECT matviewname FROM pg_matviews WHERE schemaname='mart'
                       ORDER BY 1""")
        mart_objs = [r[0] for r in cur.fetchall()]
        unreadable = [m for m in mart_objs
                      if not scalar(cur, "SELECT has_table_privilege('nbci_bi_reader', %s, 'SELECT')",
                                    (f"mart.{m}",))]
        check(f"nbci_bi_reader holds SELECT on all {len(mart_objs)} mart objects",
              not unreadable,
              f"{len(mart_objs) - len(unreadable)}/{len(mart_objs)} readable"
              + (f"; unreadable {unreadable[:3]}" if unreadable else ""))
        check("nbci_etl can also read mart",
              not [m for m in mart_objs
                   if not scalar(cur, "SELECT has_table_privilege('nbci_etl', %s, 'SELECT')",
                                 (f"mart.{m}",))])

        # and the reader must hold nothing at all in staging or core
        for schema in ("staging", "core"):
            cur.execute("""SELECT c.relname FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           WHERE n.nspname = %s AND c.relkind = 'r'""", (schema,))
            tabs = [r[0] for r in cur.fetchall()]
            leaked = [t for t in tabs
                      for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
                      if scalar(cur, "SELECT has_table_privilege('nbci_bi_reader', %s, %s)",
                                (f"{schema}.{t}", p))]
            check(f"nbci_bi_reader holds no privilege on any {schema} table",
                  not leaked, f"{len(tabs)} tables checked"
                  + (f"; leaked {leaked[:3]}" if leaked else ""))

        # the view-owner mechanism the design relies on must actually hold
        cur.execute("""SELECT count(*) FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname IN ('staging','core','mart')
                         AND c.relkind IN ('r','v','m')
                         AND pg_get_userbyid(c.relowner) <> 'nbci_owner'""")
        not_owned = cur.fetchone()[0]
        check("every staging/core/mart object is owned by nbci_owner",
              not_owned == 0, f"{not_owned} objects with another owner")
        # security_invoker=on would make a mart view run as the CALLER, which
        # would break reader isolation. strpos avoids LIKE wildcards, because
        # a literal % in the SQL collides with psycopg's placeholder scan.
        check("mart views run with the owner's privileges (security_invoker off)",
              scalar(cur, """SELECT count(*) FROM pg_class c
                             JOIN pg_namespace n ON n.oid = c.relnamespace
                             WHERE n.nspname='mart' AND c.relkind IN ('v','m')
                               AND strpos(coalesce(array_to_string(c.reloptions, ','), ''),
                                          'security_invoker=on') > 0""") == 0)

        # --- MAINTAIN: PostgreSQL 17+ requires it to REFRESH a matview ----
        # SELECT alone is not enough for a non-owner, so the design's claim
        # that nbci_etl refreshes matviews needs its own proof.
        cur.execute("""SELECT schemaname || '.' || matviewname
                       FROM pg_matviews WHERE schemaname='mart' ORDER BY 1""")
        matviews = [r[0] for r in cur.fetchall()]
        check("mart has the two expected materialized views",
              len(matviews) == 2, str(matviews))
        for mv in matviews:
            check(f"nbci_etl has SELECT on {mv}",
                  scalar(cur, "SELECT has_table_privilege('nbci_etl', %s, 'SELECT')", (mv,)))
            check(f"nbci_etl has MAINTAIN on {mv}",
                  scalar(cur, "SELECT has_table_privilege('nbci_etl', %s, 'MAINTAIN')", (mv,)))
            check(f"nbci_bi_reader has SELECT on {mv}",
                  scalar(cur, "SELECT has_table_privilege('nbci_bi_reader', %s, 'SELECT')", (mv,)))
            check(f"nbci_bi_reader does NOT have MAINTAIN on {mv}",
                  not scalar(cur, "SELECT has_table_privilege('nbci_bi_reader', %s, 'MAINTAIN')",
                             (mv,)))
        # MAINTAIN must not have leaked onto plain views or core tables
        leaked_maintain = scalar(cur, """
            SELECT count(*) FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('mart','core','staging')
              AND c.relkind IN ('r','v')
              AND has_table_privilege('nbci_etl', c.oid, 'MAINTAIN')""")
        check("MAINTAIN granted to no ordinary table or plain view",
              leaked_maintain == 0, f"{leaked_maintain} objects")

        # --- and prove it by EXECUTING as the roles themselves -------------
        section("14b. REFRESH executed as the roles themselves (not catalog only)")
        before = {mv: scalar(cur, f"SELECT count(*) FROM {mv}") for mv in matviews}
        panel_dups_before = scalar(cur, """SELECT count(*) FROM (
                                             SELECT state_id, observation_month, metric_code
                                             FROM mart.mv_state_cost_panel_monthly
                                             GROUP BY 1,2,3 HAVING count(*) > 1) x""")

        # This audit connection has read both matviews, so it holds ACCESS
        # SHARE on them. REFRESH needs ACCESS EXCLUSIVE, so without this
        # commit the refresh below blocks forever on our own read locks.
        conn.commit()

        with psycopg.connect(host=PGHOST, user=PGUSER, dbname=DB_NAME,
                             autocommit=True) as rc, rc.cursor() as rcur:
            # fail fast rather than hang if anything else holds a lock
            rcur.execute("SET lock_timeout = '20s'")
            for mv in matviews:
                rcur.execute("SET ROLE nbci_etl")
                try:
                    rcur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                    ok, detail = True, "refreshed"
                except psycopg.errors.InsufficientPrivilege as exc:
                    ok, detail = False, "PRIVILEGE: " + str(exc).splitlines()[0][:60]
                except psycopg.errors.LockNotAvailable:
                    ok, detail = False, "LOCK TIMEOUT - another session holds the matview"
                finally:
                    rcur.execute("RESET ROLE")
                check(f"nbci_etl CAN refresh {mv}", ok, detail)

            for mv in matviews:
                rcur.execute("SET ROLE nbci_bi_reader")
                try:
                    rcur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                    refused = False
                except psycopg.errors.InsufficientPrivilege:
                    refused = True
                finally:
                    rcur.execute("RESET ROLE")
                check(f"nbci_bi_reader CANNOT refresh {mv}", refused,
                      "refused" if refused else "SUCCEEDED - privilege leak")

            # the reader must still be able to read what it cannot refresh
            for mv in matviews:
                rcur.execute("SET ROLE nbci_bi_reader")
                try:
                    rcur.execute(f"SELECT count(*) FROM {mv}")
                    readable = rcur.fetchone()[0] == before[mv]
                except psycopg.errors.InsufficientPrivilege:
                    readable = False
                finally:
                    rcur.execute("RESET ROLE")
                check(f"nbci_bi_reader can still SELECT {mv}", readable)

        # the refresh must not have changed anything
        for mv in matviews:
            after = scalar(cur, f"SELECT count(*) FROM {mv}")
            check(f"{mv} row count unchanged by refresh", after == before[mv],
                  f"{after:,} vs {before[mv]:,}")
        panel_dups_after = scalar(cur, """SELECT count(*) FROM (
                                            SELECT state_id, observation_month, metric_code
                                            FROM mart.mv_state_cost_panel_monthly
                                            GROUP BY 1,2,3 HAVING count(*) > 1) x""")
        check("panel grain still unique after an nbci_etl refresh",
              panel_dups_after == 0 and panel_dups_before == 0,
              f"before={panel_dups_before} after={panel_dups_after}")

        # ==============================================================
        # 15. PUBLICATION-VERSION INTEGRITY (widened natural keys)
        # ==============================================================
        section("15. Publication-version integrity (widened natural keys)")
        WIDENED = ("fact_lpg_extreme_callout", "fact_transport_fare_state_monthly",
                   "fact_food_price_zone_monthly", "fact_food_extreme_callout")
        for t in WIDENED:
            defn = scalar(cur, """SELECT pg_get_constraintdef(con.oid)
                                  FROM pg_constraint con
                                  JOIN pg_class c ON c.oid = con.conrelid
                                  WHERE c.relname = %s AND con.contype = 'u'
                                    AND con.conname LIKE '%%natural_uk'""", (t,))
            check(f"{t} natural key carries release_month",
                  defn is not None and "release_month" in defn, str(defn))
        for t in WIDENED:
            has_col = scalar(cur, """SELECT count(*) FROM pg_attribute a
                                     JOIN pg_class c ON c.oid = a.attrelid
                                     JOIN pg_namespace n ON n.oid = c.relnamespace
                                     WHERE n.nspname='core' AND c.relname=%s
                                       AND a.attname='is_primary_release'""", (t,))
            check(f"{t} has no is_primary_release (primary rule is structural)",
                  has_col == 0, str(has_col))

        tsp = scalar(cur, "SELECT count(*) FROM mart.v_transport_state_primary")
        tsp_expected = scalar(cur, """SELECT count(*) FROM core.fact_transport_fare_state_monthly
                                      WHERE release_month = observation_month""")
        check("v_transport_state_primary = rows where release_month = observation_month",
              tsp == tsp_expected, f"{tsp:,}")
        tsl = scalar(cur, "SELECT count(*) FROM mart.v_transport_state_latest_restatement")
        tsl_expected = scalar(cur, """SELECT count(*) FROM (
                                        SELECT DISTINCT observation_month, geography_id,
                                               transport_mode_id
                                        FROM core.fact_transport_fare_state_monthly) x""")
        check("v_transport_state_latest_restatement = one row per (obs, geo, mode)",
              tsl == tsl_expected, f"{tsl:,}")
        fzp = scalar(cur, "SELECT count(*) FROM mart.v_food_zone_primary")
        fzp_expected = scalar(cur, """SELECT count(*) FROM core.fact_food_price_zone_monthly
                                      WHERE release_month = observation_month""")
        check("v_food_zone_primary = rows where release_month = observation_month",
              fzp == fzp_expected, f"{fzp:,}")
        fzl = scalar(cur, "SELECT count(*) FROM mart.v_food_zone_latest_restatement")
        fzl_expected = scalar(cur, """SELECT count(*) FROM (
                                        SELECT DISTINCT observation_month, item_id, geography_id
                                        FROM core.fact_food_price_zone_monthly) x""")
        check("v_food_zone_latest_restatement = one row per (obs, item, geo)",
              fzl == fzl_expected, f"{fzl:,}")
        tw = scalar(cur, """SELECT primary_end FROM mart.v_state_dataset_windows
                            WHERE dataset = 'TRANSPORT_STATE'""")
        tw_expected = scalar(cur, """SELECT max(f.observation_month)
                                     FROM core.fact_transport_fare_state_monthly f
                                     JOIN core.dim_geography g USING (geography_id)
                                     WHERE g.geography_type='STATE'
                                       AND f.release_month = f.observation_month""")
        check("v_state_dataset_windows derives transport primary coverage from the rule",
              tw == tw_expected and tw is not None, f"{tw}")
        fzn = scalar(cur, "SELECT count(*) FROM mart.v_food_zone_vs_national")
        check("v_food_zone_vs_national = one row per PRIMARY zone row",
              fzn == fzp, f"view={fzn:,} zone_primary={fzp:,}")
        check("v_food_zone_vs_national has no duplicate (month, item, zone)",
              scalar(cur, """SELECT count(*) FROM (
                               SELECT observation_month, item_code, zone_name
                               FROM mart.v_food_zone_vs_national
                               GROUP BY 1,2,3 HAVING count(*) > 1) x""") == 0)
        fznl = scalar(cur, "SELECT count(*) FROM mart.v_food_zone_vs_national_latest")
        check("v_food_zone_vs_national_latest = one row per LATEST zone row",
              fznl == fzl, f"view={fznl:,} zone_latest={fzl:,}")
        tmc = scalar(cur, "SELECT count(*) FROM mart.v_transport_mode_comparison")
        tmc_expected = scalar(cur, """SELECT count(*) FROM core.fact_transport_fare_state_monthly f
                                      JOIN core.dim_geography g USING (geography_id)
                                      WHERE g.geography_type='STATE'
                                        AND f.release_month = f.observation_month""")
        check("v_transport_mode_comparison uses PRIMARY publications only",
              tmc == tmc_expected, f"{tmc:,}")
        check("panel transport metrics come from PRIMARY publications",
              scalar(cur, """SELECT count(*) FROM mart.mv_state_cost_panel_monthly p
                             WHERE p.source_dataset = 'TRANSPORT_STATE'
                               AND p.release_month <> p.observation_month""") == 0)
        cur.execute("SELECT DISTINCT dataset FROM mart.mv_cross_release_stability")
        monitored = {r[0] for r in cur.fetchall()}
        viewdef = scalar(cur, "SELECT pg_get_viewdef('mart.mv_cross_release_stability'::regclass)")
        for ds in ("TRANSPORT_STATE", "FOOD_ZONE", "FOOD_CALLOUT", "LPG_CALLOUT"):
            check(f"stability monitor covers {ds}", ds in viewdef)
        check("stability monitor currently reports no restatement in those four",
              monitored.isdisjoint({"TRANSPORT_STATE", "FOOD_ZONE",
                                    "FOOD_CALLOUT", "LPG_CALLOUT"}),
              f"datasets present: {sorted(monitored)}")

    print(f"\n{'=' * 70}")
    if failures:
        print(f"DATABASE AUDIT FAILED: {passed} passed, {len(failures)} failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"INDEPENDENT DATABASE AUDIT: {passed} of {passed} assertions pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
