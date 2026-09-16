-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 06. Indexes
--
-- Design: docs/data_design/postgres_schema_design.md  (section 6)
--
-- 29,032 rows total. Indexes here are for join ergonomics and constraint
-- enforcement, not for scale. Deliberately sparse.
--
-- Skipped on purpose:
--   * source_file / source_sheet - low cardinality, provenance only
--   * release_month alone - always used together with observation_month
--
-- Idempotent. Safe to re-run.
-- =====================================================================

SET search_path = core, public;

-- --- the dominant analytical filter: current-month rows only ---------
CREATE INDEX IF NOT EXISTS petrol_primary_ix ON core.fact_petrol_price_monthly (observation_month) WHERE is_primary_release;
CREATE INDEX IF NOT EXISTS diesel_primary_ix ON core.fact_diesel_price_monthly (observation_month) WHERE is_primary_release;
CREATE INDEX IF NOT EXISTS lpg_primary_ix    ON core.fact_lpg_price_monthly    (observation_month) WHERE is_primary_release;
CREATE INDEX IF NOT EXISTS tz_primary_ix     ON core.fact_transport_fare_zone_monthly (observation_month) WHERE is_primary_release;
CREATE INDEX IF NOT EXISTS fn_primary_ix     ON core.fact_food_price_national_monthly (observation_month) WHERE is_primary_release;
CREATE INDEX IF NOT EXISTS cpi_primary_ix    ON core.fact_cpi_state_monthly    (observation_month) WHERE is_primary_release;

-- --- geography-then-time: the natural BI drill path -------------------
CREATE INDEX IF NOT EXISTS petrol_geo_time_ix ON core.fact_petrol_price_monthly (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS diesel_geo_time_ix ON core.fact_diesel_price_monthly (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS lpg_geo_time_ix    ON core.fact_lpg_price_monthly    (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS lpgc_geo_time_ix   ON core.fact_lpg_extreme_callout  (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS ts_geo_time_ix     ON core.fact_transport_fare_state_monthly (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS tz_geo_time_ix     ON core.fact_transport_fare_zone_monthly  (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS fn_geo_time_ix     ON core.fact_food_price_national_monthly  (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS fz_geo_time_ix     ON core.fact_food_price_zone_monthly      (geography_id, observation_month);
CREATE INDEX IF NOT EXISTS fc_geo_time_ix     ON core.fact_food_extreme_callout         (geography_id, observation_month);

-- --- CPI: measure leads, because INDEX and PERCENT rows are never -----
-- --- queried together --------------------------------------------------
CREATE INDEX IF NOT EXISTS cpi_measure_time_geo_ix
    ON core.fact_cpi_state_monthly (cpi_measure_id, observation_month, geography_id);

-- --- item-driven food access ------------------------------------------
CREATE INDEX IF NOT EXISTS fn_item_time_ix ON core.fact_food_price_national_monthly (item_id, observation_month);
CREATE INDEX IF NOT EXISTS fz_item_time_ix ON core.fact_food_price_zone_monthly     (item_id, observation_month);
CREATE INDEX IF NOT EXISTS fc_item_time_ix ON core.fact_food_extreme_callout        (item_id, observation_month);

-- --- transport mode access --------------------------------------------
CREATE INDEX IF NOT EXISTS ts_mode_time_ix ON core.fact_transport_fare_state_monthly (transport_mode_id, observation_month);
CREATE INDEX IF NOT EXISTS tz_mode_time_ix ON core.fact_transport_fare_zone_monthly  (transport_mode_id, observation_month);

-- --- FX -----------------------------------------------------------------
CREATE INDEX IF NOT EXISTS fx_date_ix ON core.fact_fx_rate_daily (observation_date);

-- --- NERC ---------------------------------------------------------------
CREATE INDEX IF NOT EXISTS tariff_order_class_ix ON core.fact_electricity_tariff (order_id, tariff_class_id);
CREATE INDEX IF NOT EXISTS tariff_current_ix     ON core.fact_electricity_tariff (tariff_class_id) WHERE is_current_period;

-- --- anomaly triage: GIN on the derived flag array ----------------------
CREATE INDEX IF NOT EXISTS petrol_anomaly_gix ON core.fact_petrol_price_monthly USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS diesel_anomaly_gix ON core.fact_diesel_price_monthly USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS lpg_anomaly_gix    ON core.fact_lpg_price_monthly    USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS ts_anomaly_gix     ON core.fact_transport_fare_state_monthly USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS tz_anomaly_gix     ON core.fact_transport_fare_zone_monthly  USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS fn_anomaly_gix     ON core.fact_food_price_national_monthly  USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS fz_anomaly_gix     ON core.fact_food_price_zone_monthly      USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS fc_anomaly_gix     ON core.fact_food_extreme_callout         USING gin (source_anomaly_flags);
CREATE INDEX IF NOT EXISTS cpi_anomaly_gix    ON core.fact_cpi_state_monthly    USING gin (source_anomaly_flags);

-- Indexes on core.bridge_fact_anomaly live in 08_bridge.sql, because the
-- bridge is built after the views (implementation step 14).
