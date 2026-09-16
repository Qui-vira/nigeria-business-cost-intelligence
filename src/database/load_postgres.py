"""Build and load the PostgreSQL analytical layer.

Runs implementation steps 3-14 of docs/data_design/postgres_schema_design.md:
schemas and roles, load_audit, staging tables, the 17-file load with hash and
row-count verification, dimensions, facts, numeric round-trip verification,
foreign keys, constraints, indexes, views and the anomaly bridge.

Credentials come from the local libpq password file - on Windows
%APPDATA%\\postgresql\\pgpass.conf - which libpq reads itself. This script
never reads, prints, logs or stores a password, and no password environment
variable is used or requested. Non-secret connection settings (PGHOST, PGPORT,
PGUSER, PGDATABASE) may come from the environment.

    python src/database/load_postgres.py

Nothing under data/raw/ is opened. The cleaning pipelines are not imported.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys
import uuid
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from file_manifest import (  # noqa: E402
    INPUT_FILES, PROJECT_ROOT, EXPECTED_FACT_ROWS, EXPECTED_REFERENCE_ROWS,
)

# Connection defaults. libpq would otherwise default the user to the OS
# username, which does not match the postgres role in the password file.
PGHOST = os.environ.get("PGHOST", "localhost")
PGUSER = os.environ.get("PGUSER", "postgres")


def connect(dbname: str, **kw):
    return psycopg.connect(host=PGHOST, user=PGUSER, dbname=dbname, **kw)


SQL_DIR = PROJECT_ROOT / "sql"
DB_NAME = os.environ.get("NBCI_DATABASE", "nigeria_business_cost")

# Ordered DDL / population scripts.
SCRIPTS_BEFORE_LOAD = ["01_schemas_roles.sql", "02_staging.sql"]
SCRIPTS_DIMENSIONS = ["03_dimensions.sql", "09_populate_dimensions.sql"]
SCRIPTS_FACTS = ["04_facts.sql", "10_populate_facts.sql"]
SCRIPTS_AFTER = ["05_constraints.sql", "06_indexes.sql", "07_views.sql",
                 "08_bridge.sql",
                 # 11 must run LAST: object privileges can only be granted
                 # once the objects exist (see the header of that file)
                 "11_grants.sql"]

# Measure columns whose typed numeric must round-trip to the staging text.
# (staging table, staging column, core table, core column, natural-key join)
NUMERIC_ROUND_TRIP = [
    ("stg_fx_nfem_daily", "nfem_rate_ngn_per_usd",
     "fact_fx_rate_daily", "nfem_rate_ngn_per_usd", "source_id"),
    ("stg_fx_nfem_daily", "simple_avg_rate_ngn_per_usd",
     "fact_fx_rate_daily", "simple_avg_rate_ngn_per_usd", "source_id"),
    ("stg_fx_nfem_daily", "nfem_turnover_usd",
     "fact_fx_rate_daily", "nfem_turnover_usd", "source_id"),
    ("stg_petrol_price_monthly", "price_ngn_per_litre",
     "fact_petrol_price_monthly", "price_ngn_per_litre", "cell"),
    ("stg_diesel_price_monthly", "price_ngn_per_litre",
     "fact_diesel_price_monthly", "price_ngn_per_litre", "cell"),
    ("stg_cooking_gas_price_monthly", "refill_price_ngn",
     "fact_lpg_price_monthly", "refill_price_ngn", "cell"),
    ("stg_transport_fare_state_monthly", "fare_ngn",
     "fact_transport_fare_state_monthly", "fare_ngn", "cell"),
    ("stg_transport_fare_zone_monthly", "fare_ngn",
     "fact_transport_fare_zone_monthly", "fare_ngn", "cell"),
    ("stg_food_price_national_monthly", "avg_price_ngn",
     "fact_food_price_national_monthly", "avg_price_ngn", "cell"),
    ("stg_food_price_zone_monthly", "avg_price_ngn",
     "fact_food_price_zone_monthly", "avg_price_ngn", "cell"),
    ("stg_food_price_extreme_callout", "price_ngn",
     "fact_food_extreme_callout", "price_ngn", "cell"),
    ("stg_cpi_state_monthly", "value",
     "fact_cpi_state_monthly", "value", "cell"),
]

EXPECTED_DIMENSION_COUNTS = {
    "dim_zone": 6, "dim_state": 37, "dim_state_alias": 39,
    "dim_state_alias_observed": 77, "dim_geography": 44, "dim_month": 31,
    "dim_food_item": 42, "dim_transport_mode": 5, "dim_cpi_measure": 3,
    "dim_disco": 12, "dim_nerc_order": 11, "dim_tariff_class": 17,
    "dim_tariff_period": 3, "dim_anomaly_flag": 14,
}

EXPECTED_FACT_COUNTS = {
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

failures: list[str] = []


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def ok(msg: str) -> None:
    print(f"  OK    {msg}")


def bad(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) as raw text. Absence is the empty string."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = [r for r in reader]
    return header, rows


def run_script(conn: psycopg.Connection, name: str) -> None:
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    ok(f"ran {name}")


def preflight_privileges() -> bool:
    """Verify the connecting role actually holds the privileges this run needs.

    Privileges are read from pg_roles, never inferred from the role NAME. A role
    called 'postgres' is not assumed to be a superuser.
    """
    with connect("postgres", autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""SELECT current_user, rolsuper, rolcreatedb, rolcreaterole
                       FROM pg_roles WHERE rolname = current_user""")
        user, is_super, can_createdb, can_createrole = cur.fetchone()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        db_exists = cur.fetchone() is not None
        cur.execute("""SELECT count(*) FROM pg_roles
                       WHERE rolname IN ('nbci_owner','nbci_etl','nbci_bi_reader')""")
        roles_present = cur.fetchone()[0]

    print(f"  connected as        : {user}")
    print(f"  superuser           : {is_super}")
    print(f"  can create database : {can_createdb}")
    print(f"  can create role     : {can_createrole}")
    print(f"  target database     : {DB_NAME} ({'exists' if db_exists else 'must be created'})")
    print(f"  project roles present: {roles_present} of 3")

    need_createdb = not db_exists
    need_createrole = roles_present < 3

    if need_createdb and not (is_super or can_createdb):
        bad(f"role {user} cannot CREATE DATABASE, and {DB_NAME} does not exist. "
            f"Grant CREATEDB, or set NBCI_DATABASE to an existing database.")
    else:
        ok("database creation privilege satisfied"
           if need_createdb else "database already exists, no CREATEDB needed")

    if need_createrole and not (is_super or can_createrole):
        bad(f"role {user} cannot CREATE ROLE, and {3 - roles_present} of the three "
            f"project roles are missing.")
    else:
        ok("role creation privilege satisfied"
           if need_createrole else "all three project roles already exist")

    return not failures


def ensure_database() -> None:
    """Create the target database if it does not exist."""
    with connect("postgres", autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
            if cur.fetchone():
                ok(f"database {DB_NAME} already exists")
            else:
                cur.execute(f'CREATE DATABASE "{DB_NAME}"')
                ok(f"created database {DB_NAME}")


def load_files(conn: psycopg.Connection) -> str:
    """COPY all 17 files into staging, recording hash and counts."""
    run_id = str(uuid.uuid4())
    for f in INPUT_FILES:
        header, rows = read_csv(f.path)
        digest = sha256_file(f.path)
        size = f.path.stat().st_size

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO staging.load_audit
                     (load_run_id, source_path, target_table, file_kind,
                      file_sha256, file_bytes, csv_row_count, loaded_row_count,
                      column_count)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s) RETURNING load_id""",
                (run_id, f.source_path, f"staging.{f.staging_table}", f.file_kind,
                 digest, size, len(rows), len(header)))
            load_id = cur.fetchone()[0]

            cols = ", ".join(f'"{c}"' for c in header)
            copy_sql = (f'COPY staging.{f.staging_table} '
                        f'({cols}, stg_line_number, stg_load_id) FROM STDIN')
            with cur.copy(copy_sql) as cp:
                for i, row in enumerate(rows, start=1):
                    cp.write_row([*row, i, load_id])

            cur.execute(f"SELECT count(*) FROM staging.{f.staging_table}")
            loaded = cur.fetchone()[0]
            cur.execute("UPDATE staging.load_audit SET loaded_row_count = %s "
                        "WHERE load_id = %s", (loaded, load_id))
        conn.commit()

        if loaded != len(rows) or loaded != f.expected_rows:
            bad(f"{f.staging_table}: csv {len(rows)}, loaded {loaded}, "
                f"expected {f.expected_rows}")
        else:
            ok(f"{f.staging_table:<38} {loaded:>6} rows  sha256 {digest[:12]}...")
    return run_id


def verify_field_text(conn: psycopg.Connection, run_id: str) -> None:
    """Every staged field must equal the field parsed independently from the CSV.

    This validates parsed field-text preservation before typed casting. It does
    NOT claim that relational rows reproduce the original CSV bytes - that is
    what the SHA-256 in load_audit is for.
    """
    for f in INPUT_FILES:
        header, rows = read_csv(f.path)
        cols = ", ".join(f'"{c}"' for c in header)
        with conn.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM staging.{f.staging_table} "
                        f"ORDER BY stg_line_number")
            staged = cur.fetchall()
        match = True
        if len(staged) != len(rows):
            match = False
        else:
            for line, (csv_row, db_row) in enumerate(zip(rows, staged), start=1):
                db_text = ["" if v is None else v for v in db_row]
                if list(csv_row) != db_text:
                    match = False
                    diff = next((i for i, (a, b) in enumerate(zip(csv_row, db_text))
                                 if a != b), None)
                    bad(f"{f.staging_table} line {line} column "
                        f"{header[diff] if diff is not None else '?'}: "
                        f"csv={csv_row[diff]!r} db={db_text[diff]!r}")
                    break
        with conn.cursor() as cur:
            cur.execute("UPDATE staging.load_audit SET field_text_match = %s "
                        "WHERE target_table = %s AND load_run_id = %s",
                        (match, f"staging.{f.staging_table}", run_id))
        conn.commit()
        if match:
            ok(f"{f.staging_table:<38} field text preserved")


def verify_counts(conn: psycopg.Connection, expected: dict[str, int],
                  label: str) -> int:
    total = 0
    with conn.cursor() as cur:
        for table, want in expected.items():
            cur.execute(f"SELECT count(*) FROM core.{table}")
            got = cur.fetchone()[0]
            total += got
            if got != want:
                bad(f"core.{table}: expected {want}, got {got}")
            else:
                ok(f"core.{table:<38} {got:>6}")
    print(f"  ---- {label} total: {total:,}")
    return total


def verify_numeric_round_trip(conn: psycopg.Connection) -> None:
    """Typed numeric cast back to text must equal the staging text."""
    for stg, stg_col, fact, fact_col, join in NUMERIC_ROUND_TRIP:
        if join == "source_id":
            on = "f.source_id::text = s.source_id"
        else:
            on = ("f.source_file = s.source_file "
                  "AND coalesce(f.source_member,'') = coalesce(s.source_member,'') "
                  "AND f.source_sheet = s.source_sheet "
                  "AND f.source_cell_reference = s.source_cell_reference")
        sql = f"""
            SELECT count(*)
            FROM core.{fact} f
            JOIN staging.{stg} s ON {on}
            WHERE coalesce(f.{fact_col}::text, '') IS DISTINCT FROM
                  coalesce(nullif(s.{stg_col}, '')::numeric::text, '')
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            mismatches = cur.fetchone()[0]
        if mismatches:
            bad(f"{fact}.{fact_col}: {mismatches} values do not round-trip")
        else:
            ok(f"{fact}.{fact_col:<28} round-trips exactly")


def verify_orphans(conn: psycopg.Connection) -> None:
    sql = """
        SELECT con.conrelid::regclass::text AS child,
               con.conname,
               pg_get_constraintdef(con.oid) AS def
        FROM pg_constraint con
        JOIN pg_namespace n ON n.oid = con.connamespace
        WHERE con.contype = 'f' AND n.nspname = 'core'
        ORDER BY 1, 2
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        fks = cur.fetchall()
    ok(f"{len(fks)} foreign keys declared in core")
    # Postgres validates every FK at creation time; a surviving constraint
    # proves zero orphans. Re-assert that none is NOT VALID.
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM pg_constraint con
                       JOIN pg_namespace n ON n.oid = con.connamespace
                       WHERE con.contype = 'f' AND n.nspname = 'core'
                         AND NOT con.convalidated""")
        unvalidated = cur.fetchone()[0]
    if unvalidated:
        bad(f"{unvalidated} foreign keys are NOT VALID")
    else:
        ok("all foreign keys validated - zero orphans")


def verify_panel_grain(conn: psycopg.Connection) -> None:
    """Prove the claimed panel grain rather than describing it.

    The exact duplicate-group query must return zero rows, and every metric_code
    must uniquely identify all source-specific dimensions needed to interpret it
    (LPG cylinder size, transport mode, CPI group and measure).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT state_id, observation_month, metric_code, COUNT(*)
            FROM mart.mv_state_cost_panel_monthly
            GROUP BY state_id, observation_month, metric_code
            HAVING COUNT(*) > 1
        """)
        dups = cur.fetchall()
        if dups:
            bad(f"panel grain NOT unique: {len(dups)} duplicate groups, "
                f"e.g. {dups[0]}")
        else:
            ok("panel grain (state_id, observation_month, metric_code): 0 duplicate groups")

        # a metric_code must never span two units, two source datasets,
        # or - for the decomposed sources - two underlying dimension values
        cur.execute("""
            SELECT metric_code, count(DISTINCT unit) AS units,
                   count(DISTINCT source_dataset) AS datasets
            FROM mart.mv_state_cost_panel_monthly
            GROUP BY metric_code
            HAVING count(DISTINCT unit) > 1 OR count(DISTINCT source_dataset) > 1
        """)
        impure = cur.fetchall()
        if impure:
            bad(f"metric_code does not fully qualify its dimensions: {impure}")
        else:
            ok("every metric_code maps to exactly one unit and one source dataset")

        cur.execute("SELECT count(DISTINCT metric_code) "
                    "FROM mart.mv_state_cost_panel_monthly")
        n = cur.fetchone()[0]
        if n != 15:
            bad(f"expected 15 metric codes, got {n}")
        else:
            ok("15 metric codes present")

        cur.execute("""SELECT metric_code, count(*) FROM mart.mv_state_cost_panel_monthly
                       GROUP BY 1 ORDER BY 1""")
        for code, cnt in cur.fetchall():
            print(f"        {code:<42} {cnt:>6}")


def summarise(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        print(f"\n  PostgreSQL : {cur.fetchone()[0].split(',')[0]}")
        cur.execute("SELECT current_database(), current_user")
        db, user = cur.fetchone()
        print(f"  database   : {db}   connected as: {user}")

        cur.execute("""SELECT count(*) FROM pg_constraint con
                       JOIN pg_namespace n ON n.oid = con.connamespace
                       WHERE n.nspname='core' AND con.contype='c'""")
        print(f"  CHECK constraints in core   : {cur.fetchone()[0]}")
        cur.execute("""SELECT count(*) FROM pg_constraint con
                       JOIN pg_namespace n ON n.oid = con.connamespace
                       WHERE n.nspname='core' AND con.contype='u'""")
        print(f"  UNIQUE constraints in core  : {cur.fetchone()[0]}")
        cur.execute("""SELECT count(*) FROM pg_indexes
                       WHERE schemaname IN ('core','mart')""")
        print(f"  indexes in core + mart      : {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM core.bridge_fact_anomaly")
        print(f"  anomaly bridge rows         : {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM mart.mv_state_cost_panel_monthly")
        print(f"  state cost panel rows       : {cur.fetchone()[0]}")
        cur.execute("""SELECT window_name, window_start, window_end, month_count
                       FROM mart.v_analysis_windows ORDER BY 1""")
        for row in cur.fetchall():
            print(f"  {row[0]:<30} {row[1]} .. {row[2]}  ({row[3]} months)")


CONSTRAINT_FAILURE_GUIDANCE = """
A constraint or index failed to apply. This does NOT automatically mean the load
is wrong. Investigate which of these five causes the evidence supports, and
report the evidence BEFORE changing either the data or the rule:

  1. loading / transformation   - the loader mapped, joined or ordered wrongly
  2. SQL implementation          - the constraint differs from the rule it intends
  3. casting / NULL semantics    - '' vs NULL, numeric scale, date coercion,
                                   or three-valued logic behaving unlike the
                                   Python check that validated the CSV
  4. incorrect constraint expression - right idea, wrong predicate
  5. invalid design assumption   - the rule does not actually hold on this data

Never weaken a constraint merely to make the run pass.
"""


def apply_with_diagnosis(conn: psycopg.Connection, name: str) -> bool:
    """Run a constraint/index script, and on failure report evidence rather than
    assuming a cause."""
    try:
        run_script(conn, name)
        return True
    except psycopg.Error as exc:
        conn.rollback()
        diag = exc.diag
        bad(f"{name} failed: {diag.message_primary or exc}")
        print(CONSTRAINT_FAILURE_GUIDANCE)
        print("  Evidence available from the server:")
        for label, value in (("constraint", diag.constraint_name),
                             ("table", diag.table_name),
                             ("column", diag.column_name),
                             ("detail", diag.message_detail),
                             ("hint", diag.message_hint),
                             ("sqlstate", diag.sqlstate)):
            if value:
                print(f"    {label:<11}: {value}")
        print("  Next step: identify the offending rows and their source cells, "
              "classify the cause against the five above, then report.")
        return False


def main() -> int:
    step("Step 3a: privilege pre-flight (read from pg_roles, not inferred from the name)")
    if not preflight_privileges():
        print("\nAborting before creating anything: required privileges are missing.")
        for f in failures:
            print(f"  - {f}")
        return 1

    step("Step 3b: database, schemas and roles")
    ensure_database()

    with connect(DB_NAME) as conn:
        for name in SCRIPTS_BEFORE_LOAD:
            run_script(conn, name)

        step("Steps 4-6: load 17 CSVs into staging")
        run_id = load_files(conn)

        step("Step 6 gate: parsed field-text preservation")
        verify_field_text(conn, run_id)

        step("Step 7: dimensions")
        for name in SCRIPTS_DIMENSIONS:
            run_script(conn, name)
        verify_counts(conn, EXPECTED_DIMENSION_COUNTS, "dimensions")

        step("Step 8: facts")
        for name in SCRIPTS_FACTS:
            run_script(conn, name)
        total = verify_counts(conn, EXPECTED_FACT_COUNTS, "facts")
        if total != EXPECTED_FACT_ROWS:
            bad(f"total fact rows {total:,}, expected {EXPECTED_FACT_ROWS:,}")
        else:
            ok(f"total fact rows = {total:,}")

        step("Step 9: numeric round-trip against staging text")
        verify_numeric_round_trip(conn)

        step("Steps 10-12: foreign keys, constraints, indexes")
        for name in SCRIPTS_AFTER[:2]:
            if not apply_with_diagnosis(conn, name):
                print("\nStopping here. A constraint failure needs investigation, "
                      "not a workaround.")
                return 1
        verify_orphans(conn)

        step("Steps 13-14: views, state cost panel, anomaly bridge")
        for name in SCRIPTS_AFTER[2:]:
            if not apply_with_diagnosis(conn, name):
                return 1

        step("Step 14 gate: state cost panel grain")
        verify_panel_grain(conn)

        step("Summary")
        summarise(conn)

    print()
    if failures:
        print(f"LOAD FAILED: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("LOAD COMPLETE: every gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
