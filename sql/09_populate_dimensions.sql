-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 09. Populate dimensions from staging  (14 tables, 341 rows)
--
-- Reads staging only. Every cast is explicit; empty string becomes NULL,
-- never zero.
--
-- Run AFTER 02_staging.sql has been loaded and 03_dimensions.sql created.
-- Idempotent: each section truncates before inserting.
-- =====================================================================

SET search_path = core, staging, public;

TRUNCATE core.dim_state_alias_observed,
         core.dim_state_alias,
         core.dim_geography,
         core.dim_state,
         core.dim_zone,
         core.dim_month,
         core.dim_food_item,
         core.dim_transport_mode,
         core.dim_cpi_measure,
         core.dim_nerc_order,
         core.dim_disco,
         core.dim_tariff_class,
         core.dim_tariff_period,
         core.dim_anomaly_flag
    RESTART IDENTITY CASCADE;

-- ---------------------------------------------------------------------
-- dim_zone (6)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_zone (zone_name)
SELECT DISTINCT zone FROM staging.stg_ref_state_zone
WHERE zone IS NOT NULL AND zone <> ''
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_state (37)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_state (state_name, zone_id)
SELECT DISTINCT s.state, z.zone_id
FROM staging.stg_ref_state_zone s
JOIN core.dim_zone z ON z.zone_name = s.zone
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_state_alias (39) - the join key, unique by construction
-- ---------------------------------------------------------------------
INSERT INTO core.dim_state_alias
    (alias_normalised, state_id, observed_aliases, alias_variant_count, alias_source, observed_in)
SELECT a.alias_normalised, s.state_id, a.observed_aliases,
       nullif(a.alias_variant_count,'')::integer, a.alias_source, a.observed_in
FROM staging.stg_ref_state_zone a
JOIN core.dim_state s ON s.state_name = a.state;

-- ---------------------------------------------------------------------
-- dim_state_alias_observed (77) - PROVENANCE ONLY
-- ---------------------------------------------------------------------
INSERT INTO core.dim_state_alias_observed
    (alias_raw, alias_normalised, state_name, zone_name, alias_source, observed_in)
SELECT alias_raw, alias_normalised, state, zone, alias_source, observed_in
FROM staging.stg_ref_state_alias_observed;

-- ---------------------------------------------------------------------
-- dim_geography (44 = 37 STATE + 6 ZONE + 1 NATIONAL)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_geography (geography_type, geography_name, state_id, zone_id, is_aggregate)
SELECT 'STATE', s.state_name, s.state_id, s.zone_id, false
FROM core.dim_state s
UNION ALL
SELECT 'ZONE', z.zone_name, NULL, z.zone_id, true
FROM core.dim_zone z
UNION ALL
SELECT 'NATIONAL', 'Nigeria', NULL, NULL, true;

-- ---------------------------------------------------------------------
-- dim_month - spine covering every month used anywhere in the facts
-- ---------------------------------------------------------------------
WITH all_months AS (
    SELECT release_month AS m FROM staging.stg_petrol_price_monthly
    UNION SELECT observation_month FROM staging.stg_petrol_price_monthly
    UNION SELECT release_month     FROM staging.stg_diesel_price_monthly
    UNION SELECT observation_month FROM staging.stg_diesel_price_monthly
    UNION SELECT release_month     FROM staging.stg_cooking_gas_price_monthly
    UNION SELECT observation_month FROM staging.stg_cooking_gas_price_monthly
    UNION SELECT release_month     FROM staging.stg_cooking_gas_extreme_callout
    UNION SELECT observation_month FROM staging.stg_cooking_gas_extreme_callout
    UNION SELECT release_month     FROM staging.stg_transport_fare_state_monthly
    UNION SELECT observation_month FROM staging.stg_transport_fare_state_monthly
    UNION SELECT release_month     FROM staging.stg_transport_fare_zone_monthly
    UNION SELECT observation_month FROM staging.stg_transport_fare_zone_monthly
    UNION SELECT release_month     FROM staging.stg_food_price_national_monthly
    UNION SELECT observation_month FROM staging.stg_food_price_national_monthly
    UNION SELECT release_month     FROM staging.stg_food_price_zone_monthly
    UNION SELECT observation_month FROM staging.stg_food_price_zone_monthly
    UNION SELECT release_month     FROM staging.stg_food_price_extreme_callout
    UNION SELECT observation_month FROM staging.stg_food_price_extreme_callout
    UNION SELECT release_month     FROM staging.stg_cpi_state_monthly
    UNION SELECT observation_month FROM staging.stg_cpi_state_monthly
),
bounds AS (SELECT min(m::date) AS lo, max(m::date) AS hi FROM all_months)
INSERT INTO core.dim_month (month_date, year, month_of_year, month_label, quarter)
SELECT d::date,
       EXTRACT(YEAR    FROM d)::int,
       EXTRACT(MONTH   FROM d)::int,
       to_char(d, 'YYYY-MM'),
       EXTRACT(QUARTER FROM d)::int
FROM bounds, generate_series(bounds.lo, bounds.hi, interval '1 month') d;

-- ---------------------------------------------------------------------
-- dim_food_item (42); 19 units legitimately NULL
-- ---------------------------------------------------------------------
INSERT INTO core.dim_food_item
    (item_code, item_label, item_label_normalised, observed_aliases,
     alias_variant_count, unit, unit_source, unit_evidence, observed_in)
SELECT item_code, item_label, item_label_normalised, observed_aliases,
       nullif(alias_variant_count,'')::integer,
       nullif(unit,''), nullif(unit_source,''), nullif(unit_evidence,''), observed_in
FROM staging.stg_ref_food_item;

-- ---------------------------------------------------------------------
-- dim_transport_mode (5 from 6 reference rows)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_transport_mode (transport_mode, raw_label, normalised_label, match_prefix, unit)
SELECT transport_mode,
       min(raw_label), min(normalised_label), min(match_prefix),
       'NGN per journey'
FROM staging.stg_ref_transport_mode
GROUP BY transport_mode
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_cpi_measure (3) - derived from the data, so an unexpected
-- measure/unit pairing fails the dimension's own CHECK
-- ---------------------------------------------------------------------
INSERT INTO core.dim_cpi_measure (measure, unit, measure_label)
SELECT DISTINCT measure, unit,
       CASE measure WHEN 'INDEX'          THEN 'CPI index level, 2024 = 100'
                    WHEN 'CHANGE_MOM_PCT' THEN 'Month-on-month change, per cent'
                    WHEN 'CHANGE_YOY_PCT' THEN 'Year-on-year change, per cent' END
FROM staging.stg_cpi_state_monthly
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_disco (12)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_disco
    (disco_code, disco_official_name, observed_aliases, alias_variant_count,
     alias_normalised_keys, state_mapping, notes)
SELECT disco_code, disco_official_name, observed_aliases,
       nullif(alias_variant_count,'')::integer,
       alias_normalised_keys, state_mapping, nullif(notes,'')
FROM staging.stg_ref_disco;

-- ---------------------------------------------------------------------
-- dim_nerc_order (11) - order-level metadata lifted out of the fact
-- ---------------------------------------------------------------------
INSERT INTO core.dim_nerc_order
    (order_number, order_number_raw, disco_id, source_file,
     order_effective_date, order_effective_date_raw,
     order_signed_date, signing_date_raw, signing_date_status,
     website_publication_date, vat_treatment, extraction_method,
     validation_status, source_page, source_table_label, source_anomaly)
SELECT DISTINCT
       t.order_number, t.order_number_raw, d.disco_id, t.source_file,
       t.order_effective_date::date, t.order_effective_date_raw,
       nullif(t.order_signed_date,'')::date, nullif(t.signing_date_raw,''),
       t.signing_date_status,
       nullif(t.website_publication_date,'')::date,
       t.vat_treatment, t.extraction_method, t.validation_status,
       t.source_page::integer, t.source_table_label, nullif(t.source_anomaly,'')
FROM staging.stg_electricity_tariff_disco_period t
JOIN core.dim_disco d ON d.disco_code = t.disco_code;

-- ---------------------------------------------------------------------
-- dim_tariff_class (17)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_tariff_class (tariff_class, service_band, mdclass)
SELECT DISTINCT tariff_class, service_band, mdclass
FROM staging.stg_electricity_tariff_disco_period
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_tariff_period (3)
--
-- period_label_raw has five spellings across three positions because the
-- source mixes an en dash and a hyphen in the same label. The position,
-- start and end are what identify the period; min() picks one stable
-- spelling for display and the variants stay in the fact's own
-- period_label_raw.
-- ---------------------------------------------------------------------
INSERT INTO core.dim_tariff_period (period_position, period_start, period_end, period_label_raw)
SELECT period_position, period_start::date, period_end::date, min(period_label_raw)
FROM staging.stg_electricity_tariff_disco_period
GROUP BY period_position, period_start::date, period_end::date
ORDER BY 1;

-- ---------------------------------------------------------------------
-- dim_anomaly_flag (14) - documentation as data
--
-- This is a curated seed, not derived. The loader asserts that the set of
-- flags actually present in the facts equals this set exactly, so a new
-- flag appearing in a future reload FAILS rather than passing unexplained.
-- ---------------------------------------------------------------------
INSERT INTO core.dim_anomaly_flag (flag_code, flag_meaning, decision_ref, affects_analysis) VALUES
 ('MEMBER_FILENAME_YEAR_WRONG',
  'The workbook inside the ZIP carries the wrong year in its filename: PMS_JANUARY_2025.xlsx ships inside the January 2026 release. The sheet contents are correct; only the member filename is wrong.',
  'rulebook 2a', false),
 ('ZONE_BLOCK_BELOW_STATE_BLOCK',
  'The zone table sits below the state table in the same sheet rather than beside it, so the two blocks had to be separated by content rather than by column position.',
  'rulebook 2a', false),
 ('TITLE_ROW_MONTH_WRONG',
  'The sheet title row names a different month from the period headers. The period headers are authoritative.',
  'rulebook 2a', false),
 ('PERIOD_HEADER_DAY_NOT_14',
  'The diesel period header carries a day other than the 14th, which is the convention in the rest of the corpus. The month is unaffected.',
  'rulebook 3a', false),
 ('LPG_12_5KG_KEBBI_LABELLED_TARABA',
  'In the 2025 12.5 kg block, Kebbi is published under the label Taraba. Corrected only where all five fingerprint conditions hold - never as a global Taraba to Kebbi substitution.',
  'rulebook 4a', false),
 ('HEADER_ITEM_LABELS_PLURAL',
  'The food header reads "Item Labels" rather than "Item Label" in one release. Anchor matching accepts both.',
  'D-30', false),
 ('STALE_SHEET_NAME',
  'The worksheet name names an earlier month than the release: two food workbooks name their sheet "Selected Food Dec 2024". The sheet name is never used to determine the month.',
  'D-30', false),
 ('NATIONAL_ABOVE_ALL_ZONES',
  'The published national average sits above every one of its own zone averages, which the weighted identity says is impossible. March 2025 crate of eggs. Preserved as published.',
  'D-32', true),
 ('ZONE_ABOVE_STATE_MAXIMUM',
  'A published zone average exceeds the published highest-state price for the same item and month. Six July 2025 cells. Both values preserved because neither can be shown to be the wrong one.',
  'D-33', true),
 ('DUPLICATE_PERIOD_HEADER_RESOLVED_BY_POSITION',
  'Two columns carry the identical header "Average of Mar-24"; the second is really March 2025, proven by cross-checking the April release. Resolved by column position.',
  'D-29', false),
 ('PUBLISHED_CHANGE_ROUNDED_TO_2DP',
  'NBS published this change rate hand-rounded to two decimals (Borno All Items, August 2025, exactly 26.31) where every other value in the column carries 14-15 decimals. Preserved byte-exact, never recomputed.',
  'D-49', false),
 ('STATE_LABEL_NASSARAWA_DOUBLE_S',
  'The source spells Nasarawa as "Nassarawa". Resolved to the canonical state while state_raw_label keeps the published spelling. Not a one-way correction: six releases use the double-s form and twelve do not.',
  'D-50', false),
 ('STATE_VALUE_ALIGNMENT_DISPUTED',
  'The April 2025 CPI release assigns 67 of 74 values to states that the May 2025 and April 2026 releases both contradict. Published exactly as issued, demoted to is_primary_release = FALSE. Exclude from a first-publication view.',
  'D-52', true),
 ('SIGNING_PAGE_NOT_IN_TEXT_LAYER',
  'The order signature page is an image in all 11 processed NERC orders, so no signing date is recoverable. Recorded as absent with a reason rather than inferred from the effective month.',
  'D-39', false);
