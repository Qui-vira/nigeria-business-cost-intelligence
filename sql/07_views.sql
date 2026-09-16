-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 07. Safety views, analysis windows and the state cost panel
--
-- Design: docs/data_design/postgres_schema_design.md  (section 8)
--
-- Every view here encodes a rule from the cleaning phase, so an analyst
-- cannot bypass it by accident. Views are owned by nbci_owner and run
-- with the owner's privileges, which is what lets nbci_bi_reader query
-- mart without holding any privilege on core.
--
-- Idempotent. Safe to re-run.
-- =====================================================================

SET search_path = mart, core, public;

-- =====================================================================
-- SAFETY VIEWS
-- =====================================================================

-- --- resolved geography, used by almost everything below --------------
CREATE OR REPLACE VIEW mart.v_geography AS
SELECT g.geography_id, g.geography_type, g.geography_name, g.is_aggregate,
       s.state_id, s.state_name, z.zone_id, z.zone_name
FROM core.dim_geography g
LEFT JOIN core.dim_state s ON s.state_id = g.state_id
LEFT JOIN core.dim_zone  z ON z.zone_id  = g.zone_id;
COMMENT ON VIEW mart.v_geography IS
  'Geography with state and zone names resolved. geography_type is always present: '
  'NEVER aggregate across it.';

-- --- primary-release views: the default an analyst should reach for ---
CREATE OR REPLACE VIEW mart.v_petrol_primary AS
SELECT * FROM core.fact_petrol_price_monthly WHERE is_primary_release;
CREATE OR REPLACE VIEW mart.v_diesel_primary AS
SELECT * FROM core.fact_diesel_price_monthly WHERE is_primary_release;
CREATE OR REPLACE VIEW mart.v_lpg_primary AS
SELECT * FROM core.fact_lpg_price_monthly WHERE is_primary_release;
CREATE OR REPLACE VIEW mart.v_transport_zone_primary AS
SELECT * FROM core.fact_transport_fare_zone_monthly WHERE is_primary_release;
CREATE OR REPLACE VIEW mart.v_food_national_primary AS
SELECT * FROM core.fact_food_price_national_monthly WHERE is_primary_release;
CREATE OR REPLACE VIEW mart.v_cpi_primary AS
SELECT * FROM core.fact_cpi_state_monthly WHERE is_primary_release;

COMMENT ON VIEW mart.v_cpi_primary IS
  'CPI first publications. 3,848 rows, not 3,922: the 74 alignment-disputed '
  'April 2025 rows are deliberately demoted (D-52) and are excluded here.';

-- --- latest restatement: the best current estimate of each month ------
CREATE OR REPLACE VIEW mart.v_petrol_latest_restatement AS
SELECT DISTINCT ON (observation_month, geography_id) *
FROM core.fact_petrol_price_monthly
ORDER BY observation_month, geography_id, release_month DESC;

CREATE OR REPLACE VIEW mart.v_diesel_latest_restatement AS
SELECT DISTINCT ON (observation_month, geography_id) *
FROM core.fact_diesel_price_monthly
ORDER BY observation_month, geography_id, release_month DESC;

CREATE OR REPLACE VIEW mart.v_lpg_latest_restatement AS
SELECT DISTINCT ON (observation_month, cylinder_size_kg, geography_id) *
FROM core.fact_lpg_price_monthly
ORDER BY observation_month, cylinder_size_kg, geography_id, release_month DESC;

CREATE OR REPLACE VIEW mart.v_cpi_latest_restatement AS
SELECT DISTINCT ON (observation_month, geography_id, cpi_group, cpi_measure_id) *
FROM core.fact_cpi_state_monthly
ORDER BY observation_month, geography_id, cpi_group, cpi_measure_id, release_month DESC;

COMMENT ON VIEW mart.v_cpi_latest_restatement IS
  'Most recent publication of each CPI observation. Use this OR v_cpi_primary, '
  'never both in one aggregate - they answer different questions.';

-- --- publication views for the widened-key tables ---------------------
--
-- fact_transport_fare_state_monthly and fact_food_price_zone_monthly carry NO
-- is_primary_release column, because their sheets publish one period per
-- release. Now that the natural keys admit a restatement
-- (observation_month < release_month), "which publication" must be stated
-- explicitly rather than assumed. The primary rule is structural:
--
--     primary publication  <=>  release_month = observation_month
--
-- Every row satisfies this today; these views exist so that the day one does
-- not, the answer is already defined instead of silently returning both.

CREATE OR REPLACE VIEW mart.v_transport_state_primary AS
SELECT * FROM core.fact_transport_fare_state_monthly
WHERE release_month = observation_month;
COMMENT ON VIEW mart.v_transport_state_primary IS
  'Transport state fares as first published: release_month = observation_month. '
  'The transport equivalent of is_primary_release on the other facts.';

CREATE OR REPLACE VIEW mart.v_transport_state_latest_restatement AS
SELECT DISTINCT ON (observation_month, geography_id, transport_mode_id) *
FROM core.fact_transport_fare_state_monthly
ORDER BY observation_month, geography_id, transport_mode_id,
         release_month DESC, transport_state_id DESC;
COMMENT ON VIEW mart.v_transport_state_latest_restatement IS
  'Most recent publication per (observation_month, geography_id, transport_mode_id). '
  'DISTINCT ON is made deterministic by the surrogate-key tie-break, so the result '
  'is stable even if two rows ever shared a release_month.';

CREATE OR REPLACE VIEW mart.v_food_zone_primary AS
SELECT * FROM core.fact_food_price_zone_monthly
WHERE release_month = observation_month;
COMMENT ON VIEW mart.v_food_zone_primary IS
  'Food zone averages as first published: release_month = observation_month.';

CREATE OR REPLACE VIEW mart.v_food_zone_latest_restatement AS
SELECT DISTINCT ON (observation_month, item_id, geography_id) *
FROM core.fact_food_price_zone_monthly
ORDER BY observation_month, item_id, geography_id,
         release_month DESC, food_zone_id DESC;
COMMENT ON VIEW mart.v_food_zone_latest_restatement IS
  'Most recent publication per (observation_month, item_id, geography_id), with a '
  'deterministic surrogate-key tie-break.';

-- --- coverage matrix: a gap should be visible, not inferred -----------
CREATE OR REPLACE VIEW mart.v_coverage_matrix AS
SELECT 'PETROL' AS dataset, observation_month, count(*) AS row_count FROM core.fact_petrol_price_monthly GROUP BY 2
UNION ALL SELECT 'DIESEL',          observation_month, count(*) FROM core.fact_diesel_price_monthly GROUP BY 2
UNION ALL SELECT 'LPG',             observation_month, count(*) FROM core.fact_lpg_price_monthly GROUP BY 2
UNION ALL SELECT 'LPG_CALLOUT',     observation_month, count(*) FROM core.fact_lpg_extreme_callout GROUP BY 2
UNION ALL SELECT 'TRANSPORT_STATE', observation_month, count(*) FROM core.fact_transport_fare_state_monthly GROUP BY 2
UNION ALL SELECT 'TRANSPORT_ZONE',  observation_month, count(*) FROM core.fact_transport_fare_zone_monthly GROUP BY 2
UNION ALL SELECT 'FOOD_NATIONAL',   observation_month, count(*) FROM core.fact_food_price_national_monthly GROUP BY 2
UNION ALL SELECT 'FOOD_ZONE',       observation_month, count(*) FROM core.fact_food_price_zone_monthly GROUP BY 2
UNION ALL SELECT 'FOOD_CALLOUT',    observation_month, count(*) FROM core.fact_food_extreme_callout GROUP BY 2
UNION ALL SELECT 'CPI',             observation_month, count(*) FROM core.fact_cpi_state_monthly GROUP BY 2;
COMMENT ON VIEW mart.v_coverage_matrix IS
  'Rows per dataset per month. Coverage ends where each publisher stopped - there '
  'is no shared end date.';

-- --- the 5 CBN rows outside their own published band ------------------
CREATE OR REPLACE VIEW mart.v_fx_band_exceptions AS
SELECT source_id, observation_date,
       lowest_rate_ngn_per_usd, highest_rate_ngn_per_usd,
       nfem_rate_ngn_per_usd, closing_rate_ngn_per_usd, simple_avg_rate_ngn_per_usd,
       (nfem_rate_ngn_per_usd    NOT BETWEEN lowest_rate_ngn_per_usd AND highest_rate_ngn_per_usd) AS nfem_outside_band,
       (closing_rate_ngn_per_usd NOT BETWEEN lowest_rate_ngn_per_usd AND highest_rate_ngn_per_usd) AS closing_outside_band
FROM core.fact_fx_rate_daily
WHERE nfem_rate_ngn_per_usd    NOT BETWEEN lowest_rate_ngn_per_usd AND highest_rate_ngn_per_usd
   OR closing_rate_ngn_per_usd NOT BETWEEN lowest_rate_ngn_per_usd AND highest_rate_ngn_per_usd;
COMMENT ON VIEW mart.v_fx_band_exceptions IS
  'CBN publishes a rate outside its own daily [low, high] band on 5 of 425 days: '
  'the closing rate on 4 days, and on 2026-03-06 the headline NFEM rate itself. '
  'Published source data, not a cleaning error - which is why no CHECK asserts it.';

-- =====================================================================
-- ANALYSIS WINDOWS  (correction 8: two DIFFERENT concepts, never conflated)
-- =====================================================================

CREATE OR REPLACE VIEW mart.v_state_dataset_windows AS
WITH d AS (
    SELECT 'PETROL' AS dataset, f.observation_month, f.is_primary_release
    FROM core.fact_petrol_price_monthly f
    JOIN core.dim_geography g USING (geography_id) WHERE g.geography_type = 'STATE'
  UNION ALL
    SELECT 'DIESEL', f.observation_month, f.is_primary_release
    FROM core.fact_diesel_price_monthly f
    JOIN core.dim_geography g USING (geography_id) WHERE g.geography_type = 'STATE'
  UNION ALL
    SELECT 'LPG', f.observation_month, f.is_primary_release
    FROM core.fact_lpg_price_monthly f
    JOIN core.dim_geography g USING (geography_id) WHERE g.geography_type = 'STATE'
  UNION ALL
    -- transport state has no is_primary_release column; the primary rule is
    -- structural. COMPUTED, never hard-coded, so a future restatement is
    -- correctly excluded from primary coverage.
    SELECT 'TRANSPORT_STATE', f.observation_month,
           (f.release_month = f.observation_month)
    FROM core.fact_transport_fare_state_monthly f
    JOIN core.dim_geography g USING (geography_id) WHERE g.geography_type = 'STATE'
  UNION ALL
    SELECT 'CPI', f.observation_month, f.is_primary_release
    FROM core.fact_cpi_state_monthly f
    JOIN core.dim_geography g USING (geography_id) WHERE g.geography_type = 'STATE'
)
SELECT dataset,
       min(observation_month)                                  AS available_start,
       max(observation_month)                                  AS available_end,
       min(observation_month) FILTER (WHERE is_primary_release) AS primary_start,
       max(observation_month) FILTER (WHERE is_primary_release) AS primary_end
FROM d GROUP BY dataset;

CREATE OR REPLACE VIEW mart.v_analysis_windows AS
SELECT 'AVAILABLE_OBSERVATION_WINDOW' AS window_name,
       max(available_start) AS window_start,
       min(available_end)   AS window_end,
       (EXTRACT(YEAR  FROM age(min(available_end), max(available_start))) * 12
      + EXTRACT(MONTH FROM age(min(available_end), max(available_start))) + 1)::int AS month_count,
       'Intersection of observation_month across the five state-grain datasets, '
       'counting every published row including restatements.' AS definition
FROM mart.v_state_dataset_windows
UNION ALL
SELECT 'PRIMARY_RELEASE_COMMON_WINDOW',
       max(primary_start), min(primary_end),
       (EXTRACT(YEAR  FROM age(min(primary_end), max(primary_start))) * 12
      + EXTRACT(MONTH FROM age(min(primary_end), max(primary_start))) + 1)::int,
       'Intersection over rows that are each dataset''s own first publication of '
       'that month. Starts a month later than the available window because CPI''s '
       'first release is February 2025.'
FROM mart.v_state_dataset_windows;

COMMENT ON VIEW mart.v_analysis_windows IS
  'TWO DIFFERENT CONCEPTS. Available observation window: 2025-01 to 2026-04 (16 '
  'months). Primary-release common window: 2025-02 to 2026-04 (15 months). Never '
  'treat them as the same thing - pick one explicitly.';

-- =====================================================================
-- THE STATE COST PANEL  (corrections 6 and 7)
--
-- LONG, not wide. Joining the state facts on (state_id, observation_month)
-- is unsafe: LPG has 2 rows per state-month (cylinder sizes), transport 5
-- (modes) and CPI 6 (2 groups x 3 measures). A five-way join would produce
-- 1 x 1 x 2 x 5 x 6 = 60 rows per state-month - a 60x Cartesian
-- multiplication that silently inflates every average.
--
-- Here each metric_code fully qualifies its own dimension, so the grain
-- (state_id, observation_month, metric_code) is unique BY CONSTRUCTION and
-- a Cartesian join is not merely avoided but impossible.
--
-- This is NOT a composite business-cost index. No such index has been
-- defined, which is why the object is named ..._panel_monthly and not
-- ..._index_monthly.
-- =====================================================================

DROP MATERIALIZED VIEW IF EXISTS mart.mv_state_cost_panel_monthly CASCADE;
CREATE MATERIALIZED VIEW mart.mv_state_cost_panel_monthly AS
WITH win AS (
    SELECT
      (SELECT window_start FROM mart.v_analysis_windows WHERE window_name = 'AVAILABLE_OBSERVATION_WINDOW')  AS avail_start,
      (SELECT window_end   FROM mart.v_analysis_windows WHERE window_name = 'AVAILABLE_OBSERVATION_WINDOW')  AS avail_end,
      (SELECT window_start FROM mart.v_analysis_windows WHERE window_name = 'PRIMARY_RELEASE_COMMON_WINDOW') AS prim_start,
      (SELECT window_end   FROM mart.v_analysis_windows WHERE window_name = 'PRIMARY_RELEASE_COMMON_WINDOW') AS prim_end
),
metrics AS (
    -- 1. petrol
    SELECT g.state_id, f.observation_month,
           'PETROL_PRICE_NGN_PER_LITRE'::text AS metric_code,
           f.price_ngn_per_litre AS metric_value, f.unit,
           'PETROL'::text AS source_dataset, f.release_month, f.source_anomaly_flags
    FROM core.fact_petrol_price_monthly f
    JOIN core.dim_geography g USING (geography_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release

    -- 2. diesel
    UNION ALL
    SELECT g.state_id, f.observation_month,
           'DIESEL_PRICE_NGN_PER_LITRE', f.price_ngn_per_litre, f.unit,
           'DIESEL', f.release_month, f.source_anomaly_flags
    FROM core.fact_diesel_price_monthly f
    JOIN core.dim_geography g USING (geography_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release

    -- 3-4. LPG, one metric per cylinder size
    UNION ALL
    SELECT g.state_id, f.observation_month,
           CASE WHEN f.cylinder_size_kg = 5.0 THEN 'LPG_REFILL_5KG_NGN'
                ELSE 'LPG_REFILL_12_5KG_NGN' END,
           f.refill_price_ngn, f.unit,
           'LPG', f.release_month, f.source_anomaly_flags
    FROM core.fact_lpg_price_monthly f
    JOIN core.dim_geography g USING (geography_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release

    -- 5-9. transport, one metric per mode
    UNION ALL
    SELECT g.state_id, f.observation_month,
           'TRANSPORT_' || m.transport_mode || '_NGN_PER_JOURNEY',
           f.fare_ngn, f.unit,
           'TRANSPORT_STATE', f.release_month, f.source_anomaly_flags
    FROM core.fact_transport_fare_state_monthly f
    JOIN core.dim_geography g USING (geography_id)
    JOIN core.dim_transport_mode m USING (transport_mode_id)
    -- PRIMARY publications only, matching every other input to this panel.
    -- Without this a restatement would add a second row for the same
    -- (state_id, observation_month, metric_code) and break the grain.
    WHERE g.geography_type = 'STATE' AND f.release_month = f.observation_month

    -- 10-15. CPI, one metric per group x measure
    UNION ALL
    SELECT g.state_id, f.observation_month,
           'CPI_' || f.cpi_group ||
           CASE cm.measure WHEN 'INDEX'          THEN '_INDEX'
                           WHEN 'CHANGE_YOY_PCT' THEN '_YOY_PCT'
                           ELSE                       '_MOM_PCT' END,
           f.value, cm.unit,
           'CPI', f.release_month, f.source_anomaly_flags
    FROM core.fact_cpi_state_monthly f
    JOIN core.dim_geography g USING (geography_id)
    JOIN core.dim_cpi_measure cm USING (cpi_measure_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release
)
SELECT m.state_id, s.state_name, z.zone_name,
       m.observation_month,
       m.metric_code, m.metric_value, m.unit,
       m.source_dataset, m.release_month, m.source_anomaly_flags,
       (m.observation_month BETWEEN w.avail_start AND w.avail_end) AS in_available_window,
       (m.observation_month BETWEEN w.prim_start  AND w.prim_end)  AS in_primary_release_window
FROM metrics m
CROSS JOIN win w
JOIN core.dim_state s ON s.state_id = m.state_id
JOIN core.dim_zone  z ON z.zone_id  = s.zone_id;

CREATE UNIQUE INDEX mv_state_cost_panel_grain_uix
    ON mart.mv_state_cost_panel_monthly (state_id, observation_month, metric_code);
CREATE INDEX mv_state_cost_panel_metric_ix
    ON mart.mv_state_cost_panel_monthly (metric_code, observation_month);

COMMENT ON MATERIALIZED VIEW mart.mv_state_cost_panel_monthly IS
  'LONG state cost panel. Grain (state_id, observation_month, metric_code) is unique '
  'by construction, so a Cartesian join is impossible. 15 metric codes. unit travels '
  'with every value so an index level and a naira price can never be summed. '
  'NOT a composite business-cost index - none has been defined.';

-- --- pivot AFTER reduction, never join before it ----------------------
CREATE OR REPLACE VIEW mart.v_state_cost_panel_wide AS
SELECT state_id, state_name, zone_name, observation_month,
       in_available_window, in_primary_release_window,
       max(metric_value) FILTER (WHERE metric_code = 'PETROL_PRICE_NGN_PER_LITRE')              AS petrol_ngn_per_litre,
       max(metric_value) FILTER (WHERE metric_code = 'DIESEL_PRICE_NGN_PER_LITRE')              AS diesel_ngn_per_litre,
       max(metric_value) FILTER (WHERE metric_code = 'LPG_REFILL_5KG_NGN')                      AS lpg_5kg_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'LPG_REFILL_12_5KG_NGN')                   AS lpg_12_5kg_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'TRANSPORT_AIR_NGN_PER_JOURNEY')           AS transport_air_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'TRANSPORT_BUS_INTERCITY_NGN_PER_JOURNEY') AS transport_bus_intercity_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'TRANSPORT_BUS_INTRACITY_NGN_PER_JOURNEY') AS transport_bus_intracity_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'TRANSPORT_OKADA_NGN_PER_JOURNEY')         AS transport_okada_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'TRANSPORT_WATER_NGN_PER_JOURNEY')         AS transport_water_ngn,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_ALL_ITEMS_INDEX')                     AS cpi_all_items_index,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_FOOD_INDEX')                          AS cpi_food_index,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_ALL_ITEMS_YOY_PCT')                   AS cpi_all_items_yoy_pct,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_FOOD_YOY_PCT')                        AS cpi_food_yoy_pct,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_ALL_ITEMS_MOM_PCT')                   AS cpi_all_items_mom_pct,
       max(metric_value) FILTER (WHERE metric_code = 'CPI_FOOD_MOM_PCT')                        AS cpi_food_mom_pct
FROM mart.mv_state_cost_panel_monthly
GROUP BY state_id, state_name, zone_name, observation_month,
         in_available_window, in_primary_release_window;
COMMENT ON VIEW mart.v_state_cost_panel_wide IS
  'Convenience pivot over the long panel, built with FILTER aggregates. Pivoting '
  'happens AFTER reduction - the raw facts are never joined on (state, month). '
  'A NULL here means "not published", not zero. CPI index columns must not be '
  'used to rank states.';

-- =====================================================================
-- BUSINESS VIEWS
-- =====================================================================

-- CPI: rates only. Index levels are deliberately absent.
CREATE OR REPLACE VIEW mart.v_cpi_state_inflation AS
SELECT f.release_month, f.observation_month,
       g.state_name, g.zone_name,
       f.cpi_group, cm.measure, f.value AS rate_pct, cm.unit,
       f.is_primary_release, f.source_anomaly, f.comparability_warning
FROM core.fact_cpi_state_monthly f
JOIN mart.v_geography g USING (geography_id)
JOIN core.dim_cpi_measure cm USING (cpi_measure_id)
WHERE cm.measure IN ('CHANGE_MOM_PCT','CHANGE_YOY_PCT');
COMMENT ON VIEW mart.v_cpi_state_inflation IS
  'CHANGE rates only. Index LEVELS are excluded on purpose: NBS prohibits using them '
  'for inter-state comparison. Rates MAY be compared across states.';

-- fuel price spread across states
CREATE OR REPLACE VIEW mart.v_fuel_price_spread AS
WITH p AS (
    SELECT 'PETROL' AS fuel, f.observation_month, g.state_name, g.zone_name, f.price_ngn_per_litre AS price
    FROM core.fact_petrol_price_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release
  UNION ALL
    SELECT 'DIESEL', f.observation_month, g.state_name, g.zone_name, f.price_ngn_per_litre
    FROM core.fact_diesel_price_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE g.geography_type = 'STATE' AND f.is_primary_release
)
SELECT fuel, observation_month,
       min(price) AS min_price, max(price) AS max_price,
       max(price) - min(price) AS spread_ngn,
       round(avg(price), 4) AS mean_price,
       (array_agg(state_name ORDER BY price))[1]                  AS cheapest_state,
       (array_agg(state_name ORDER BY price DESC))[1]             AS dearest_state,
       (array_agg(zone_name  ORDER BY price))[1]                  AS cheapest_zone,
       (array_agg(zone_name  ORDER BY price DESC))[1]             AS dearest_zone,
       count(*) AS state_count
FROM p GROUP BY fuel, observation_month;

-- food: zone premium or discount against the national figure
CREATE OR REPLACE VIEW mart.v_food_zone_vs_national AS
SELECT z.observation_month, i.item_code, i.item_label, i.unit AS item_unit,
       g.zone_name,
       z.avg_price_ngn AS zone_price_ngn,
       n.avg_price_ngn AS national_price_ngn,
       z.avg_price_ngn - n.avg_price_ngn AS premium_ngn,
       CASE WHEN n.avg_price_ngn IS NULL OR n.avg_price_ngn = 0 THEN NULL
            ELSE round(100.0 * (z.avg_price_ngn - n.avg_price_ngn) / n.avg_price_ngn, 4)
       END AS premium_pct,
       z.source_anomaly AS zone_anomaly
FROM mart.v_food_zone_primary z                       -- PRIMARY zone publication
JOIN mart.v_geography g USING (geography_id)
JOIN core.dim_food_item i ON i.item_id = z.item_id
LEFT JOIN core.fact_food_price_national_monthly n     -- PRIMARY national publication
       ON n.item_id = z.item_id
      AND n.observation_month = z.observation_month
      AND n.is_primary_release;
COMMENT ON VIEW mart.v_food_zone_vs_national IS
  'Zone premium to national per item per month, comparing PRIMARY zone publications '
  'with PRIMARY national publications - like with like. Each side is one row per '
  '(observation_month, item[, zone]), so a restatement on either side can neither '
  'duplicate a row nor cross-mix versions. For newest-versus-newest use '
  'v_food_zone_vs_national_latest; never mix the two semantics in one aggregate. '
  'Food is ZONE-level at best - no state-level food price exists in the corpus.';

-- the same comparison on the newest publication of each side, kept SEPARATE
-- rather than blended into the default view
CREATE OR REPLACE VIEW mart.v_food_zone_vs_national_latest AS
SELECT z.observation_month, i.item_code, i.item_label, i.unit AS item_unit,
       g.zone_name,
       z.release_month AS zone_release_month,
       n.release_month AS national_release_month,
       z.avg_price_ngn AS zone_price_ngn,
       n.avg_price_ngn AS national_price_ngn,
       z.avg_price_ngn - n.avg_price_ngn AS premium_ngn,
       CASE WHEN n.avg_price_ngn IS NULL OR n.avg_price_ngn = 0 THEN NULL
            ELSE round(100.0 * (z.avg_price_ngn - n.avg_price_ngn) / n.avg_price_ngn, 4)
       END AS premium_pct,
       z.source_anomaly AS zone_anomaly
FROM mart.v_food_zone_latest_restatement z
JOIN mart.v_geography g USING (geography_id)
JOIN core.dim_food_item i ON i.item_id = z.item_id
LEFT JOIN (
    SELECT DISTINCT ON (observation_month, item_id) *
    FROM core.fact_food_price_national_monthly
    ORDER BY observation_month, item_id, release_month DESC, food_national_id DESC
) n ON n.item_id = z.item_id AND n.observation_month = z.observation_month;
COMMENT ON VIEW mart.v_food_zone_vs_national_latest IS
  'Newest-versus-newest variant of v_food_zone_vs_national. Both release months are '
  'exposed so an analyst can see which publications are being compared.';

-- transport: mode by mode, never summed across modes
CREATE OR REPLACE VIEW mart.v_transport_mode_comparison AS
SELECT f.observation_month, m.transport_mode, m.raw_label AS mode_raw_label,
       g.state_name, g.zone_name, f.fare_ngn, f.unit
FROM core.fact_transport_fare_state_monthly f
JOIN mart.v_geography g USING (geography_id)
JOIN core.dim_transport_mode m USING (transport_mode_id)
WHERE g.geography_type = 'STATE'
  AND f.release_month = f.observation_month;   -- PRIMARY publications only
COMMENT ON VIEW mart.v_transport_mode_comparison IS
  'Fares by mode across states, PRIMARY publications only (release_month = '
  'observation_month). Modes are different services measured per journey; never sum '
  'or average across modes. For the newest figure per month use '
  'v_transport_state_latest_restatement instead - do not mix the two.';

-- NERC: a cross-section, and the name says so
CREATE OR REPLACE VIEW mart.v_tariff_band_cross_section AS
SELECT o.order_number, d.disco_code, d.disco_official_name,
       c.tariff_class, c.service_band, c.mdclass,
       f.tariff_ngn_per_kwh, f.unit,
       p.period_start, p.period_end, p.period_label_raw, f.is_current_period,
       o.order_effective_date, o.website_publication_date,
       o.vat_treatment, o.signing_date_status, d.state_mapping
FROM core.fact_electricity_tariff f
JOIN core.dim_nerc_order    o USING (order_id)
JOIN core.dim_disco         d USING (disco_id)
JOIN core.dim_tariff_class  c USING (tariff_class_id)
JOIN core.dim_tariff_period p USING (tariff_period_id);
COMMENT ON VIEW mart.v_tariff_band_cross_section IS
  'A validated JULY 2025 CROSS-SECTION of 11 of 217 NERC orders - not a tariff '
  'history. state_mapping is NOT_MAPPED on every row: this cannot be joined to '
  'state-level data.';

-- FX aggregated to month, ACTIVE rows only
CREATE OR REPLACE VIEW mart.v_fx_monthly_summary AS
SELECT date_trunc('month', observation_date)::date AS observation_month,
       count(*) AS trading_days,
       round(avg(nfem_rate_ngn_per_usd), 4) AS mean_nfem_rate,
       min(nfem_rate_ngn_per_usd)  AS min_nfem_rate,
       max(nfem_rate_ngn_per_usd)  AS max_nfem_rate,
       (array_agg(nfem_rate_ngn_per_usd ORDER BY observation_date))[1]      AS first_rate,
       (array_agg(nfem_rate_ngn_per_usd ORDER BY observation_date DESC))[1] AS last_rate
FROM core.fact_fx_rate_daily
WHERE record_status = 'ACTIVE'
GROUP BY 1;
COMMENT ON VIEW mart.v_fx_monthly_summary IS
  'ACTIVE rows only - the 6 exact-duplicate records are excluded from aggregates '
  'but remain in core for reconciliation.';

-- where restatements disagree
DROP MATERIALIZED VIEW IF EXISTS mart.mv_cross_release_stability CASCADE;
CREATE MATERIALIZED VIEW mart.mv_cross_release_stability AS
WITH obs AS (
    SELECT 'PETROL' AS dataset, observation_month, geography_id::text AS entity,
           price_ngn_per_litre AS value, release_month
    FROM core.fact_petrol_price_monthly
  UNION ALL
    SELECT 'DIESEL', observation_month, geography_id::text, price_ngn_per_litre, release_month
    FROM core.fact_diesel_price_monthly
  UNION ALL
    SELECT 'LPG', observation_month, geography_id::text || ':' || cylinder_size_kg::text,
           refill_price_ngn, release_month
    FROM core.fact_lpg_price_monthly
  UNION ALL
    SELECT 'CPI', observation_month,
           geography_id::text || ':' || cpi_group || ':' || cpi_measure_id::text,
           value, release_month
    FROM core.fact_cpi_state_monthly
  -- The four widened-key facts are restatement-capable too, so the monitor
  -- covers them. They contribute zero rows while no restatement exists, and
  -- would surface one immediately if it appeared.
  UNION ALL
    SELECT 'TRANSPORT_STATE', observation_month,
           geography_id::text || ':' || transport_mode_id::text,
           fare_ngn, release_month
    FROM core.fact_transport_fare_state_monthly
  UNION ALL
    SELECT 'FOOD_ZONE', observation_month,
           geography_id::text || ':' || item_id::text,
           avg_price_ngn, release_month
    FROM core.fact_food_price_zone_monthly
  UNION ALL
    SELECT 'FOOD_CALLOUT', observation_month,
           geography_id::text || ':' || item_id::text || ':' || extreme_type,
           price_ngn, release_month
    FROM core.fact_food_extreme_callout
  UNION ALL
    SELECT 'LPG_CALLOUT', observation_month,
           geography_id::text || ':' || cylinder_size_kg::text || ':' || extreme_type,
           price_ngn, release_month
    FROM core.fact_lpg_extreme_callout
)
SELECT dataset, observation_month, entity,
       count(*)                 AS publication_count,
       count(DISTINCT value)    AS distinct_values,
       min(value) AS min_value, max(value) AS max_value,
       max(value) - min(value)  AS value_range,
       min(release_month) AS first_release, max(release_month) AS last_release
FROM obs
GROUP BY dataset, observation_month, entity
HAVING count(*) > 1;

CREATE INDEX mv_cross_release_dataset_ix
    ON mart.mv_cross_release_stability (dataset, observation_month);
COMMENT ON MATERIALIZED VIEW mart.mv_cross_release_stability IS
  'Every observation published more than once, and whether the publications agree. '
  'distinct_values > 1 means the source restated the number - for CPI every such '
  'case is explained by a documented defect, not a revision.';
