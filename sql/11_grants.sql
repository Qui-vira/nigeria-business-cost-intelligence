-- =====================================================================
-- Nigeria Business Cost Intelligence - PostgreSQL analytical layer
-- 11. Object ownership and privileges  -- MUST RUN LAST
--
-- Design: docs/data_design/postgres_schema_design.md  (section 10)
--
-- WHY THIS FILE EXISTS
--
-- 01_schemas_roles.sql creates the roles and schemas and grants schema
-- USAGE. It CANNOT grant table privileges, because:
--
--   * GRANT ... ON ALL TABLES IN SCHEMA affects only tables that exist at
--     the moment it runs, and at that moment both schemas are empty; and
--   * ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner never fires, because
--     the objects are created by the connecting role, not by nbci_owner.
--
-- The result was a permission model that looked right and granted nothing:
-- nbci_etl had 0 privileges on 45 tables, and nbci_bi_reader could see the
-- mart schema but SELECT nothing in it. Schema USAGE is not access.
--
-- This script runs after every object exists and fixes both halves:
-- ownership first, then privileges.
--
-- Idempotent. Safe to re-run.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Ownership
--
-- The design states that mart views run with their OWNER's privileges,
-- which is what lets nbci_bi_reader query mart without holding any core
-- privilege. That is only true if nbci_owner actually owns them.
--
-- Sequences are deliberately skipped: a sequence owned by an identity
-- column follows its table's ownership and cannot be reassigned alone.
-- ---------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT n.nspname AS sch, c.relname AS rel, c.relkind AS kind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('staging', 'core', 'mart')
          AND c.relkind IN ('r', 'v', 'm')
    LOOP
        IF r.kind = 'v' THEN
            EXECUTE format('ALTER VIEW %I.%I OWNER TO nbci_owner', r.sch, r.rel);
        ELSIF r.kind = 'm' THEN
            EXECUTE format('ALTER MATERIALIZED VIEW %I.%I OWNER TO nbci_owner', r.sch, r.rel);
        ELSE
            EXECUTE format('ALTER TABLE %I.%I OWNER TO nbci_owner', r.sch, r.rel);
        END IF;
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- 2. ETL: full DML on staging and core, read-only on mart
-- ---------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA staging, core TO nbci_etl;
GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA staging, core TO nbci_etl;
GRANT SELECT
    ON ALL TABLES IN SCHEMA mart TO nbci_etl;

-- ---------------------------------------------------------------------
-- 3. BI reader: SELECT on mart only
--
-- GRANT ... ON ALL TABLES covers views and materialized views too.
-- ---------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA mart TO nbci_bi_reader;

-- ---------------------------------------------------------------------
-- 4. MAINTAIN on materialized views, for nbci_etl only
--
-- PostgreSQL 17 introduced the MAINTAIN privilege, and from 17 onward
-- REFRESH MATERIALIZED VIEW requires it from any role that is not the
-- owner. SELECT is not enough. Verified on this server: with SELECT
-- alone, nbci_etl gets
--     InsufficientPrivilege: permission denied for materialized view
-- so the design's claim that nbci_etl refreshes matviews was false until
-- this grant existed.
--
-- HOW FUTURE MATERIALIZED VIEWS GET MAINTAIN
--
-- By object class, in this loop - not by ALTER DEFAULT PRIVILEGES.
-- Default privileges would have to be written "ON TABLES", which in
-- PostgreSQL covers ordinary tables and plain views as well, handing
-- MAINTAIN to 28 objects that can never be refreshed. This loop grants it
-- to exactly relkind='m' in mart, and to nothing else.
--
-- This is a loop, not a trigger and not a default privilege. A matview
-- added later receives MAINTAIN the next time this script is run - which
-- the clean-build workflow does on every rebuild, since 11_grants.sql
-- runs last. Adding a matview therefore needs no edit to this script, but
-- one created by hand outside that workflow holds no MAINTAIN until this
-- script is run again. Adding a different object class grants it nothing.
-- ---------------------------------------------------------------------
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT n.nspname AS sch, c.relname AS rel
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'mart' AND c.relkind = 'm'
    LOOP
        EXECUTE format('GRANT MAINTAIN ON %I.%I TO nbci_etl', r.sch, r.rel);
        -- the BI reader reads matviews; it never refreshes them
        EXECUTE format('REVOKE MAINTAIN ON %I.%I FROM nbci_bi_reader', r.sch, r.rel);
    END LOOP;
END
$$;

-- ---------------------------------------------------------------------
-- 5. The reader must hold nothing in staging or core
-- ---------------------------------------------------------------------
REVOKE ALL ON ALL TABLES    IN SCHEMA staging, core FROM nbci_bi_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA staging, core FROM nbci_bi_reader;
REVOKE ALL ON SCHEMA staging, core FROM nbci_bi_reader;

-- ---------------------------------------------------------------------
-- 6. Future objects
--
-- Scoped to the role that actually creates them. Without FOR ROLE the
-- default applies to the current role, which is the one running the
-- build - so a table added later inherits the same shape instead of
-- silently arriving with no grants.
-- ---------------------------------------------------------------------
ALTER DEFAULT PRIVILEGES IN SCHEMA staging, core
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO nbci_etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA staging, core
    GRANT USAGE, SELECT ON SEQUENCES TO nbci_etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA mart
    GRANT SELECT ON TABLES TO nbci_bi_reader, nbci_etl;

ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA staging, core
    GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO nbci_etl;
ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA staging, core
    GRANT USAGE, SELECT ON SEQUENCES TO nbci_etl;
ALTER DEFAULT PRIVILEGES FOR ROLE nbci_owner IN SCHEMA mart
    GRANT SELECT ON TABLES TO nbci_bi_reader, nbci_etl;

-- ---------------------------------------------------------------------
-- 7. Nothing to PUBLIC, anywhere
-- ---------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA staging, core, mart FROM PUBLIC;
REVOKE ALL ON SCHEMA staging, core, mart FROM PUBLIC;
