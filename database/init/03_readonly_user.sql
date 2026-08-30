-- =========================================================
-- 03_readonly_user.sql
-- Creates a least-privilege role for the Safe Executor.
--
-- This is the REAL security boundary. Even if every guardrail
-- upstream had a bug, this role physically cannot INSERT,
-- UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE anything.
--
-- Values are injected via POSTGRES_READONLY_USER /
-- POSTGRES_READONLY_PASSWORD environment variables at
-- container init time (see docker-compose.yml).
--
-- NOTE: this script relies on psql's `:'var'` / `:"var"`
-- interpolation, which Postgres's official image init-scripts
-- support since they're executed via `psql -f`. Interpolation
-- does NOT occur inside dollar-quoted ($$ ... $$) blocks, so
-- this script deliberately avoids PL/pgSQL DO blocks and uses
-- plain top-level statements instead. Since Postgres only runs
-- files in /docker-entrypoint-initdb.d on a completely fresh
-- data volume, CREATE ROLE here is safe to run unconditionally.
-- =========================================================

\set readonly_user `echo "${POSTGRES_READONLY_USER:-app_readonly}"`
\set readonly_password `echo "${POSTGRES_READONLY_PASSWORD:-app_readonly_pw}"`

CREATE ROLE :"readonly_user" WITH LOGIN PASSWORD :'readonly_password';

-- No ability to create objects in the public schema
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Explicit, minimal grants
GRANT USAGE ON SCHEMA public TO :"readonly_user";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"readonly_user";

-- Ensure any tables created LATER by the admin role are also
-- automatically readable (but never writable) by this role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO :"readonly_user";

-- Explicitly deny write/DDL capability (defense in depth --
-- the SELECT-only grant above already excludes these; this makes
-- the intent unambiguous to any future reader of this script).
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM :"readonly_user";

-- Prevent the role from creating new databases or roles
ALTER ROLE :"readonly_user" WITH NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Defense-in-depth: cap statement execution time at the connection
-- level too (the app also enforces QUERY_TIMEOUT_SECONDS itself).
ALTER ROLE :"readonly_user" SET statement_timeout = '10s';

-- Cap the number of concurrent connections this role can open,
-- so a runaway agent loop can't exhaust the connection pool.
ALTER ROLE :"readonly_user" CONNECTION LIMIT 10;

COMMENT ON ROLE :"readonly_user" IS 'Least-privilege role used exclusively by the Safe Executor. SELECT-only.';
