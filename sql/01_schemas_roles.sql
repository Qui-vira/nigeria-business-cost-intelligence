-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 01. Schemas, roles and grants
--
-- Design: docs/data_design/postgres_schema_design.md  (sections 1, 10)
-- Target: PostgreSQL 18
--
-- Idempotent. Safe to re-run.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Roles (NOLOGIN group roles; login roles are granted these separately
-- and their passwords are never stored in this repository)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nbci_owner') THEN
        CREATE ROLE nbci_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nbci_etl') THEN
        CREATE ROLE nbci_etl NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nbci_bi_reader') THEN
        CREATE ROLE nbci_bi_reader NOLOGIN;
    END IF;
END
$$;

COMMENT ON ROLE nbci_owner     IS 'Owns every object in staging, core and mart.';
COMMENT ON ROLE nbci_etl       IS 'Loads staging and core; refreshes materialized views.';
COMMENT ON ROLE nbci_bi_reader IS 'Read-only access to mart. No USAGE on staging or core.';

-- ---------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION nbci_owner;
CREATE SCHEMA IF NOT EXISTS core    AUTHORIZATION nbci_owner;
CREATE SCHEMA IF NOT EXISTS mart    AUTHORIZATION nbci_owner;

COMMENT ON SCHEMA staging IS
  'Import layer. Every column text. File byte integrity is established by SHA-256 in '
  'staging.load_audit; this layer validates parsed field-text preservation before typed '
  'casting. Parsed relational rows do not reproduce the original CSV bytes and are not '
  'claimed to.';
COMMENT ON SCHEMA core IS
  'Typed, keyed, constrained system of record. Twelve canonical grains stay twelve fact tables.';
COMMENT ON SCHEMA mart IS
  'Read-only analytical surface. Each view encodes a safety rule from the cleaning phase.';

-- ---------------------------------------------------------------------
-- Grants
--
-- The BI reader has NO USAGE on staging or core - not merely no SELECT.
-- It cannot see that those schemas exist. mart views are owned by
-- nbci_owner and PostgreSQL runs a view with its OWNER's privileges
-- (security_invoker defaults to false), so the reader queries mart
-- without holding any core privilege at all.
-- ---------------------------------------------------------------------

-- ETL: full DML on staging and core, read on mart
GRANT USAGE                      ON SCHEMA staging, core TO nbci_etl;
GRANT USAGE                      ON SCHEMA mart          TO nbci_etl;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
                                 ON ALL TABLES IN SCHEMA staging, core TO nbci_etl;
GRANT USAGE, SELECT              ON ALL SEQUENCES IN SCHEMA staging, core TO nbci_etl;
GRANT SELECT                     ON ALL TABLES IN SCHEMA mart TO nbci_etl;

-- BI reader: mart only
GRANT USAGE                      ON SCHEMA mart TO nbci_bi_reader;
GRANT SELECT                     ON ALL TABLES IN SCHEMA mart TO nbci_bi_reader;

-- Explicitly ensure the reader cannot reach staging or core
REVOKE ALL ON SCHEMA staging, core FROM nbci_bi_reader;

-- Future objects inherit the same shape
ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA staging, core
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO nbci_etl;
ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA staging, core
    GRANT USAGE, SELECT ON SEQUENCES TO nbci_etl;
ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA mart
    GRANT SELECT ON TABLES TO nbci_bi_reader, nbci_etl;

-- Nothing is granted to PUBLIC anywhere in this database
REVOKE ALL ON SCHEMA staging, core, mart FROM PUBLIC;
