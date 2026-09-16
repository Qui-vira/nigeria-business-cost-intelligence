-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 05. Foreign keys, natural-key uniqueness and CHECK constraints
--
-- Design: docs/data_design/postgres_schema_design.md  (section 5)
--
-- EVERY constraint here was tested against the actual CSV data before
-- being written, and passes at the CSV level.
--
-- A failure here does NOT automatically mean the load is wrong. Investigate
-- which of these the evidence supports, and report it BEFORE changing the
-- data or the rule:
--   1. loading / transformation
--   2. SQL implementation (e.g. statement ORDER - a self-FK needs its
--      referenced UNIQUE constraint to exist first)
--   3. casting / NULL semantics
--   4. incorrect constraint expression
--   5. invalid design assumption
-- Never weaken a constraint merely to make the run pass.
--
-- Two constraints are deliberately absent - see the note at the end.
--
-- Run AFTER the facts are loaded.
-- =====================================================================

SET search_path = core, public;

-- NOTE: natural keys are declared BEFORE foreign keys because
-- fact_fx_rate_daily has a SELF-referencing FK (duplicate_of_source_id
-- -> source_id). PostgreSQL requires the referenced column to already
-- carry a UNIQUE or PK constraint when the FK is created.

-- =====================================================================
-- NATURAL KEYS  (the canonical grain of each fact - what validates the load)
--
-- EVERY fact carries release_month in its natural key, including the four
-- tables whose sheets publish only one period per release
-- (lpg_extreme_callout, transport_fare_state_monthly, food_price_zone_monthly,
-- food_extreme_callout). In those four, observation_month = release_month on
-- every row today, so including release_month changes no cardinality - it was
-- verified identical (193/3,230/4,284/1,428) before and after.
--
-- It is included anyway because the constraint set would otherwise contradict
-- itself: *_order_ck PERMITS observation_month < release_month (a restatement),
-- while a key omitting release_month would REJECT that same row with a unique
-- violation. A future restatement must be storable as a new publication, not
-- rejected. This matches the project rule from D-53: nothing is collapsed onto
-- a latest value; every publication keeps its own row, told apart by
-- release_month.
-- =====================================================================

ALTER TABLE core.fact_fx_rate_daily
    ADD CONSTRAINT fx_natural_uk UNIQUE (source_id);

ALTER TABLE core.fact_petrol_price_monthly
    ADD CONSTRAINT petrol_natural_uk UNIQUE (release_month, observation_month, geography_id);

ALTER TABLE core.fact_diesel_price_monthly
    ADD CONSTRAINT diesel_natural_uk UNIQUE (release_month, observation_month, geography_id);

ALTER TABLE core.fact_lpg_price_monthly
    ADD CONSTRAINT lpg_natural_uk UNIQUE (release_month, observation_month, cylinder_size_kg, geography_id);

ALTER TABLE core.fact_lpg_extreme_callout
    ADD CONSTRAINT lpgc_natural_uk UNIQUE (release_month, observation_month, cylinder_size_kg, extreme_type, geography_id);

ALTER TABLE core.fact_transport_fare_state_monthly
    ADD CONSTRAINT ts_natural_uk UNIQUE (release_month, observation_month, geography_id, transport_mode_id);

ALTER TABLE core.fact_transport_fare_zone_monthly
    ADD CONSTRAINT tz_natural_uk UNIQUE (release_month, observation_month, transport_mode_id, geography_id);

ALTER TABLE core.fact_food_price_national_monthly
    ADD CONSTRAINT fn_natural_uk UNIQUE (release_month, observation_month, item_id);

ALTER TABLE core.fact_food_price_zone_monthly
    ADD CONSTRAINT fz_natural_uk UNIQUE (release_month, observation_month, item_id, geography_id);

ALTER TABLE core.fact_food_extreme_callout
    ADD CONSTRAINT fc_natural_uk UNIQUE (release_month, observation_month, item_id, extreme_type, geography_id);

ALTER TABLE core.fact_cpi_state_monthly
    ADD CONSTRAINT cpi_natural_uk UNIQUE (release_month, observation_month, geography_id, cpi_group, cpi_measure_id);

ALTER TABLE core.fact_electricity_tariff
    ADD CONSTRAINT tariff_natural_uk UNIQUE (order_id, tariff_class_id, tariff_period_id);

-- =====================================================================
-- FOREIGN KEYS
-- =====================================================================

ALTER TABLE core.fact_fx_rate_daily
    ADD CONSTRAINT fx_geography_fk    FOREIGN KEY (geography_id) REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT fx_duplicate_of_fk FOREIGN KEY (duplicate_of_source_id) REFERENCES core.fact_fx_rate_daily(source_id);

ALTER TABLE core.fact_petrol_price_monthly
    ADD CONSTRAINT petrol_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT petrol_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT petrol_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_diesel_price_monthly
    ADD CONSTRAINT diesel_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT diesel_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT diesel_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_lpg_price_monthly
    ADD CONSTRAINT lpg_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT lpg_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT lpg_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_lpg_extreme_callout
    ADD CONSTRAINT lpgc_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT lpgc_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT lpgc_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_transport_fare_state_monthly
    ADD CONSTRAINT ts_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT ts_mode_fk        FOREIGN KEY (transport_mode_id) REFERENCES core.dim_transport_mode(transport_mode_id),
    ADD CONSTRAINT ts_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT ts_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_transport_fare_zone_monthly
    ADD CONSTRAINT tz_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT tz_mode_fk        FOREIGN KEY (transport_mode_id) REFERENCES core.dim_transport_mode(transport_mode_id),
    ADD CONSTRAINT tz_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT tz_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_food_price_national_monthly
    ADD CONSTRAINT fn_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT fn_item_fk        FOREIGN KEY (item_id)           REFERENCES core.dim_food_item(item_id),
    ADD CONSTRAINT fn_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT fn_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_food_price_zone_monthly
    ADD CONSTRAINT fz_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT fz_item_fk        FOREIGN KEY (item_id)           REFERENCES core.dim_food_item(item_id),
    ADD CONSTRAINT fz_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT fz_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_food_extreme_callout
    ADD CONSTRAINT fc_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT fc_item_fk        FOREIGN KEY (item_id)           REFERENCES core.dim_food_item(item_id),
    ADD CONSTRAINT fc_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT fc_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_cpi_state_monthly
    ADD CONSTRAINT cpi_geography_fk   FOREIGN KEY (geography_id)      REFERENCES core.dim_geography(geography_id),
    ADD CONSTRAINT cpi_measure_fk     FOREIGN KEY (cpi_measure_id)    REFERENCES core.dim_cpi_measure(cpi_measure_id),
    ADD CONSTRAINT cpi_release_fk     FOREIGN KEY (release_month)     REFERENCES core.dim_month(month_date),
    ADD CONSTRAINT cpi_observation_fk FOREIGN KEY (observation_month) REFERENCES core.dim_month(month_date);

ALTER TABLE core.fact_electricity_tariff
    ADD CONSTRAINT tariff_order_fk  FOREIGN KEY (order_id)         REFERENCES core.dim_nerc_order(order_id),
    ADD CONSTRAINT tariff_class_fk  FOREIGN KEY (tariff_class_id)  REFERENCES core.dim_tariff_class(tariff_class_id),
    ADD CONSTRAINT tariff_period_fk FOREIGN KEY (tariff_period_id) REFERENCES core.dim_tariff_period(tariff_period_id);

-- =====================================================================
-- PROVENANCE: one source cell -> one clean row
--
-- NULLS NOT DISTINCT because source_member is NULL for loose (non-ZIP)
-- workbooks and those rows must still collide on the rest of the key.
--
-- fact_lpg_extreme_callout is the DOCUMENTED exception: 192 cells produce
-- 193 rows because one cell names two tied states. It gets the weaker
-- guarantee below instead.
-- =====================================================================

ALTER TABLE core.fact_petrol_price_monthly
    ADD CONSTRAINT petrol_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_diesel_price_monthly
    ADD CONSTRAINT diesel_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_lpg_price_monthly
    ADD CONSTRAINT lpg_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_transport_fare_state_monthly
    ADD CONSTRAINT ts_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_transport_fare_zone_monthly
    ADD CONSTRAINT tz_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_food_price_national_monthly
    ADD CONSTRAINT fn_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_food_price_zone_monthly
    ADD CONSTRAINT fz_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_food_extreme_callout
    ADD CONSTRAINT fc_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);
ALTER TABLE core.fact_cpi_state_monthly
    ADD CONSTRAINT cpi_cell_uk UNIQUE NULLS NOT DISTINCT (source_file, source_member, source_sheet, source_cell_reference);

-- the tie exception: a shared cell is allowed only when it is declared shared
ALTER TABLE core.fact_lpg_extreme_callout
    ADD CONSTRAINT lpgc_tie_ck CHECK (tie_member_count = 1 OR is_shared_extreme);

-- =====================================================================
-- PERIOD SEMANTICS  (all 10 monthly facts)
-- =====================================================================

ALTER TABLE core.fact_petrol_price_monthly
    ADD CONSTRAINT petrol_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                      AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT petrol_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT petrol_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

ALTER TABLE core.fact_diesel_price_monthly
    ADD CONSTRAINT diesel_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                      AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT diesel_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT diesel_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

ALTER TABLE core.fact_lpg_price_monthly
    ADD CONSTRAINT lpg_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                   AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT lpg_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT lpg_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

ALTER TABLE core.fact_lpg_extreme_callout
    ADD CONSTRAINT lpgc_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                    AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT lpgc_order_ck CHECK (observation_month <= release_month);

ALTER TABLE core.fact_transport_fare_state_monthly
    ADD CONSTRAINT ts_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                  AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT ts_order_ck CHECK (observation_month <= release_month);

ALTER TABLE core.fact_transport_fare_zone_monthly
    ADD CONSTRAINT tz_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                  AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT tz_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT tz_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

ALTER TABLE core.fact_food_price_national_monthly
    ADD CONSTRAINT fn_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                  AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT fn_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT fn_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

ALTER TABLE core.fact_food_price_zone_monthly
    ADD CONSTRAINT fz_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                  AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT fz_order_ck CHECK (observation_month <= release_month);

ALTER TABLE core.fact_food_extreme_callout
    ADD CONSTRAINT fc_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                  AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT fc_order_ck CHECK (observation_month <= release_month);

-- CPI: is_primary_release MUST be one-way. 74 April-2025 rows have
-- observation_month = release_month but is_primary_release = FALSE,
-- because they are alignment-disputed and deliberately demoted (D-52).
-- An equality constraint here would reject them and destroy the defect handling.
ALTER TABLE core.fact_cpi_state_monthly
    ADD CONSTRAINT cpi_month_ck CHECK (release_month = date_trunc('month', release_month)::date
                                   AND observation_month = date_trunc('month', observation_month)::date),
    ADD CONSTRAINT cpi_order_ck CHECK (observation_month <= release_month),
    ADD CONSTRAINT cpi_primary_ck CHECK (NOT is_primary_release OR observation_month = release_month);

-- =====================================================================
-- VALUE INTEGRITY
-- =====================================================================

ALTER TABLE core.fact_petrol_price_monthly
    ADD CONSTRAINT petrol_price_ck CHECK (price_ngn_per_litre > 0),
    ADD CONSTRAINT petrol_unit_ck  CHECK (unit = 'NGN per litre');

ALTER TABLE core.fact_diesel_price_monthly
    ADD CONSTRAINT diesel_price_ck CHECK (price_ngn_per_litre > 0),
    ADD CONSTRAINT diesel_unit_ck  CHECK (unit = 'NGN per litre');

ALTER TABLE core.fact_lpg_price_monthly
    ADD CONSTRAINT lpg_price_ck    CHECK (refill_price_ngn > 0),
    ADD CONSTRAINT lpg_unit_ck     CHECK (unit = 'NGN per refill'),
    ADD CONSTRAINT lpg_cylinder_ck CHECK (cylinder_size_kg IN (5.0, 12.5));

ALTER TABLE core.fact_lpg_extreme_callout
    ADD CONSTRAINT lpgc_price_ck    CHECK (price_ngn > 0),
    ADD CONSTRAINT lpgc_cylinder_ck CHECK (cylinder_size_kg IN (5.0, 12.5)),
    ADD CONSTRAINT lpgc_extreme_ck  CHECK (extreme_type IN ('HIGHEST','LOWEST')),
    ADD CONSTRAINT lpgc_rank_ck     CHECK (rank_within_block >= 1);

ALTER TABLE core.fact_transport_fare_state_monthly
    ADD CONSTRAINT ts_fare_ck CHECK (fare_ngn > 0),
    ADD CONSTRAINT ts_unit_ck CHECK (unit = 'NGN per journey');

ALTER TABLE core.fact_transport_fare_zone_monthly
    ADD CONSTRAINT tz_fare_ck   CHECK (fare_ngn > 0),
    ADD CONSTRAINT tz_unit_ck   CHECK (unit = 'NGN per journey'),
    ADD CONSTRAINT tz_period_ck CHECK (period_position IN ('CURRENT_MONTH','PRIOR_MONTH','YEAR_AGO'));

-- a blank is never a zero: NULL price and NOT_REPORTED are the same fact
ALTER TABLE core.fact_food_price_national_monthly
    ADD CONSTRAINT fn_status_ck CHECK ((avg_price_ngn IS NULL) = (value_status = 'NOT_REPORTED')),
    ADD CONSTRAINT fn_price_ck  CHECK (avg_price_ngn IS NULL OR avg_price_ngn > 0),
    ADD CONSTRAINT fn_period_ck CHECK (period_position IN ('CURRENT_MONTH','PRIOR_MONTH','YEAR_AGO'));

ALTER TABLE core.fact_food_price_zone_monthly
    ADD CONSTRAINT fz_price_ck  CHECK (avg_price_ngn > 0),
    ADD CONSTRAINT fz_status_ck CHECK (value_status = 'OK');

ALTER TABLE core.fact_food_extreme_callout
    ADD CONSTRAINT fc_price_ck   CHECK (price_ngn > 0),
    ADD CONSTRAINT fc_extreme_ck CHECK (extreme_type IN ('HIGHEST','LOWEST'));

-- CPI: group domain and base period. measure<->unit agreement is declared
-- once in dim_cpi_measure and reaches this table through the FK.
ALTER TABLE core.fact_cpi_state_monthly
    ADD CONSTRAINT cpi_group_ck  CHECK (cpi_group IN ('FOOD','ALL_ITEMS')),
    ADD CONSTRAINT cpi_base_ck   CHECK (base_period = '2024=100'),
    ADD CONSTRAINT cpi_status_ck CHECK (value_status = 'OK'),
    ADD CONSTRAINT cpi_period_ck CHECK (period_position IN ('CURRENT_MONTH','PRIOR_MONTH','YEAR_AGO'));

ALTER TABLE core.fact_electricity_tariff
    ADD CONSTRAINT tariff_value_ck CHECK (tariff_ngn_per_kwh > 0),
    ADD CONSTRAINT tariff_unit_ck  CHECK (unit = 'NGN per kWh');

-- CBN
ALTER TABLE core.fact_fx_rate_daily
    ADD CONSTRAINT fx_status_ck    CHECK (record_status IN ('ACTIVE','EXACT_DUPLICATE')),
    ADD CONSTRAINT fx_duplicate_ck CHECK ((duplicate_of_source_id IS NOT NULL) = (record_status = 'EXACT_DUPLICATE')),
    -- holds on all 425 rows
    ADD CONSTRAINT fx_band_ck      CHECK (lowest_rate_ngn_per_usd <= highest_rate_ngn_per_usd),
    ADD CONSTRAINT fx_rate_ck      CHECK (nfem_rate_ngn_per_usd > 0),
    ADD CONSTRAINT fx_turnover_ck  CHECK (nfem_turnover_usd IS NULL OR nfem_turnover_usd >= 0);

-- =====================================================================
-- PARTIAL UNIQUE INDEXES
-- =====================================================================

-- exactly one ACTIVE record per FX date (duplicates are labelled, not deleted)
CREATE UNIQUE INDEX IF NOT EXISTS fx_active_date_uix
    ON core.fact_fx_rate_daily (observation_date)
    WHERE record_status = 'ACTIVE';

-- exactly one current period per tariff class WITHIN AN ORDER (correction 3).
-- Scoped to the order, not the DisCo: a DisCo could publish more than one
-- order, and the rule is a property of the order's own table.
CREATE UNIQUE INDEX IF NOT EXISTS tariff_current_period_uix
    ON core.fact_electricity_tariff (order_id, tariff_class_id)
    WHERE is_current_period;

-- =====================================================================
-- DELIBERATELY NOT DECLARED
--
-- 1. lowest <= nfem_rate <= highest on fact_fx_rate_daily.
--    Fails on 5 of 425 rows: the closing rate falls outside the published
--    band on 4 days, and on 2026-03-06 the headline NFEM rate itself
--    (1393.2556) sits below the published low (1398.0000). This is
--    published CBN data, not a cleaning error. Surfaced by
--    mart.v_fx_band_exceptions instead of being forced into a rule.
--
-- 2. nfem_deal_count = 0 implies nfem_turnover_usd IS NULL.
--    297 rows fit; 3 have a real deal count with NULL turnover and 1 has a
--    literal 0 turnover with populated interbank. The blank-versus-zero
--    distinction is real and irregular and must not be flattened.
-- =====================================================================
