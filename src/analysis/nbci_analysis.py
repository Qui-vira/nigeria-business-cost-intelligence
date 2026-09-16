"""Shared analysis helpers: read-only database access, windows, validation harness.

Every analysis script in this package imports from here so that the safety rules
are declared once rather than restated per script.

THREE GUARANTEES THIS MODULE ENFORCES

1. The database is never modified. The connection sets
   `default_transaction_read_only = on`, so any INSERT/UPDATE/DELETE/DDL issued by
   an analysis script - deliberately or by mistake - is refused by the server with
   SQLSTATE 25006. This is a server-side guarantee, not a convention.
2. Cleaned datasets are never modified. Nothing here opens anything under
   `data/processed/`, `data/reference/` or `data/raw/`. The database is the source.
3. Analytical outputs are written only under `outputs/analysis/`, never back into
   `data/`.

Credentials come from the local libpq password file, which libpq reads itself.
This module never reads, prints, logs or stores a password.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "analysis"

PGHOST = os.environ.get("PGHOST", "localhost")
PGUSER = os.environ.get("PGUSER", "postgres")
DB_NAME = os.environ.get("NBCI_DATABASE", "nigeria_business_cost")

# ---------------------------------------------------------------------------
# Analysis windows. These mirror mart.v_analysis_windows and are verified
# against it at run time by check_windows_match_database() - they are never
# allowed to drift from the database silently.
# ---------------------------------------------------------------------------
AVAILABLE_WINDOW = ("2025-01-01", "2026-04-01")        # 16 months
PRIMARY_WINDOW = ("2025-02-01", "2026-04-01")          # 15 months
PRIMARY_WINDOW_MONTHS = 15
N_STATES = 37                                          # 36 states + FCT

# Metrics carried by mart.mv_state_cost_panel_monthly, grouped by how they may
# be used. The INDEX metrics are quarantined: NBS prints the prohibition inside
# the source table and comparability_warning is set on all 6,512 CPI rows.
PRICE_METRICS = [
    "PETROL_PRICE_NGN_PER_LITRE",
    "DIESEL_PRICE_NGN_PER_LITRE",
    "LPG_REFILL_5KG_NGN",
    "LPG_REFILL_12_5KG_NGN",
    "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
    "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
    "TRANSPORT_OKADA_NGN_PER_JOURNEY",
    "TRANSPORT_WATER_NGN_PER_JOURNEY",
    "TRANSPORT_AIR_NGN_PER_JOURNEY",
]
CPI_RATE_METRICS = [
    "CPI_ALL_ITEMS_YOY_PCT",
    "CPI_FOOD_YOY_PCT",
    "CPI_ALL_ITEMS_MOM_PCT",
    "CPI_FOOD_MOM_PCT",
]
# Never rank, average or compare states on these. Listed so the prohibition is
# machine-checkable rather than a comment someone has to remember.
CPI_INDEX_METRICS_DO_NOT_COMPARE_ACROSS_STATES = [
    "CPI_ALL_ITEMS_INDEX",
    "CPI_FOOD_INDEX",
]

# ---------------------------------------------------------------------------
# PERSISTENT HIGH-COST CLASSIFICATION
#
# The complete definition, in one place, so the classification is reproducible
# from these constants alone. Changing any of them changes the published result
# and must be a deliberate, stated decision - never a tweak to obtain a cleaner
# answer.
#
#   ranking method       : pandas rank(pct=True), method='average', ASCENDING
#                          (so a high percentile = an expensive jurisdiction),
#                          computed independently within each (metric, month).
#   high-cost threshold  : percentile rank STRICTLY GREATER THAN 0.75
#   low-cost threshold   : percentile rank LESS THAN OR EQUAL TO 0.25
#   tied values          : tied published prices receive the same AVERAGED
#                          percentile rank and therefore fall on the same side of
#                          the boundary together. Equal published prices are
#                          treated equally; ties are never broken arbitrarily, and
#                          this is why observed quartile sizes vary slightly.
#   minimum eligible     : a (jurisdiction, metric) pair is eligible only if it has
#                          at least MIN_ELIGIBLE_MONTHS observed months. Pairs with
#                          fewer are reported as INELIGIBLE, never as "not
#                          persistent".
#   denominator          : share_high = months in the high-cost quartile divided by
#                          the number of MONTHS ACTUALLY OBSERVED for that pair -
#                          NOT the 15-month window length.
#   missing observations : a month with no published value contributes to neither
#                          numerator nor denominator, and the count of observed
#                          months is reported alongside every share so a short
#                          series can never masquerade as a complete one.
#   persistent high      : share_high >= PERSISTENCE_THRESHOLD, among eligible pairs
# ---------------------------------------------------------------------------
HIGH_COST_QUANTILE = 0.75
LOW_COST_QUANTILE = 0.25
RANK_METHOD = "average"
PERSISTENCE_THRESHOLD = 0.80
MIN_ELIGIBLE_MONTHS = 12

# RANK STABILITY - a PROJECT DECISION-USE HEURISTIC, not a data-quality verdict.
#
# Every published rank is a VALID SNAPSHOT of that month: the underlying values are
# correctly extracted, correctly ranked, and correct as of their observation month.
# Nothing here questions the data.
#
# The heuristic answers a narrower, practical question: will a rank computed this
# month still describe the same jurisdiction next month, well enough to support a
# PERSISTENT, RANK-BASED LOCATION DECISION - siting, sourcing, a standing supplier
# preference? For that a rank has to be durable, not merely correct.
#
#   ratio = mean |month-over-month %| / mean cross-jurisdiction CV %
#
# At or above RANK_STABILITY_RATIO a typical monthly move is as large as the whole
# spread the ranking has to traverse, so ordinary price movement reshuffles the
# order. Such a metric is UNSTABLE FOR PERSISTENT RANKING - its snapshot ranks stay
# valid, but they should not anchor a durable location decision.
#
# The 1.0 cut is a judgement this project has adopted for consistency, not a
# statistical standard. Established by a02_source_verification.py (V4) and
# recomputed independently wherever it is used.
RANK_STABILITY_RATIO = 1.0

# Air and intercity bus are inter-regional services priced on carrier or route
# networks; a02 (V2) measured 83% of air's month-to-month variation as a common
# national movement. They are KEPT and reported, but never folded into a claim
# about LOCAL mobility.
LOCAL_MOBILITY_METRICS = [
    "TRANSPORT_OKADA_NGN_PER_JOURNEY",
    "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY",
    "TRANSPORT_WATER_NGN_PER_JOURNEY",
]
INTERREGIONAL_TRANSPORT_METRICS = [
    "TRANSPORT_AIR_NGN_PER_JOURNEY",
    "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY",
]

SHORT_LABEL = {
    "PETROL_PRICE_NGN_PER_LITRE": "Petrol (NGN/l)",
    "DIESEL_PRICE_NGN_PER_LITRE": "Diesel (NGN/l)",
    "LPG_REFILL_5KG_NGN": "LPG 5kg refill (NGN)",
    "LPG_REFILL_12_5KG_NGN": "LPG 12.5kg refill (NGN)",
    "TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY": "Bus intracity (NGN)",
    "TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY": "Bus intercity (NGN)",
    "TRANSPORT_OKADA_NGN_PER_JOURNEY": "Okada (NGN)",
    "TRANSPORT_WATER_NGN_PER_JOURNEY": "Water transport (NGN)",
    "TRANSPORT_AIR_NGN_PER_JOURNEY": "Air (NGN)",
    "CPI_ALL_ITEMS_YOY_PCT": "CPI all items YoY %",
    "CPI_FOOD_YOY_PCT": "CPI food YoY %",
    "CPI_ALL_ITEMS_MOM_PCT": "CPI all items MoM %",
    "CPI_FOOD_MOM_PCT": "CPI food MoM %",
}


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def connect():
    """Open a READ-ONLY connection. Any write is refused by the server."""
    conn = psycopg.connect(host=PGHOST, user=PGUSER, dbname=DB_NAME)
    with conn.cursor() as cur:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SET lock_timeout = '30s'")
    conn.commit()
    return conn


def q(conn, sql: str, params=None) -> pd.DataFrame:
    """Run a query and return a DataFrame. psycopg is used directly rather than
    SQLAlchemy; pandas warns about that, so the query is executed explicitly."""
    with conn.cursor() as cur:
        cur.execute(sql, params) if params else cur.execute(sql)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Validation harness
# ---------------------------------------------------------------------------
class Checks:
    """Accumulates validation results. Never raises mid-run, so one failure does
    not discard the checks that follow it (cleaning-phase lesson: a helper that
    raises inside validate() throws away every failure accumulated so far)."""

    def __init__(self) -> None:
        self.results: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, evidence: str = "") -> bool:
        self.results.append((bool(ok), name, evidence))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{evidence}]" if evidence else ""))
        return bool(ok)

    def eq(self, actual, expected, name: str) -> bool:
        return self.check(actual == expected, name, f"actual={actual} expected={expected}")

    @property
    def passed(self) -> int:
        return sum(1 for ok, _, _ in self.results if ok)

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.results if not ok)

    def summary(self, title: str) -> int:
        total = len(self.results)
        print("\n" + "=" * 78)
        print(f"{title}: {self.passed} of {total} checks pass")
        if self.failed:
            print(f"{self.failed} FAILED:")
            for ok, name, ev in self.results:
                if not ok:
                    print(f"  - {name}  [{ev}]")
        print("=" * 78)
        return self.failed


# ---------------------------------------------------------------------------
# Reusable structural checks
# ---------------------------------------------------------------------------
def check_read_only(conn, ck: Checks) -> None:
    """Prove the connection cannot write, rather than asserting that it cannot."""
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE nbci_write_probe (x int)")
        conn.rollback()
        ck.check(False, "connection is READ-ONLY", "a write succeeded - ABORT")
    except psycopg.errors.ReadOnlySqlTransaction:
        conn.rollback()
        ck.check(True, "connection is READ-ONLY", "write refused, SQLSTATE 25006")
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        ck.check(False, "connection is READ-ONLY", f"unexpected {type(e).__name__}")


def check_windows_match_database(conn, ck: Checks) -> None:
    w = q(conn, "SELECT window_name, window_start, window_end, month_count "
                "FROM mart.v_analysis_windows ORDER BY window_name")
    w = w.set_index("window_name")
    a = w.loc["AVAILABLE_OBSERVATION_WINDOW"]
    p = w.loc["PRIMARY_RELEASE_COMMON_WINDOW"]
    ck.check(str(a.window_start) == AVAILABLE_WINDOW[0] and str(a.window_end) == AVAILABLE_WINDOW[1],
             "AVAILABLE_OBSERVATION_WINDOW matches this module's constant",
             f"{a.window_start}..{a.window_end} ({a.month_count}m)")
    ck.check(str(p.window_start) == PRIMARY_WINDOW[0] and str(p.window_end) == PRIMARY_WINDOW[1],
             "PRIMARY_RELEASE_COMMON_WINDOW matches this module's constant",
             f"{p.window_start}..{p.window_end} ({p.month_count}m)")
    ck.eq(int(p.month_count), PRIMARY_WINDOW_MONTHS, "primary window is 15 months")


def check_no_duplicate_grain(df: pd.DataFrame, keys: list[str], name: str, ck: Checks) -> None:
    dups = int(df.duplicated(subset=keys).sum())
    ck.check(dups == 0, f"no duplicate analytical grain: {name}",
             f"{dups} duplicate rows on {tuple(keys)}")


def check_no_unexpected_nulls(df: pd.DataFrame, cols: list[str], name: str, ck: Checks) -> None:
    bad = {c: int(df[c].isna().sum()) for c in cols if int(df[c].isna().sum()) > 0}
    ck.check(not bad, f"no unexpected NULLs: {name}", f"{bad}" if bad else "0 nulls")


def check_units_unique_per_metric(df: pd.DataFrame, ck: Checks) -> None:
    per = df.groupby("metric_code")["unit"].nunique()
    bad = per[per > 1]
    ck.check(bad.empty, "each metric carries exactly one unit",
             "mixed: " + ", ".join(bad.index) if not bad.empty else f"{len(per)} metrics")


def write_csv(df: pd.DataFrame, subdir: str, filename: str) -> Path:
    out_dir = OUTPUT_ROOT / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return path


class Tee:
    """Mirror stdout to a log file so every reported figure has a saved run log."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "w", encoding="utf-8", newline="\n")
        self.stdout = sys.stdout

    def write(self, s):  # noqa: D102
        self.stdout.write(s)
        self.file.write(s)

    def flush(self):  # noqa: D102
        self.stdout.flush()
        self.file.flush()

    def close(self):  # noqa: D102
        self.file.close()
