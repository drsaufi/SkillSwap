-- =============================================================================
-- 20261028220100_foundation.sql
-- Shared groundwork used by every later migration.
--
--   * Creates the `private` schema. It is NOT exposed through the Supabase API,
--     so everything inside it can only be reached by SQL / by other functions.
--   * Locks down default function permissions (Postgres normally lets everyone
--     execute new functions - we switch that off).
--   * Adds the `set_updated_at()` trigger function.
--
-- SECURITY NOTE: before running this, confirm in the Supabase dashboard
-- (Settings -> API -> Exposed schemas) that `private` is NOT listed.
-- =============================================================================

-- Private schema: holds privileged helpers, never exposed through the API.
create schema if not exists private;

-- Nobody gets anything by default. Only `authenticated` gets USAGE, which is
-- required so the thin public wrapper functions can call into this schema.
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

-- -----------------------------------------------------------------------------
-- Default function permissions
--
-- PostgreSQL's built-in default is: every new function is executable by PUBLIC
-- (everyone). That built-in default is a GLOBAL default privilege.
--
-- IMPORTANT: `ALTER DEFAULT PRIVILEGES IN SCHEMA ...` can only ADD grants on top
-- of the global defaults. It cannot take away the global PUBLIC default, so
-- `... IN SCHEMA x REVOKE EXECUTE ... FROM PUBLIC` would silently do nothing
-- useful. The PUBLIC default must be revoked WITHOUT the IN SCHEMA clause.
--
-- 1. GLOBAL (no IN SCHEMA): stop PUBLIC from automatically getting EXECUTE on
--    functions created from now on by the role running these migrations
--    (`postgres` on Supabase).
--    SCOPE: this covers functions this role creates in ANY schema, in this
--    database, from now on. It is not retroactive (existing functions keep the
--    permissions they already have) and it does not affect functions owned by
--    other roles (for example Supabase's internal `supabase_admin`).
--    CONSEQUENCE: any function created later by this role (including via
--    dashboard or a future extension install) is NOT callable by anyone but its
--    owner until it is granted EXECUTE explicitly. That is the intended
--    least-privilege behaviour for this project.
alter default privileges
  revoke execute on functions from public;

-- 2. PER-SCHEMA: Supabase adds default function grants for `anon` and
--    `authenticated` in the `public` schema. Those ARE schema-level entries, so
--    removing them with IN SCHEMA works. (`private` has no such entries; the
--    statement is harmless there and keeps the intent explicit.)
--    `service_role` is left alone: the project never uses it, and it bypasses
--    RLS anyway.
alter default privileges in schema public
  revoke execute on functions from anon, authenticated;
alter default privileges in schema private
  revoke execute on functions from anon, authenticated;

-- These defaults are only a safety net for future functions. Every function in
-- these migrations ALSO has its own explicit REVOKE ... FROM PUBLIC, anon,
-- authenticated followed by an explicit GRANT where access is intended, so the
-- permissions of the existing functions do not depend on defaults at all.
-- To undo the global change later: ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON
-- FUNCTIONS TO PUBLIC;

-- -----------------------------------------------------------------------------
-- Trigger function: keeps `updated_at` correct on every UPDATE.
-- Plain (SECURITY INVOKER) function: it only touches the row being updated.
-- -----------------------------------------------------------------------------
create or replace function private.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

revoke all on function private.set_updated_at() from public, anon, authenticated;

