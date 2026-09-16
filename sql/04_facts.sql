-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 04. Fact tables (12 tables, 29,032 rows)
--
-- Design: docs/data_design/postgres_schema_design.md  (section 4)
--
-- Rules applied throughout:
--   * every measure is unconstrained `numeric` - exact decimal
--     preservation, no float drift, no trailing-zero padding
--   * facts reference geography_id only; geography_type/state/zone/
--     is_aggregate live in dim_geography (correction 2)
--   * source_anomaly is stored VERBATIM; the flags array is derived
--   * twelve canonical grains stay twelve tables - nothing is merged
--
-- FKs, CHECK and UNIQUE constraints are added in 05_constraints.sql
-- after the data is loaded, so a failure there names the load, not the
-- design.
--
-- Idempotent. Safe to re-run.
-- =====================================================================

SET search_path = core, public;

-- Derived array of anomaly flags. Food and CPI separate flags with '|',
-- petrol with ';'. Splitting on both means BI and SQL never guess, while
-- the verbatim source_anomaly text remains authoritative.
-- (Expression repeated per table because a generated column cannot call
-- a non-immutable or later-defined function safely across restores.)

-- ---------------------------------------------------------------------
-- 1. fact_fx_rate_daily  (425)   CBN NFEM - NATIONAL, daily
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_fx_rate_daily CASCADE;
CREATE TABLE core.fact_fx_rate_daily (
    fx_id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id                   integer NOT NULL,
    observation_date            date    NOT NULL,
    source_date_label           text    NOT NULL,
    geography_id                integer NOT NULL,

    nfem_rate_ngn_per_usd       numeric NOT NULL,
    highest_rate_ngn_per_usd    numeric NOT NULL,
    lowest_rate_ngn_per_usd     numeric NOT NULL,
    closing_rate_ngn_per_usd    numeric NOT NULL,
    simple_avg_rate_ngn_per_usd numeric NOT NULL,
    interbank_turnover_usd      numeric,
    interbank_deal_count        integer,
    nfem_turnover_usd           numeric,
    nfem_deal_count             integer,

    record_status               text    NOT NULL,
    duplicate_of_source_id      integer,
    source_file                 text    NOT NULL
);
COMMENT ON TABLE core.fact_fx_rate_daily IS
  'CBN NFEM daily rate, 2025-01-02 to 2026-09-11. 419 ACTIVE + 6 EXACT_DUPLICATE: '
  'redundant records are labelled, never deleted, so the table reconciles row-for-row '
  'with the raw snapshot.';

-- ---------------------------------------------------------------------
-- 2. fact_petrol_price_monthly  (2,040)   STATE + ZONE + NATIONAL
--    (renamed from fact_fuel_price_monthly - correction 1)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_petrol_price_monthly CASCADE;
CREATE TABLE core.fact_petrol_price_monthly (
    petrol_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month       date    NOT NULL,
    observation_month   date    NOT NULL,
    geography_id        integer NOT NULL,
    geography_raw_label text    NOT NULL,

    price_ngn_per_litre numeric NOT NULL,
    unit                text    NOT NULL,
    is_primary_release  boolean NOT NULL,

    source_period_label text,
    header_row_used     integer,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_petrol_price_monthly IS
  'NBS Petrol (PMS) Price Watch. Kept separate from diesel: separate publications, '
  'independently moving header rows, different zone-block structure (petrol 120 rows '
  'per release, diesel 132).';

-- ---------------------------------------------------------------------
-- 3. fact_diesel_price_monthly  (2,244)   STATE + ZONE + NATIONAL
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_diesel_price_monthly CASCADE;
CREATE TABLE core.fact_diesel_price_monthly (
    diesel_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month       date    NOT NULL,
    observation_month   date    NOT NULL,
    geography_id        integer NOT NULL,
    geography_raw_label text    NOT NULL,

    price_ngn_per_litre numeric NOT NULL,
    unit                text    NOT NULL,
    is_primary_release  boolean NOT NULL,

    source_period_label text,
    header_row_used     integer,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_diesel_price_monthly IS 'NBS Diesel (AGO) Price Watch.';

-- ---------------------------------------------------------------------
-- 4. fact_lpg_price_monthly  (4,224)   STATE + ZONE + NATIONAL x 2 sizes
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_lpg_price_monthly CASCADE;
CREATE TABLE core.fact_lpg_price_monthly (
    lpg_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month       date    NOT NULL,
    observation_month   date    NOT NULL,
    cylinder_size_kg    numeric NOT NULL,
    geography_id        integer NOT NULL,
    geography_raw_label text    NOT NULL,

    refill_price_ngn    numeric NOT NULL,
    unit                text    NOT NULL,
    is_primary_release  boolean NOT NULL,

    source_period_label text,
    source_banner_text  text,
    header_row_used     integer,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_lpg_price_monthly IS
  'NBS Cooking Gas (LPG) Price Watch, 5 kg and 12.5 kg. TWO rows per state-month - '
  'never join this to another state fact without reducing by cylinder_size_kg first.';

-- ---------------------------------------------------------------------
-- 5. fact_lpg_extreme_callout  (193)   STATE callouts
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_lpg_extreme_callout CASCADE;
CREATE TABLE core.fact_lpg_extreme_callout (
    lpg_callout_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month     date    NOT NULL,
    observation_month date    NOT NULL,
    cylinder_size_kg  numeric NOT NULL,
    extreme_type      text    NOT NULL,
    rank_within_block integer NOT NULL,
    geography_id      integer NOT NULL,

    price_ngn         numeric NOT NULL,
    is_shared_extreme boolean NOT NULL,
    raw_callout_text  text    NOT NULL,
    tie_member_count  integer NOT NULL,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_lpg_extreme_callout IS
  'Highest/lowest state callouts only - an extremes sample, NOT a state price series. '
  'The one cell that produces two rows is the documented tie (is_shared_extreme).';

-- ---------------------------------------------------------------------
-- 6. fact_transport_fare_state_monthly  (3,230)   STATE + NATIONAL
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_transport_fare_state_monthly CASCADE;
CREATE TABLE core.fact_transport_fare_state_monthly (
    transport_state_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month       date    NOT NULL,
    observation_month   date    NOT NULL,
    geography_id        integer NOT NULL,
    geography_raw_label text    NOT NULL,
    transport_mode_id   integer NOT NULL,
    transport_mode_raw  text    NOT NULL,

    fare_ngn            numeric NOT NULL,
    unit                text    NOT NULL,

    source_period_label text,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_transport_fare_state_monthly IS
  'NBS Transport Fare Watch, state table. Current month only - no release overlap. '
  'FIVE rows per state-month (one per mode).';

-- ---------------------------------------------------------------------
-- 7. fact_transport_fare_zone_monthly  (1,785)   ZONE + NATIONAL
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_transport_fare_zone_monthly CASCADE;
CREATE TABLE core.fact_transport_fare_zone_monthly (
    transport_zone_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month       date    NOT NULL,
    observation_month   date    NOT NULL,
    geography_id        integer NOT NULL,
    geography_raw_label text    NOT NULL,
    transport_mode_id   integer NOT NULL,
    transport_mode_raw  text    NOT NULL,

    fare_ngn            numeric NOT NULL,
    unit                text    NOT NULL,
    period_position     text    NOT NULL,
    is_primary_release  boolean NOT NULL,

    source_period_label text,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_transport_fare_zone_monthly IS
  'NBS Transport Fare Watch, zone table. Publishes three periods per release, '
  'unlike the state table - which is why the two have different keys and stay separate.';

-- ---------------------------------------------------------------------
-- 8. fact_food_price_national_monthly  (2,142)   NATIONAL
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_food_price_national_monthly CASCADE;
CREATE TABLE core.fact_food_price_national_monthly (
    food_national_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month      date    NOT NULL,
    observation_month  date    NOT NULL,
    item_id            integer NOT NULL,
    item_label_raw     text    NOT NULL,
    geography_id       integer NOT NULL,

    avg_price_ngn      numeric,            -- NULL when NOT_REPORTED; never zero
    value_status       text    NOT NULL,
    period_position    text    NOT NULL,
    is_primary_release boolean NOT NULL,

    source_period_label text,
    header_row_used     integer,
    header_label_raw    text,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_food_price_national_monthly IS
  'NBS Selected Food Price Watch, national. 195 NULL prices, all NOT_REPORTED - '
  'a blank is never a zero.';

-- ---------------------------------------------------------------------
-- 9. fact_food_price_zone_monthly  (4,284)   ZONE
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_food_price_zone_monthly CASCADE;
CREATE TABLE core.fact_food_price_zone_monthly (
    food_zone_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month     date    NOT NULL,
    observation_month date    NOT NULL,
    item_id           integer NOT NULL,
    item_label_raw    text    NOT NULL,
    geography_id      integer NOT NULL,
    zone_raw_label    text    NOT NULL,

    avg_price_ngn     numeric NOT NULL,
    value_status      text    NOT NULL,
    observation_month_basis text NOT NULL,

    header_row_used     integer,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_food_price_zone_monthly IS
  'NBS food, six zones. Food has a HARD SOURCE CEILING at zone level - there are no '
  'state-level food prices anywhere in the corpus, and none may be derived from these.';

-- ---------------------------------------------------------------------
-- 10. fact_food_extreme_callout  (1,428)   STATE callouts
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_food_extreme_callout CASCADE;
CREATE TABLE core.fact_food_extreme_callout (
    food_callout_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month     date    NOT NULL,
    observation_month date    NOT NULL,
    item_id           integer NOT NULL,
    item_label_raw    text    NOT NULL,
    extreme_type      text    NOT NULL,
    geography_id      integer NOT NULL,
    state_raw_label   text    NOT NULL,

    price_ngn         numeric NOT NULL,
    is_shared_extreme boolean NOT NULL,
    raw_callout_text  text    NOT NULL,
    observation_month_basis text NOT NULL,

    header_row_used     integer,
    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_food_extreme_callout IS
  'The ONLY place state names appear in the food dataset, and only as the highest and '
  'lowest state per item per month. Not a state series.';

-- ---------------------------------------------------------------------
-- 11. fact_cpi_state_monthly  (6,512)   STATE
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_cpi_state_monthly CASCADE;
CREATE TABLE core.fact_cpi_state_monthly (
    cpi_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_month     date    NOT NULL,
    observation_month date    NOT NULL,
    geography_id      integer NOT NULL,
    state_raw_label   text    NOT NULL,
    cpi_group         text    NOT NULL,
    cpi_group_raw     text    NOT NULL,
    cpi_measure_id    integer NOT NULL,

    value             numeric NOT NULL,
    base_period       text    NOT NULL,
    period_position   text    NOT NULL,
    period_label_raw  text    NOT NULL,
    is_primary_release boolean NOT NULL,
    value_status      text    NOT NULL,

    comparability_warning text NOT NULL,
    extraction_method     text NOT NULL,

    source_anomaly      text,
    source_anomaly_flags text[] GENERATED ALWAYS AS (
        CASE WHEN source_anomaly IS NULL OR source_anomaly = '' THEN NULL
             ELSE regexp_split_to_array(source_anomaly, '[|;]') END) STORED,

    source_file          text NOT NULL,
    source_member        text,
    source_sheet         text NOT NULL,
    source_row           integer NOT NULL,
    source_column_index  integer NOT NULL,
    source_cell_reference text NOT NULL
);
COMMENT ON TABLE core.fact_cpi_state_monthly IS
  'NBS CPI state table (Table-5) only. comparability_warning is carried on EVERY row: '
  'index LEVELS must never be used to rank states by cost - only CHANGE_* rates may be '
  'compared across states. SIX rows per state-month (2 groups x 3 measures).';

-- ---------------------------------------------------------------------
-- 12. fact_electricity_tariff  (525)   DISCO - an island, no state FK
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.fact_electricity_tariff CASCADE;
CREATE TABLE core.fact_electricity_tariff (
    tariff_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id           integer NOT NULL,
    tariff_class_id    integer NOT NULL,
    tariff_period_id   integer NOT NULL,

    tariff_ngn_per_kwh numeric NOT NULL,
    unit               text    NOT NULL,
    is_current_period  boolean NOT NULL,

    tariff_class_raw   text NOT NULL,
    disco_raw_label    text NOT NULL,
    period_label_raw   text NOT NULL,
    period_position    text NOT NULL,
    source_row_label   text NOT NULL,
    source_column_index integer NOT NULL
);
COMMENT ON TABLE core.fact_electricity_tariff IS
  'A validated July 2025 cross-section of 11 complete NERC MYTO tariff tables - NOT a '
  'tariff history. Has NO geography FK: DisCo licence areas cross state boundaries, so '
  'this table cannot be joined to any state-level dataset (D-44).';
