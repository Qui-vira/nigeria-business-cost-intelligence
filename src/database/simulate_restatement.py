"""Prove the publication-version design against a restatement that does not yet exist.

Every row in the four widened-key facts currently has
``release_month = observation_month``, so the real data cannot demonstrate what
happens when a later release restates an earlier observation. This script
injects that situation, checks the whole mart layer behaves, and then ROLLS
BACK, so nothing synthetic is ever committed to the database.

    python src/database/simulate_restatement.py

Proves, for both fact_transport_fare_state_monthly and
fact_food_price_zone_monthly:

  1. core can store BOTH publication versions (the widened natural key admits it)
  2. the primary view returns the ORIGINAL publication
  3. the latest-restatement view returns the NEWER publication
  4. mv_state_cost_panel_monthly keeps one row per
     (state_id, observation_month, metric_code)
  5. the panel's unique index still builds
  6. v_food_zone_vs_national does not duplicate a zone/item/month
  7. the primary analysis window is not dragged forward by a restatement
"""
from __future__ import annotations

import os
import sys

import psycopg

PGHOST = os.environ.get("PGHOST", "localhost")
PGUSER = os.environ.get("PGUSER", "postgres")
DB_NAME = os.environ.get("NBCI_DATABASE", "nigeria_business_cost")

# a release month far later than the observation, and present in dim_month
RESTATEMENT_RELEASE = "2026-07-01"
TRANSPORT_OBS = "2025-03-01"
FOOD_ZONE_OBS = "2025-03-01"

passed = 0
failures: list[str] = []


def chk(label: str, cond: bool, detail: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        failures.append(f"{label}: {detail}")
        print(f"  FAIL  {label}  [{detail}]")


def main() -> int:
    conn = psycopg.connect(host=PGHOST, user=PGUSER, dbname=DB_NAME)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        print("Restatement simulation - all changes are rolled back at the end.\n")

        baseline_panel, = _one(cur, "SELECT count(*) FROM mart.mv_state_cost_panel_monthly")
        baseline_fzn, = _one(cur, "SELECT count(*) FROM mart.v_food_zone_vs_national")
        baseline_tmc, = _one(cur, "SELECT count(*) FROM mart.v_transport_mode_comparison")
        baseline_facts, = _one(cur, """
            SELECT (SELECT count(*) FROM core.fact_transport_fare_state_monthly)
                 + (SELECT count(*) FROM core.fact_food_price_zone_monthly)""")
        base_prim_end, = _one(cur, """
            SELECT primary_end FROM mart.v_state_dataset_windows
            WHERE dataset = 'TRANSPORT_STATE'""")
        print(f"  baseline: panel={baseline_panel:,}  v_food_zone_vs_national={baseline_fzn:,}"
              f"  v_transport_mode_comparison={baseline_tmc:,}")
        print(f"  baseline TRANSPORT_STATE primary_end = {base_prim_end}\n")

        # ---------------- inject a transport restatement ----------------
        print("--- injecting a transport restatement ---")
        tgt = _one(cur, """
            SELECT transport_state_id, geography_id, transport_mode_id, fare_ngn
            FROM core.fact_transport_fare_state_monthly
            WHERE observation_month = %s ORDER BY transport_state_id LIMIT 1""",
                   (TRANSPORT_OBS,))
        t_id, t_geo, t_mode, t_fare = tgt
        cur.execute("""
            INSERT INTO core.fact_transport_fare_state_monthly
                (release_month, observation_month, geography_id, geography_raw_label,
                 transport_mode_id, transport_mode_raw, fare_ngn, unit,
                 source_period_label, source_anomaly, source_file, source_member,
                 source_sheet, source_row, source_column_index, source_cell_reference)
            SELECT %s, observation_month, geography_id, geography_raw_label,
                   transport_mode_id, transport_mode_raw, fare_ngn + 1000, unit,
                   source_period_label, source_anomaly,
                   'SYNTHETIC_RESTATEMENT.xlsx', source_member,
                   source_sheet, source_row, source_column_index, source_cell_reference
            FROM core.fact_transport_fare_state_monthly
            WHERE transport_state_id = %s""", (RESTATEMENT_RELEASE, t_id))
        chk("1. core stored BOTH transport publication versions",
            _one(cur, """SELECT count(*) FROM core.fact_transport_fare_state_monthly
                         WHERE observation_month=%s AND geography_id=%s
                           AND transport_mode_id=%s""",
                 (TRANSPORT_OBS, t_geo, t_mode))[0] == 2,
            "widened natural key admits the restatement")

        prim = _one(cur, """SELECT count(*), max(fare_ngn) FROM mart.v_transport_state_primary
                            WHERE observation_month=%s AND geography_id=%s
                              AND transport_mode_id=%s""",
                    (TRANSPORT_OBS, t_geo, t_mode))
        chk("2. v_transport_state_primary returns the ORIGINAL only",
            prim[0] == 1 and prim[1] == t_fare, f"rows={prim[0]} fare={prim[1]}")

        latest = _one(cur, """SELECT count(*), max(fare_ngn), max(release_month)
                              FROM mart.v_transport_state_latest_restatement
                              WHERE observation_month=%s AND geography_id=%s
                                AND transport_mode_id=%s""",
                      (TRANSPORT_OBS, t_geo, t_mode))
        chk("3. v_transport_state_latest_restatement returns the NEWER only",
            latest[0] == 1 and latest[1] == t_fare + 1000
            and str(latest[2]) == RESTATEMENT_RELEASE,
            f"rows={latest[0]} fare={latest[1]} release={latest[2]}")

        # ---------------- inject a food-zone restatement ----------------
        print("\n--- injecting a food zone restatement ---")
        fz = _one(cur, """
            SELECT food_zone_id, item_id, geography_id, avg_price_ngn
            FROM core.fact_food_price_zone_monthly
            WHERE observation_month = %s ORDER BY food_zone_id LIMIT 1""",
                  (FOOD_ZONE_OBS,))
        f_id, f_item, f_geo, f_price = fz
        cur.execute("""
            INSERT INTO core.fact_food_price_zone_monthly
                (release_month, observation_month, item_id, item_label_raw,
                 geography_id, zone_raw_label, avg_price_ngn, value_status,
                 observation_month_basis, header_row_used, source_anomaly,
                 source_file, source_member, source_sheet, source_row,
                 source_column_index, source_cell_reference)
            SELECT %s, observation_month, item_id, item_label_raw,
                   geography_id, zone_raw_label, avg_price_ngn + 50, value_status,
                   observation_month_basis, header_row_used, source_anomaly,
                   'SYNTHETIC_RESTATEMENT.zip', source_member, source_sheet,
                   source_row, source_column_index, source_cell_reference
            FROM core.fact_food_price_zone_monthly
            WHERE food_zone_id = %s""", (RESTATEMENT_RELEASE, f_id))
        chk("1b. core stored BOTH food-zone publication versions",
            _one(cur, """SELECT count(*) FROM core.fact_food_price_zone_monthly
                         WHERE observation_month=%s AND item_id=%s AND geography_id=%s""",
                 (FOOD_ZONE_OBS, f_item, f_geo))[0] == 2)

        p2 = _one(cur, """SELECT count(*), max(avg_price_ngn) FROM mart.v_food_zone_primary
                          WHERE observation_month=%s AND item_id=%s AND geography_id=%s""",
                  (FOOD_ZONE_OBS, f_item, f_geo))
        chk("2b. v_food_zone_primary returns the ORIGINAL only",
            p2[0] == 1 and p2[1] == f_price, f"rows={p2[0]} price={p2[1]}")

        l2 = _one(cur, """SELECT count(*), max(avg_price_ngn)
                          FROM mart.v_food_zone_latest_restatement
                          WHERE observation_month=%s AND item_id=%s AND geography_id=%s""",
                  (FOOD_ZONE_OBS, f_item, f_geo))
        chk("3b. v_food_zone_latest_restatement returns the NEWER only",
            l2[0] == 1 and l2[1] == f_price + 50, f"rows={l2[0]} price={l2[1]}")

        # ---------------- the mart layer must survive -------------------
        print("\n--- mart layer behaviour with restatements present ---")
        cur.execute("REFRESH MATERIALIZED VIEW mart.mv_state_cost_panel_monthly")
        chk("5. the panel's UNIQUE index rebuilt successfully", True,
            "REFRESH would have raised on a duplicate grain")

        cur.execute("""SELECT state_id, observation_month, metric_code, count(*)
                       FROM mart.mv_state_cost_panel_monthly
                       GROUP BY 1,2,3 HAVING count(*) > 1""")
        dups = cur.fetchall()
        chk("4. panel grain still unique", len(dups) == 0, f"{len(dups)} duplicate groups")

        after_panel, = _one(cur, "SELECT count(*) FROM mart.mv_state_cost_panel_monthly")
        chk("4b. panel row count unchanged by the restatement",
            after_panel == baseline_panel, f"{after_panel:,} vs {baseline_panel:,}")

        cur.execute("""SELECT observation_month, item_code, zone_name, count(*)
                       FROM mart.v_food_zone_vs_national
                       GROUP BY 1,2,3 HAVING count(*) > 1""")
        fdup = cur.fetchall()
        after_fzn, = _one(cur, "SELECT count(*) FROM mart.v_food_zone_vs_national")
        chk("6. v_food_zone_vs_national does not duplicate zone/item/month",
            len(fdup) == 0 and after_fzn == baseline_fzn,
            f"dups={len(fdup)} rows={after_fzn:,} vs {baseline_fzn:,}")

        after_tmc, = _one(cur, "SELECT count(*) FROM mart.v_transport_mode_comparison")
        chk("6b. v_transport_mode_comparison unchanged (primary only)",
            after_tmc == baseline_tmc, f"{after_tmc:,} vs {baseline_tmc:,}")

        new_prim_end, = _one(cur, """SELECT primary_end FROM mart.v_state_dataset_windows
                                     WHERE dataset='TRANSPORT_STATE'""")
        chk("7. primary window NOT dragged forward by the restatement",
            new_prim_end == base_prim_end, f"{new_prim_end} vs {base_prim_end}")

        stab, = _one(cur, """SELECT count(*) FROM mart.mv_cross_release_stability
                             WHERE dataset IN ('TRANSPORT_STATE','FOOD_ZONE')""")
        cur.execute("REFRESH MATERIALIZED VIEW mart.mv_cross_release_stability")
        stab_after, = _one(cur, """SELECT count(*) FROM mart.mv_cross_release_stability
                                   WHERE dataset IN ('TRANSPORT_STATE','FOOD_ZONE')""")
        chk("8. stability monitor surfaces the two restatements",
            stab == 0 and stab_after == 2, f"before={stab} after={stab_after}")

        # latest-vs-latest variant should pick up the newer zone figure
        lv, = _one(cur, """SELECT zone_price_ngn FROM mart.v_food_zone_vs_national_latest
                           WHERE observation_month=%s AND item_code=(
                               SELECT item_code FROM core.dim_food_item WHERE item_id=%s)
                             AND zone_name=(SELECT zone_name FROM mart.v_geography
                                            WHERE geography_id=%s)""",
                   (FOOD_ZONE_OBS, f_item, f_geo))
        chk("9. v_food_zone_vs_national_latest shows the NEWER zone figure",
            lv == f_price + 50, f"{lv} vs expected {f_price + 50}")

    finally:
        conn.rollback()
        conn.close()

    # confirm nothing persisted
    with psycopg.connect(host=PGHOST, user=PGUSER, dbname=DB_NAME) as c2, c2.cursor() as k:
        k.execute("""SELECT (SELECT count(*) FROM core.fact_transport_fare_state_monthly)
                          + (SELECT count(*) FROM core.fact_food_price_zone_monthly)""")
        after = k.fetchone()[0]
        k.execute("""SELECT count(*) FROM core.fact_transport_fare_state_monthly
                     WHERE source_file LIKE 'SYNTHETIC%'""")
        synth = k.fetchone()[0]
        k.execute("REFRESH MATERIALIZED VIEW mart.mv_state_cost_panel_monthly")
        c2.commit()
    chk("10. ROLLBACK left no synthetic rows behind",
        after == baseline_facts and synth == 0,
        f"fact rows {after:,} (baseline {baseline_facts:,}), synthetic {synth}")

    print(f"\n{'=' * 66}")
    if failures:
        print(f"RESTATEMENT SIMULATION FAILED: {passed} passed, {len(failures)} failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"RESTATEMENT SIMULATION: {passed} of {passed} checks pass")
    return 0


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


if __name__ == "__main__":
    raise SystemExit(main())
