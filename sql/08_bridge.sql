-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 08. Anomaly bridge + BI-facing anomaly register
--
-- Design: docs/data_design/postgres_schema_design.md  (section 7)
--
-- source_anomaly stays VERBATIM on every fact - it is provenance and is
-- never re-serialised. This bridge is DERIVED from it so that Power BI,
-- Tableau and Cognos never have to split a string on '|' or ';'.
--
-- Idempotent. Safe to re-run.
-- =====================================================================

SET search_path = core, public;

DROP TABLE IF EXISTS core.bridge_fact_anomaly CASCADE;
CREATE TABLE core.bridge_fact_anomaly (
    fact_table text   NOT NULL,
    fact_id    bigint NOT NULL,
    flag_code  text   NOT NULL REFERENCES core.dim_anomaly_flag(flag_code),
    CONSTRAINT bridge_fact_anomaly_pk PRIMARY KEY (fact_table, fact_id, flag_code),
    CONSTRAINT bridge_fact_table_ck CHECK (fact_table IN (
        'fact_petrol_price_monthly',
        'fact_diesel_price_monthly',
        'fact_lpg_price_monthly',
        'fact_transport_fare_state_monthly',
        'fact_transport_fare_zone_monthly',
        'fact_food_price_national_monthly',
        'fact_food_price_zone_monthly',
        'fact_food_extreme_callout',
        'fact_cpi_state_monthly',
        'fact_electricity_tariff'))
);
COMMENT ON TABLE core.bridge_fact_anomaly IS
  'One row per (fact row x anomaly flag). Derived from the verbatim source_anomaly '
  'text, which remains authoritative. fact_id cannot carry a real FK because it '
  'points at ten different tables - that integrity is asserted by the independent '
  'database audit, not by DDL.';

CREATE INDEX IF NOT EXISTS bridge_flag_ix  ON core.bridge_fact_anomaly (flag_code);
CREATE INDEX IF NOT EXISTS bridge_table_ix ON core.bridge_fact_anomaly (fact_table, fact_id);

-- ---------------------------------------------------------------------
-- Populate from the derived flag arrays. Re-runnable.
-- ---------------------------------------------------------------------
TRUNCATE core.bridge_fact_anomaly;

INSERT INTO core.bridge_fact_anomaly (fact_table, fact_id, flag_code)
SELECT 'fact_petrol_price_monthly', petrol_id, trim(flag)
FROM core.fact_petrol_price_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_diesel_price_monthly', diesel_id, trim(flag)
FROM core.fact_diesel_price_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_lpg_price_monthly', lpg_id, trim(flag)
FROM core.fact_lpg_price_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_transport_fare_state_monthly', transport_state_id, trim(flag)
FROM core.fact_transport_fare_state_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_transport_fare_zone_monthly', transport_zone_id, trim(flag)
FROM core.fact_transport_fare_zone_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_food_price_national_monthly', food_national_id, trim(flag)
FROM core.fact_food_price_national_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_food_price_zone_monthly', food_zone_id, trim(flag)
FROM core.fact_food_price_zone_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_food_extreme_callout', food_callout_id, trim(flag)
FROM core.fact_food_extreme_callout, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL
UNION ALL
SELECT 'fact_cpi_state_monthly', cpi_id, trim(flag)
FROM core.fact_cpi_state_monthly, unnest(source_anomaly_flags) AS flag
WHERE source_anomaly_flags IS NOT NULL;

-- NERC carries its anomaly on the ORDER, not on each tariff row, so the
-- bridge points at the order's fact rows through their order_id.
INSERT INTO core.bridge_fact_anomaly (fact_table, fact_id, flag_code)
SELECT DISTINCT 'fact_electricity_tariff', f.tariff_id, trim(flag)
FROM core.fact_electricity_tariff f
JOIN core.dim_nerc_order o USING (order_id),
     unnest(regexp_split_to_array(o.source_anomaly, '[|;]')) AS flag
WHERE o.source_anomaly IS NOT NULL AND o.source_anomaly <> '';

-- =====================================================================
-- BI-facing register: what BI actually consumes. No string parsing.
-- =====================================================================
SET search_path = mart, core, public;

CREATE OR REPLACE VIEW mart.v_anomaly_register AS
WITH rows_with_context AS (
    SELECT 'fact_petrol_price_monthly'::text AS fact_table, f.petrol_id AS fact_id,
           'PETROL'::text AS dataset, f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly,
           f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_petrol_price_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_diesel_price_monthly', f.diesel_id, 'DIESEL', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_diesel_price_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_lpg_price_monthly', f.lpg_id, 'LPG', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_lpg_price_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_transport_fare_state_monthly', f.transport_state_id, 'TRANSPORT_STATE', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_transport_fare_state_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_transport_fare_zone_monthly', f.transport_zone_id, 'TRANSPORT_ZONE', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_transport_fare_zone_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_food_price_national_monthly', f.food_national_id, 'FOOD_NATIONAL', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_food_price_national_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_food_price_zone_monthly', f.food_zone_id, 'FOOD_ZONE', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_food_price_zone_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_food_extreme_callout', f.food_callout_id, 'FOOD_CALLOUT', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_food_extreme_callout f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_cpi_state_monthly', f.cpi_id, 'CPI', f.observation_month, f.release_month,
           g.geography_type, g.geography_name, f.source_anomaly, f.source_file, f.source_sheet, f.source_cell_reference
    FROM core.fact_cpi_state_monthly f JOIN mart.v_geography g USING (geography_id)
    WHERE f.source_anomaly IS NOT NULL
  UNION ALL
    SELECT 'fact_electricity_tariff', f.tariff_id, 'NERC', o.order_effective_date, o.order_effective_date,
           'DISCO', d.disco_code, o.source_anomaly, o.source_file, o.source_table_label, NULL
    FROM core.fact_electricity_tariff f
    JOIN core.dim_nerc_order o USING (order_id)
    JOIN core.dim_disco d USING (disco_id)
    WHERE o.source_anomaly IS NOT NULL
)
SELECT r.dataset, r.fact_table, r.fact_id,
       r.observation_month, r.release_month,
       r.geography_type, r.geography_name,
       b.flag_code, a.flag_meaning, a.decision_ref, a.affects_analysis,
       r.source_anomaly AS source_anomaly_verbatim,
       r.source_file, r.source_sheet, r.source_cell_reference
FROM rows_with_context r
JOIN core.bridge_fact_anomaly b
     ON b.fact_table = r.fact_table AND b.fact_id = r.fact_id
JOIN core.dim_anomaly_flag a ON a.flag_code = b.flag_code;

COMMENT ON VIEW mart.v_anomaly_register IS
  'One row per flagged fact row per flag, with the flag meaning and decision '
  'reference resolved. This is what BI consumes - it never needs to parse a '
  'separator. source_anomaly_verbatim is carried alongside for provenance.';
