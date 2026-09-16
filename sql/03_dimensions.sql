-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 03. Dimensions (14 tables, 341 rows)
--
-- Design: docs/data_design/postgres_schema_design.md  (section 3)
--
-- Geography structural rules live HERE, in dim_geography, declared once,
-- rather than being duplicated onto six fact tables (correction 2).
--
-- Idempotent. Safe to re-run.
-- =====================================================================

SET search_path = core, public;

-- ---------------------------------------------------------------------
-- dim_zone  (6)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_zone CASCADE;
CREATE TABLE core.dim_zone (
    zone_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    zone_name text NOT NULL,
    CONSTRAINT dim_zone_name_uk UNIQUE (zone_name)
);
COMMENT ON TABLE core.dim_zone IS 'The six Nigerian geopolitical zones.';

-- ---------------------------------------------------------------------
-- dim_state  (37: 36 states + Abuja for the FCT)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_state CASCADE;
CREATE TABLE core.dim_state (
    state_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    state_name text    NOT NULL,
    zone_id    integer NOT NULL REFERENCES core.dim_zone(zone_id),
    CONSTRAINT dim_state_name_uk UNIQUE (state_name)
);
COMMENT ON TABLE core.dim_state IS
  '36 states plus Abuja (FCT). Zone comes from ref_state_zone, never guessed from data.';

-- ---------------------------------------------------------------------
-- dim_state_alias  (39)  -- THE JOIN KEY: unique by construction
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_state_alias CASCADE;
CREATE TABLE core.dim_state_alias (
    alias_normalised    text    PRIMARY KEY,
    state_id            integer NOT NULL REFERENCES core.dim_state(state_id),
    observed_aliases    text,
    alias_variant_count integer,
    alias_source        text,
    observed_in         text
);
COMMENT ON TABLE core.dim_state_alias IS
  'Resolution lookup from ref_state_zone. Exactly one row per key - a join here '
  'can never multiply rows. This is the table to join to.';

-- ---------------------------------------------------------------------
-- dim_state_alias_observed  (77)  -- PROVENANCE ONLY, NEVER JOINED
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_state_alias_observed CASCADE;
CREATE TABLE core.dim_state_alias_observed (
    alias_observed_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alias_raw         text NOT NULL,
    alias_normalised  text NOT NULL,
    state_name        text NOT NULL,
    zone_name         text NOT NULL,
    alias_source      text,
    observed_in       text
);
COMMENT ON TABLE core.dim_state_alias_observed IS
  'The 77 raw spellings actually seen in the sources. PROVENANCE ONLY - it has '
  '77 rows over 39 keys, so joining to it would silently multiply observations.';

-- ---------------------------------------------------------------------
-- dim_geography  (44 = 37 STATE + 6 ZONE + 1 NATIONAL)
--
-- Owns the geography model. Facts reference geography_id and nothing
-- else; geography_type, state_id, zone_id and is_aggregate are declared
-- and constrained here once.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_geography CASCADE;
CREATE TABLE core.dim_geography (
    geography_id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    geography_type text    NOT NULL,
    geography_name text    NOT NULL,
    state_id       integer REFERENCES core.dim_state(state_id),
    zone_id        integer REFERENCES core.dim_zone(zone_id),
    is_aggregate   boolean NOT NULL,

    CONSTRAINT dim_geography_natural_uk UNIQUE (geography_type, geography_name),
    CONSTRAINT dim_geography_type_ck
        CHECK (geography_type IN ('STATE','ZONE','NATIONAL')),
    -- state is populated only on STATE rows
    CONSTRAINT dim_geography_state_ck
        CHECK ((geography_type = 'STATE') = (state_id IS NOT NULL)),
    -- zone is absent only on NATIONAL rows (STATE rows carry their own zone)
    CONSTRAINT dim_geography_zone_ck
        CHECK ((geography_type = 'NATIONAL') = (zone_id IS NULL)),
    -- everything that is not a single state is an aggregate
    CONSTRAINT dim_geography_aggregate_ck
        CHECK (is_aggregate = (geography_type <> 'STATE'))
);
COMMENT ON TABLE core.dim_geography IS
  'Four geographic levels preserved deliberately. geography_type rides on every '
  'row, so STATE/ZONE/NATIONAL survives every join. NEVER aggregate across '
  'geography_type: a SUM without a type filter counts the country three times.';

-- ---------------------------------------------------------------------
-- dim_month  (31: 2024-01 .. 2026-07, contiguous)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_month CASCADE;
CREATE TABLE core.dim_month (
    month_date    date    PRIMARY KEY,
    year          integer NOT NULL,
    month_of_year integer NOT NULL,
    month_label   text    NOT NULL,
    quarter       integer NOT NULL,
    CONSTRAINT dim_month_first_day_ck
        CHECK (month_date = date_trunc('month', month_date)::date),
    CONSTRAINT dim_month_parts_ck
        CHECK (month_of_year BETWEEN 1 AND 12 AND quarter BETWEEN 1 AND 4)
);
COMMENT ON TABLE core.dim_month IS
  'Month spine covering every release_month and observation_month in the corpus.';

-- ---------------------------------------------------------------------
-- dim_food_item  (42; 19 units legitimately NULL - units are never inferred)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_food_item CASCADE;
CREATE TABLE core.dim_food_item (
    item_id                integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_code              text    NOT NULL,
    item_label             text    NOT NULL,
    item_label_normalised  text,
    observed_aliases       text,
    alias_variant_count    integer,
    unit                   text,
    unit_source            text,
    unit_evidence          text,
    observed_in            text,
    CONSTRAINT dim_food_item_code_uk UNIQUE (item_code),
    -- a unit exists only when its evidence does
    CONSTRAINT dim_food_item_unit_ck
        CHECK ((unit IS NULL) = (unit_source IS NULL)),
    CONSTRAINT dim_food_item_unit_source_ck
        CHECK (unit_source IS NULL
               OR unit_source IN ('SPREADSHEET_LABEL','NBS_REPORT_PDF'))
);
COMMENT ON TABLE core.dim_food_item IS
  '42 items. 23 carry a unit (11 from a spreadsheet label, 12 from an NBS PDF '
  'price-anchored to the exact item); 19 are NULL because no source states one. '
  'Units are never inferred (D-36).';

-- ---------------------------------------------------------------------
-- dim_transport_mode  (5)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_transport_mode CASCADE;
CREATE TABLE core.dim_transport_mode (
    transport_mode_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transport_mode    text NOT NULL,
    raw_label         text,
    normalised_label  text,
    match_prefix      text,
    unit              text NOT NULL DEFAULT 'NGN per journey',
    CONSTRAINT dim_transport_mode_uk UNIQUE (transport_mode),
    CONSTRAINT dim_transport_mode_domain_ck
        CHECK (transport_mode IN
               ('AIR','BUS_INTERCITY','BUS_INTRACITY','OKADA','WATER'))
);
COMMENT ON TABLE core.dim_transport_mode IS
  'Five canonical modes from six observed raw labels.';

-- ---------------------------------------------------------------------
-- dim_cpi_measure  (3)  -- the D-48 rule, declared once
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_cpi_measure CASCADE;
CREATE TABLE core.dim_cpi_measure (
    cpi_measure_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    measure        text NOT NULL,
    unit           text NOT NULL,
    measure_label  text NOT NULL,
    CONSTRAINT dim_cpi_measure_uk UNIQUE (measure),
    CONSTRAINT dim_cpi_measure_domain_ck
        CHECK (measure IN ('INDEX','CHANGE_MOM_PCT','CHANGE_YOY_PCT')),
    -- an index and a rate never share an unlabelled numeric field (D-48)
    CONSTRAINT dim_cpi_measure_unit_ck
        CHECK ((measure = 'INDEX') = (unit = 'INDEX_2024_100')),
    CONSTRAINT dim_cpi_measure_unit_domain_ck
        CHECK (unit IN ('INDEX_2024_100','PERCENT'))
);
COMMENT ON TABLE core.dim_cpi_measure IS
  'Index levels and percentage changes are separated here so they can never be '
  'summed together. Their ranges overlap, so magnitude cannot tell them apart (D-48).';

-- ---------------------------------------------------------------------
-- dim_disco  (12; 11 represented in the data, APLE acquired but unused)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_disco CASCADE;
CREATE TABLE core.dim_disco (
    disco_id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    disco_code            text NOT NULL,
    disco_official_name   text NOT NULL,
    observed_aliases      text,
    alias_variant_count   integer,
    alias_normalised_keys text,
    state_mapping         text NOT NULL,
    notes                 text,
    CONSTRAINT dim_disco_code_uk UNIQUE (disco_code),
    -- licence areas cross state boundaries: no DisCo is mapped to a state (D-44)
    CONSTRAINT dim_disco_state_mapping_ck CHECK (state_mapping = 'NOT_MAPPED')
);
COMMENT ON TABLE core.dim_disco IS
  'DisCo licence areas cross state boundaries, so state_mapping is NOT_MAPPED on '
  'all 12 and electricity cannot be joined to state-level data (D-44).';

-- ---------------------------------------------------------------------
-- dim_nerc_order  (11)  -- order-level metadata (correction 3)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_nerc_order CASCADE;
CREATE TABLE core.dim_nerc_order (
    order_id                 integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_number             text    NOT NULL,
    order_number_raw         text    NOT NULL,
    disco_id                 integer NOT NULL REFERENCES core.dim_disco(disco_id),
    source_file              text    NOT NULL,
    order_effective_date     date    NOT NULL,
    order_effective_date_raw text    NOT NULL,
    order_signed_date        date,
    signing_date_raw         text,
    signing_date_status      text    NOT NULL,
    website_publication_date date,
    vat_treatment            text    NOT NULL,
    extraction_method        text    NOT NULL,
    validation_status        text    NOT NULL,
    source_page              integer NOT NULL,
    source_table_label       text    NOT NULL,
    source_anomaly           text,

    CONSTRAINT dim_nerc_order_number_uk UNIQUE (order_number),
    CONSTRAINT dim_nerc_order_file_uk   UNIQUE (source_file),
    -- only validated orders may enter analysis (D-12)
    CONSTRAINT dim_nerc_order_validated_ck
        CHECK (validation_status = 'VALIDATED'),
    -- the orders say nothing about VAT and nothing is inferred (D-43)
    CONSTRAINT dim_nerc_order_vat_ck
        CHECK (vat_treatment = 'UNSTATED'),
    -- a signing date is absent only with a recorded reason; nothing is inferred
    CONSTRAINT dim_nerc_order_signing_ck
        CHECK ((order_signed_date IS NULL) = (signing_date_status <> 'IN_TEXT_LAYER'))
);
COMMENT ON TABLE core.dim_nerc_order IS
  'The 11 processed July 2025 MYTO orders. Effective date, signing date and '
  'website publication date are three separate columns and are never conflated (D-39). '
  'order_signed_date is NULL on all 11 because page 7 is an image in every one.';

-- ---------------------------------------------------------------------
-- dim_tariff_class  (17)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_tariff_class CASCADE;
CREATE TABLE core.dim_tariff_class (
    tariff_class_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tariff_class    text NOT NULL,
    service_band    text NOT NULL,
    mdclass         text NOT NULL,
    CONSTRAINT dim_tariff_class_uk UNIQUE (tariff_class),
    CONSTRAINT dim_tariff_class_band_ck
        CHECK (service_band IN ('A','B','C','D','E','LIFELINE')),
    CONSTRAINT dim_tariff_class_md_ck
        CHECK (mdclass IN ('MD1','MD2','MD2_SPECIAL','NON_MD'))
);
COMMENT ON TABLE core.dim_tariff_class IS
  'Tariff classes are never collapsed. YEDC publishes 13, most DisCos 16, '
  'AEDC and IE 17. service_band and mdclass are functionally dependent on tariff_class.';

-- ---------------------------------------------------------------------
-- dim_tariff_period  (3)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_tariff_period CASCADE;
CREATE TABLE core.dim_tariff_period (
    tariff_period_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_position   text    NOT NULL,
    period_start      date    NOT NULL,
    period_end        date    NOT NULL,
    period_label_raw  text    NOT NULL,
    CONSTRAINT dim_tariff_period_uk UNIQUE (period_position),
    CONSTRAINT dim_tariff_period_pos_ck
        CHECK (period_position IN ('COLUMN_1','COLUMN_2','COLUMN_3')),
    CONSTRAINT dim_tariff_period_order_ck
        CHECK (period_end >= period_start)
);
COMMENT ON TABLE core.dim_tariff_period IS
  'The three period columns each July 2025 order publishes. These are historical '
  'context printed inside one order, NOT three observations over time (D-42).';

-- ---------------------------------------------------------------------
-- dim_anomaly_flag  (14)  -- documentation as data
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS core.dim_anomaly_flag CASCADE;
CREATE TABLE core.dim_anomaly_flag (
    flag_code        text PRIMARY KEY,
    flag_meaning     text NOT NULL,
    decision_ref     text,
    affects_analysis boolean NOT NULL
);
COMMENT ON TABLE core.dim_anomaly_flag IS
  'Every anomaly flag observed in the processed data, with its meaning and the '
  'decision-log entry that governs it. affects_analysis is TRUE when a row carrying '
  'the flag should normally be excluded or treated separately.';
