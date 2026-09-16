-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 10. Populate facts from staging  (12 tables, 29,032 rows)
--
-- Reads staging only. Every cast is explicit. An empty string becomes
-- NULL and never zero.
--
-- Rows are inserted in stg_line_number order so surrogate keys are
-- deterministic across reloads.
--
-- Run AFTER 09_populate_dimensions.sql. Idempotent.
-- =====================================================================

SET search_path = core, staging, public;

TRUNCATE core.fact_fx_rate_daily,
         core.fact_petrol_price_monthly,
         core.fact_diesel_price_monthly,
         core.fact_lpg_price_monthly,
         core.fact_lpg_extreme_callout,
         core.fact_transport_fare_state_monthly,
         core.fact_transport_fare_zone_monthly,
         core.fact_food_price_national_monthly,
         core.fact_food_price_zone_monthly,
         core.fact_food_extreme_callout,
         core.fact_cpi_state_monthly,
         core.fact_electricity_tariff
    RESTART IDENTITY CASCADE;

-- ---------------------------------------------------------------------
-- 1. fact_fx_rate_daily (425)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_fx_rate_daily
    (source_id, observation_date, source_date_label, geography_id,
     nfem_rate_ngn_per_usd, highest_rate_ngn_per_usd, lowest_rate_ngn_per_usd,
     closing_rate_ngn_per_usd, simple_avg_rate_ngn_per_usd,
     interbank_turnover_usd, interbank_deal_count,
     nfem_turnover_usd, nfem_deal_count,
     record_status, duplicate_of_source_id, source_file)
SELECT s.source_id::integer, s.observation_date::date, s.source_date_label, g.geography_id,
       s.nfem_rate_ngn_per_usd::numeric,
       s.highest_rate_ngn_per_usd::numeric,
       s.lowest_rate_ngn_per_usd::numeric,
       s.closing_rate_ngn_per_usd::numeric,
       s.simple_avg_rate_ngn_per_usd::numeric,
       nullif(s.interbank_turnover_usd,'')::numeric,
       nullif(s.interbank_deal_count,'')::integer,
       nullif(s.nfem_turnover_usd,'')::numeric,
       nullif(s.nfem_deal_count,'')::integer,
       s.record_status,
       nullif(s.duplicate_of_source_id,'')::integer,
       s.source_file
FROM staging.stg_fx_nfem_daily s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = 'Nigeria'
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 2. fact_petrol_price_monthly (2,040)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_petrol_price_monthly
    (release_month, observation_month, geography_id, geography_raw_label,
     price_ngn_per_litre, unit, is_primary_release,
     source_period_label, header_row_used, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, g.geography_id, s.geography_raw_label,
       s.price_ngn_per_litre::numeric, s.unit, s.is_primary_release::boolean,
       nullif(s.source_period_label,''), nullif(s.header_row_used,'')::integer,
       nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_petrol_price_monthly s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 3. fact_diesel_price_monthly (2,244)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_diesel_price_monthly
    (release_month, observation_month, geography_id, geography_raw_label,
     price_ngn_per_litre, unit, is_primary_release,
     source_period_label, header_row_used, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, g.geography_id, s.geography_raw_label,
       s.price_ngn_per_litre::numeric, s.unit, s.is_primary_release::boolean,
       nullif(s.source_period_label,''), nullif(s.header_row_used,'')::integer,
       nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_diesel_price_monthly s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 4. fact_lpg_price_monthly (4,224)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_lpg_price_monthly
    (release_month, observation_month, cylinder_size_kg, geography_id, geography_raw_label,
     refill_price_ngn, unit, is_primary_release,
     source_period_label, source_banner_text, header_row_used, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, s.cylinder_size_kg::numeric,
       g.geography_id, s.geography_raw_label,
       s.refill_price_ngn::numeric, s.unit, s.is_primary_release::boolean,
       nullif(s.source_period_label,''), nullif(s.source_banner_text,''),
       nullif(s.header_row_used,'')::integer, nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_cooking_gas_price_monthly s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 5. fact_lpg_extreme_callout (193)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_lpg_extreme_callout
    (release_month, observation_month, cylinder_size_kg, extreme_type, rank_within_block,
     geography_id, price_ngn, is_shared_extreme, raw_callout_text, tie_member_count,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, s.cylinder_size_kg::numeric,
       s.extreme_type, s.rank_within_block::integer,
       g.geography_id, s.price_ngn::numeric, s.is_shared_extreme::boolean,
       s.raw_callout_text, s.tie_member_count::integer,
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_cooking_gas_extreme_callout s
JOIN core.dim_geography g
  ON g.geography_type = 'STATE' AND g.geography_name = s.state
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 6. fact_transport_fare_state_monthly (3,230)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_transport_fare_state_monthly
    (release_month, observation_month, geography_id, geography_raw_label,
     transport_mode_id, transport_mode_raw, fare_ngn, unit,
     source_period_label, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, g.geography_id, s.geography_raw_label,
       m.transport_mode_id, s.transport_mode_raw,
       s.fare_ngn::numeric, s.unit,
       nullif(s.source_period_label,''), nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_transport_fare_state_monthly s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
JOIN core.dim_transport_mode m ON m.transport_mode = s.transport_mode
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 7. fact_transport_fare_zone_monthly (1,785)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_transport_fare_zone_monthly
    (release_month, observation_month, geography_id, geography_raw_label,
     transport_mode_id, transport_mode_raw, fare_ngn, unit,
     period_position, is_primary_release, source_period_label, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, g.geography_id, s.geography_raw_label,
       m.transport_mode_id, s.transport_mode_raw,
       s.fare_ngn::numeric, s.unit,
       s.period_position, s.is_primary_release::boolean,
       nullif(s.source_period_label,''), nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_transport_fare_zone_monthly s
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
JOIN core.dim_transport_mode m ON m.transport_mode = s.transport_mode
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 8. fact_food_price_national_monthly (2,142)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_food_price_national_monthly
    (release_month, observation_month, item_id, item_label_raw, geography_id,
     avg_price_ngn, value_status, period_position, is_primary_release,
     source_period_label, header_row_used, header_label_raw, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, i.item_id, s.item_label_raw,
       g.geography_id,
       nullif(s.avg_price_ngn,'')::numeric, s.value_status, s.period_position,
       s.is_primary_release::boolean,
       nullif(s.source_period_label,''), nullif(s.header_row_used,'')::integer,
       nullif(s.header_label_raw,''), nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_food_price_national_monthly s
JOIN core.dim_food_item i ON i.item_code = s.item_code
JOIN core.dim_geography g
  ON g.geography_type = s.geography_type AND g.geography_name = s.geography_name
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 9. fact_food_price_zone_monthly (4,284)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_food_price_zone_monthly
    (release_month, observation_month, item_id, item_label_raw, geography_id, zone_raw_label,
     avg_price_ngn, value_status, observation_month_basis,
     header_row_used, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, i.item_id, s.item_label_raw,
       g.geography_id, s.zone_raw_label,
       s.avg_price_ngn::numeric, s.value_status, s.observation_month_basis,
       nullif(s.header_row_used,'')::integer, nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_food_price_zone_monthly s
JOIN core.dim_food_item i ON i.item_code = s.item_code
JOIN core.dim_geography g
  ON g.geography_type = 'ZONE' AND g.geography_name = s.zone
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 10. fact_food_extreme_callout (1,428)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_food_extreme_callout
    (release_month, observation_month, item_id, item_label_raw, extreme_type,
     geography_id, state_raw_label, price_ngn, is_shared_extreme, raw_callout_text,
     observation_month_basis, header_row_used, source_anomaly,
     source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, i.item_id, s.item_label_raw,
       s.extreme_type, g.geography_id, s.state_raw_label,
       s.price_ngn::numeric, s.is_shared_extreme::boolean, s.raw_callout_text,
       s.observation_month_basis, nullif(s.header_row_used,'')::integer,
       nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_food_price_extreme_callout s
JOIN core.dim_food_item i ON i.item_code = s.item_code
JOIN core.dim_geography g
  ON g.geography_type = 'STATE' AND g.geography_name = s.state
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 11. fact_cpi_state_monthly (6,512)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_cpi_state_monthly
    (release_month, observation_month, geography_id, state_raw_label,
     cpi_group, cpi_group_raw, cpi_measure_id,
     value, base_period, period_position, period_label_raw,
     is_primary_release, value_status, comparability_warning, extraction_method,
     source_anomaly, source_file, source_member, source_sheet, source_row,
     source_column_index, source_cell_reference)
SELECT s.release_month::date, s.observation_month::date, g.geography_id, s.state_raw_label,
       s.cpi_group, s.cpi_group_raw, cm.cpi_measure_id,
       s.value::numeric, s.base_period, s.period_position, s.period_label_raw,
       s.is_primary_release::boolean, s.value_status, s.comparability_warning,
       s.extraction_method, nullif(s.source_anomaly,''),
       s.source_file, nullif(s.source_member,''), s.source_sheet,
       s.source_row::integer, s.source_column_index::integer, s.source_cell_reference
FROM staging.stg_cpi_state_monthly s
JOIN core.dim_geography g
  ON g.geography_type = 'STATE' AND g.geography_name = s.state
JOIN core.dim_cpi_measure cm ON cm.measure = s.measure
ORDER BY s.stg_line_number;

-- ---------------------------------------------------------------------
-- 12. fact_electricity_tariff (525)
-- ---------------------------------------------------------------------
INSERT INTO core.fact_electricity_tariff
    (order_id, tariff_class_id, tariff_period_id,
     tariff_ngn_per_kwh, unit, is_current_period,
     tariff_class_raw, disco_raw_label, period_label_raw, period_position,
     source_row_label, source_column_index)
SELECT o.order_id, c.tariff_class_id, p.tariff_period_id,
       s.tariff_ngn_per_kwh::numeric, s.unit, s.is_current_period::boolean,
       s.tariff_class_raw, s.disco_raw_label, s.period_label_raw, s.period_position,
       s.source_row_label, s.source_column_index::integer
FROM staging.stg_electricity_tariff_disco_period s
JOIN core.dim_nerc_order    o ON o.order_number    = s.order_number
JOIN core.dim_tariff_class  c ON c.tariff_class    = s.tariff_class
JOIN core.dim_tariff_period p ON p.period_position = s.period_position
ORDER BY s.stg_line_number;
