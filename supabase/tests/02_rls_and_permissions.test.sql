-- =============================================================================
-- SkillSwap pgTAP Automated Security Regression Test Suite
-- File: supabase/tests/02_rls_and_permissions.test.sql
-- Scope: DB-01 — Row Level Security (RLS), Schema/Table/Column/Function
--        Permissions, Security Definer Boundaries, and Live Role Isolation.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap WITH SCHEMA extensions;
SET LOCAL search_path = extensions, public, pg_catalog;

-- Because migration 20261028220100_foundation.sql revoked default PUBLIC
-- EXECUTE privileges on functions created by postgres, grant EXECUTE on the
-- pgTAP extension functions inside this rolled-back transaction so pgTAP
-- assertions (such as throws_ok and lives_ok) can run under SET LOCAL ROLE
-- anon and SET LOCAL ROLE authenticated.
GRANT USAGE ON SCHEMA extensions TO anon, authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA extensions TO anon, authenticated;

SELECT plan(83);

-- =============================================================================
-- SECTION A: RLS Policy Structure on All Five Application Tables (7 assertions)
-- =============================================================================

-- 1. Exact RLS policies on public.profiles
SELECT is(
  ARRAY(
    SELECT policyname::text
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'profiles'
    ORDER BY policyname
  ),
  ARRAY['profiles_select_authenticated', 'profiles_update_own'],
  'DB-01 A1: public.profiles has the exact expected RLS policies'
);

-- 2. Exact RLS policies on public.skills
SELECT is(
  ARRAY(
    SELECT policyname::text
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'skills'
    ORDER BY policyname
  ),
  ARRAY['skills_insert_own', 'skills_select_authenticated', 'skills_update_own'],
  'DB-01 A2: public.skills has the exact expected RLS policies'
);

-- 3. Exact RLS policies on public.exchange_requests
SELECT is(
  ARRAY(
    SELECT policyname::text
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'exchange_requests'
    ORDER BY policyname
  ),
  ARRAY['exchange_requests_insert_as_requester', 'exchange_requests_select_participants'],
  'DB-01 A3: public.exchange_requests has the exact expected RLS policies'
);

-- 4. Exact RLS policies on public.exchange_sessions
SELECT is(
  ARRAY(
    SELECT policyname::text
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'exchange_sessions'
    ORDER BY policyname
  ),
  ARRAY['exchange_sessions_select_participants', 'exchange_sessions_update_notes_participants'],
  'DB-01 A4: public.exchange_sessions has the exact expected RLS policies'
);

-- 5. Exact RLS policies on public.reviews
SELECT is(
  ARRAY(
    SELECT policyname::text
    FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'reviews'
    ORDER BY policyname
  ),
  ARRAY['reviews_select_authenticated'],
  'DB-01 A5: public.reviews has the exact expected RLS policies'
);

-- 6. No RLS policy on the five SkillSwap tables applies to anon or PUBLIC
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename IN ('profiles', 'skills', 'exchange_requests', 'exchange_sessions', 'reviews')
      AND (roles && ARRAY['anon', 'public']::name[])
  ),
  0,
  'DB-01 A6: Zero RLS policies on the five SkillSwap tables are granted to anon or PUBLIC'
);

-- 7. No RLS policy on the five SkillSwap tables permits DELETE or ALL
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename IN ('profiles', 'skills', 'exchange_requests', 'exchange_sessions', 'reviews')
      AND cmd IN ('DELETE', 'ALL')
  ),
  0,
  'DB-01 A7: Zero RLS policies on the five SkillSwap tables allow DELETE or ALL commands'
);

-- =============================================================================
-- SECTION B: Anonymous Role (anon) Restrictions (6 assertions)
-- =============================================================================

-- 8. anon has zero table-level privileges across all 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    CROSS JOIN unnest(ARRAY[
      'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
    ]) AS p(priv)
    WHERE has_table_privilege('anon', t.tbl, p.priv)
  ),
  0,
  'DB-01 B1: anon has zero table-level privileges across all five application tables'
);

-- 9. anon has zero column-level privileges across all columns of the 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM information_schema.columns c
    CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) AS p(priv)
    WHERE c.table_schema = 'public'
      AND c.table_name IN ('profiles', 'skills', 'exchange_requests', 'exchange_sessions', 'reviews')
      AND has_column_privilege('anon', format('public.%I', c.table_name), c.column_name, p.priv)
  ),
  0,
  'DB-01 B2: anon has zero column-level privileges across all five application tables'
);

-- 10. anon has no USAGE or CREATE privilege on schema private
SELECT is(
  has_schema_privilege('anon', 'private', 'USAGE')
  OR has_schema_privilege('anon', 'private', 'CREATE'),
  false,
  'DB-01 B3: anon has neither USAGE nor CREATE privilege on schema private'
);

-- 11. anon cannot execute any of the 5 public workflow wrapper functions
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.accept_exchange_request(uuid)',
      'public.decline_exchange_request(uuid)',
      'public.cancel_exchange_request(uuid)',
      'public.confirm_exchange_session(uuid)',
      'public.create_review(uuid, integer, text)'
    ]) AS f(fn_sig)
    WHERE has_function_privilege('anon', f.fn_sig, 'EXECUTE')
  ),
  0,
  'DB-01 B4: anon cannot execute any of the five public workflow RPC wrapper functions'
);

-- 12. anon cannot execute any function in schema private
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'private'
      AND has_function_privilege('anon', p.oid, 'EXECUTE')
  ),
  0,
  'DB-01 B5: anon cannot execute any function in schema private'
);

-- 13. Behavioural check: anon SELECT on public.profiles is rejected with 42501
SET LOCAL ROLE anon;
SELECT throws_ok(
  'SELECT count(*) FROM public.profiles',
  '42501',
  NULL,
  'DB-01 B6: Live SELECT on public.profiles as anon fails with SQLSTATE 42501'
);
SET LOCAL ROLE postgres;

-- =============================================================================
-- SECTION C: Authenticated Role Table & Column Grants (16 assertions)
-- =============================================================================

-- 14. authenticated has table-level SELECT on all 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    WHERE has_table_privilege('authenticated', t.tbl, 'SELECT')
  ),
  5,
  'DB-01 C1: authenticated has table-level SELECT privilege on all five tables'
);

-- 15. authenticated has zero table-wide INSERT grants (inserts use column-level grants)
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    WHERE has_table_privilege('authenticated', t.tbl, 'INSERT')
  ),
  0,
  'DB-01 C2: authenticated has zero table-wide INSERT grants across all five tables'
);

-- 16. authenticated has zero table-wide UPDATE grants (updates use column-level grants)
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    WHERE has_table_privilege('authenticated', t.tbl, 'UPDATE')
  ),
  0,
  'DB-01 C3: authenticated has zero table-wide UPDATE grants across all five tables'
);

-- 17. authenticated has zero TRUNCATE, REFERENCES, or TRIGGER grants across all 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    CROSS JOIN unnest(ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p(priv)
    WHERE has_table_privilege('authenticated', t.tbl, p.priv)
  ),
  0,
  'DB-01 C4: authenticated has zero TRUNCATE, REFERENCES, or TRIGGER grants on all five tables'
);

-- 18. public.profiles has zero insertable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'profiles'
      AND has_column_privilege('authenticated', 'public.profiles', c.column_name, 'INSERT')
    ORDER BY c.column_name
  ),
  ARRAY[]::text[],
  'DB-01 C5: authenticated has zero INSERT column grants on public.profiles'
);

-- 19. public.profiles exact updateable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'profiles'
      AND has_column_privilege('authenticated', 'public.profiles', c.column_name, 'UPDATE')
    ORDER BY c.column_name
  ),
  ARRAY['availability', 'bio', 'display_name', 'interests', 'learning_preferences'],
  'DB-01 C6: authenticated can UPDATE only the 5 editable profile columns'
);

-- 20. public.profiles protected columns are NOT updateable by authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY['user_id', 'created_at', 'updated_at']) AS col(name)
    WHERE has_column_privilege('authenticated', 'public.profiles', col.name, 'UPDATE')
  ),
  0,
  'DB-01 C7: authenticated cannot UPDATE user_id, created_at, or updated_at on public.profiles'
);

-- 21. public.skills exact insertable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'skills'
      AND has_column_privilege('authenticated', 'public.skills', c.column_name, 'INSERT')
    ORDER BY c.column_name
  ),
  ARRAY['category', 'description', 'owner_user_id', 'proficiency_level', 'skill_name', 'skill_type'],
  'DB-01 C8: authenticated can INSERT only the 6 allowed columns on public.skills'
);

-- 22. public.skills protected columns are NOT insertable by authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY['id', 'is_active', 'created_at', 'updated_at']) AS col(name)
    WHERE has_column_privilege('authenticated', 'public.skills', col.name, 'INSERT')
  ),
  0,
  'DB-01 C9: authenticated cannot INSERT id, is_active, created_at, or updated_at on public.skills'
);

-- 23. public.skills exact updateable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'skills'
      AND has_column_privilege('authenticated', 'public.skills', c.column_name, 'UPDATE')
    ORDER BY c.column_name
  ),
  ARRAY['category', 'description', 'is_active', 'proficiency_level', 'skill_name'],
  'DB-01 C10: authenticated can UPDATE only the 5 mutable columns on public.skills'
);

-- 24. public.skills immutable identity/audit columns are NOT updateable by authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY['id', 'owner_user_id', 'skill_type', 'created_at', 'updated_at']) AS col(name)
    WHERE has_column_privilege('authenticated', 'public.skills', col.name, 'UPDATE')
  ),
  0,
  'DB-01 C11: authenticated cannot UPDATE id, owner_user_id, skill_type, created_at, or updated_at on public.skills'
);

-- 25. public.exchange_requests exact insertable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'exchange_requests'
      AND has_column_privilege('authenticated', 'public.exchange_requests', c.column_name, 'INSERT')
    ORDER BY c.column_name
  ),
  ARRAY['format', 'message', 'offered_skill_id', 'proposed_datetime', 'receiver_user_id', 'requester_user_id', 'wanted_skill_id'],
  'DB-01 C12: authenticated can INSERT only the 7 proposal columns on public.exchange_requests'
);

-- 26. public.exchange_requests protected columns are NOT insertable by authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY['id', 'status', 'created_at', 'updated_at']) AS col(name)
    WHERE has_column_privilege('authenticated', 'public.exchange_requests', col.name, 'INSERT')
  ),
  0,
  'DB-01 C13: authenticated cannot INSERT id, status, created_at, or updated_at on public.exchange_requests'
);

-- 27. public.exchange_requests has zero updateable columns for authenticated
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'exchange_requests'
      AND has_column_privilege('authenticated', 'public.exchange_requests', c.column_name, 'UPDATE')
    ORDER BY c.column_name
  ),
  ARRAY[]::text[],
  'DB-01 C14: authenticated has zero UPDATE column grants on public.exchange_requests'
);

-- 28. public.exchange_sessions allows zero INSERT columns and only notes for UPDATE
SELECT is(
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'exchange_sessions'
      AND has_column_privilege('authenticated', 'public.exchange_sessions', c.column_name, 'INSERT')
  )
  ||
  ARRAY(
    SELECT c.column_name::text
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name = 'exchange_sessions'
      AND has_column_privilege('authenticated', 'public.exchange_sessions', c.column_name, 'UPDATE')
    ORDER BY c.column_name
  ),
  ARRAY['notes'],
  'DB-01 C15: authenticated has zero INSERT columns and can UPDATE only notes on public.exchange_sessions'
);

-- 29. public.reviews has zero INSERT and zero UPDATE column grants for authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM information_schema.columns c
    CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE']) AS p(priv)
    WHERE c.table_schema = 'public'
      AND c.table_name = 'reviews'
      AND has_column_privilege('authenticated', 'public.reviews', c.column_name, p.priv)
  ),
  0,
  'DB-01 C16: authenticated has zero INSERT or UPDATE column grants on public.reviews'
);

-- =============================================================================
-- SECTION D: Direct DELETE Restrictions Across All Five Tables (6 assertions)
-- =============================================================================

-- 30. Catalog check: zero DELETE privilege for authenticated or anon on all 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.profiles',
      'public.skills',
      'public.exchange_requests',
      'public.exchange_sessions',
      'public.reviews'
    ]) AS t(tbl)
    CROSS JOIN unnest(ARRAY['authenticated', 'anon']) AS r(role_name)
    WHERE has_table_privilege(r.role_name, t.tbl, 'DELETE')
  ),
  0,
  'DB-01 D1: Neither authenticated nor anon has DELETE privilege on any of the five tables'
);

-- 31–35. Behavioural checks: live DELETE statements as authenticated fail with 42501
SET LOCAL ROLE authenticated;

SELECT throws_ok(
  'DELETE FROM public.profiles',
  '42501',
  NULL,
  'DB-01 D2: Direct DELETE on public.profiles as authenticated fails with SQLSTATE 42501'
);

SELECT throws_ok(
  'DELETE FROM public.skills',
  '42501',
  NULL,
  'DB-01 D3: Direct DELETE on public.skills as authenticated fails with SQLSTATE 42501'
);

SELECT throws_ok(
  'DELETE FROM public.exchange_requests',
  '42501',
  NULL,
  'DB-01 D4: Direct DELETE on public.exchange_requests as authenticated fails with SQLSTATE 42501'
);

SELECT throws_ok(
  'DELETE FROM public.exchange_sessions',
  '42501',
  NULL,
  'DB-01 D5: Direct DELETE on public.exchange_sessions as authenticated fails with SQLSTATE 42501'
);

SELECT throws_ok(
  'DELETE FROM public.reviews',
  '42501',
  NULL,
  'DB-01 D6: Direct DELETE on public.reviews as authenticated fails with SQLSTATE 42501'
);

SET LOCAL ROLE postgres;

-- =============================================================================
-- SECTION E: Private Schema & Internal Function Restrictions (9 assertions)
-- =============================================================================

-- 36. authenticated has USAGE on schema private
SELECT ok(
  has_schema_privilege('authenticated', 'private', 'USAGE'),
  'DB-01 E1: authenticated has USAGE privilege on schema private'
);

-- 37. authenticated does NOT have CREATE on schema private
SELECT is(
  has_schema_privilege('authenticated', 'private', 'CREATE'),
  false,
  'DB-01 E2: authenticated does not have CREATE privilege on schema private'
);

-- 38. authenticated can execute private.valid_interests(text[]) for profile CHECK constraint
SELECT ok(
  has_function_privilege('authenticated', 'private.valid_interests(text[])', 'EXECUTE'),
  'DB-01 E3: authenticated has EXECUTE privilege on helper private.valid_interests(text[])'
);

-- 39. private.valid_interests(text[]) is SECURITY INVOKER (prosecdef = false)
SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'private.valid_interests(text[])'::regprocedure),
  false,
  'DB-01 E4: private.valid_interests(text[]) is SECURITY INVOKER (prosecdef = false)'
);

-- 40. authenticated cannot execute any of the 8 private trigger functions directly
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'private.set_updated_at()',
      'private.handle_new_user()',
      'private.guard_skill_identity()',
      'private.validate_exchange_request_insert()',
      'private.guard_exchange_request_update()',
      'private.protect_referenced_skill()',
      'private.guard_exchange_session_update()',
      'private.validate_review_insert()'
    ]) AS f(fn_sig)
    WHERE has_function_privilege('authenticated', f.fn_sig, 'EXECUTE')
  ),
  0,
  'DB-01 E5: authenticated cannot directly execute any of the 8 private trigger functions'
);

-- 41. All 5 private workflow functions are SECURITY DEFINER (prosecdef = true)
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'private.accept_exchange_request(uuid)',
      'private.decline_exchange_request(uuid)',
      'private.cancel_exchange_request(uuid)',
      'private.confirm_exchange_session(uuid)',
      'private.create_review(uuid, integer, text)'
    ]) AS f(fn_sig)
    WHERE (SELECT prosecdef FROM pg_proc WHERE oid = f.fn_sig::regprocedure) = true
  ),
  5,
  'DB-01 E6: All five private workflow functions are SECURITY DEFINER (prosecdef = true)'
);

-- 42. All 5 private workflow functions are executable by authenticated (invoked via public wrappers)
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'private.accept_exchange_request(uuid)',
      'private.decline_exchange_request(uuid)',
      'private.cancel_exchange_request(uuid)',
      'private.confirm_exchange_session(uuid)',
      'private.create_review(uuid, integer, text)'
    ]) AS f(fn_sig)
    WHERE has_function_privilege('authenticated', f.fn_sig, 'EXECUTE')
  ),
  5,
  'DB-01 E7: All five private workflow functions grant EXECUTE to authenticated'
);

-- 43. Trigger function SECURITY DEFINER / INVOKER split matches architecture
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'private.handle_new_user()',
      'private.validate_exchange_request_insert()',
      'private.protect_referenced_skill()',
      'private.validate_review_insert()'
    ]) AS def_fn(fn_sig)
    WHERE (SELECT prosecdef FROM pg_proc WHERE oid = def_fn.fn_sig::regprocedure) = true
  )
  +
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'private.set_updated_at()',
      'private.guard_skill_identity()',
      'private.guard_exchange_request_update()',
      'private.guard_exchange_session_update()'
    ]) AS inv_fn(fn_sig)
    WHERE (SELECT prosecdef FROM pg_proc WHERE oid = inv_fn.fn_sig::regprocedure) = false
  ),
  8,
  'DB-01 E8: All 8 private trigger functions have their exact expected SECURITY DEFINER / INVOKER flags'
);

-- 44. All 14 functions in schema private have an explicitly EMPTY search_path
-- PostgreSQL stores `SET search_path = ''` in pg_proc.proconfig as `search_path=""`
-- (or `search_path=` depending on GUC serialization). Both represent an explicitly
-- empty search_path; any non-empty schema list is rejected.
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'private'
      AND EXISTS (
        SELECT 1
        FROM unnest(COALESCE(p.proconfig, ARRAY[]::text[])) AS cfg
        WHERE cfg IN ('search_path=""', 'search_path=')
      )
  ),
  14,
  'DB-01 E9: All 14 functions in schema private enforce an explicitly empty search_path'
);

-- =============================================================================
-- SECTION F: Public Workflow RPC Wrappers (12 assertions)
-- =============================================================================

-- 45–49. authenticated has EXECUTE privilege on each of the 5 public workflow wrappers
SELECT ok(
  has_function_privilege('authenticated', 'public.accept_exchange_request(uuid)', 'EXECUTE'),
  'DB-01 F1: authenticated can EXECUTE public.accept_exchange_request(uuid)'
);

SELECT ok(
  has_function_privilege('authenticated', 'public.decline_exchange_request(uuid)', 'EXECUTE'),
  'DB-01 F2: authenticated can EXECUTE public.decline_exchange_request(uuid)'
);

SELECT ok(
  has_function_privilege('authenticated', 'public.cancel_exchange_request(uuid)', 'EXECUTE'),
  'DB-01 F3: authenticated can EXECUTE public.cancel_exchange_request(uuid)'
);

SELECT ok(
  has_function_privilege('authenticated', 'public.confirm_exchange_session(uuid)', 'EXECUTE'),
  'DB-01 F4: authenticated can EXECUTE public.confirm_exchange_session(uuid)'
);

SELECT ok(
  has_function_privilege('authenticated', 'public.create_review(uuid, integer, text)', 'EXECUTE'),
  'DB-01 F5: authenticated can EXECUTE public.create_review(uuid, integer, text)'
);

-- 50–54. Each of the 5 public workflow wrappers is SECURITY INVOKER (prosecdef = false)
SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'public.accept_exchange_request(uuid)'::regprocedure),
  false,
  'DB-01 F6: public.accept_exchange_request(uuid) is SECURITY INVOKER'
);

SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'public.decline_exchange_request(uuid)'::regprocedure),
  false,
  'DB-01 F7: public.decline_exchange_request(uuid) is SECURITY INVOKER'
);

SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'public.cancel_exchange_request(uuid)'::regprocedure),
  false,
  'DB-01 F8: public.cancel_exchange_request(uuid) is SECURITY INVOKER'
);

SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'public.confirm_exchange_session(uuid)'::regprocedure),
  false,
  'DB-01 F9: public.confirm_exchange_session(uuid) is SECURITY INVOKER'
);

SELECT is(
  (SELECT prosecdef FROM pg_proc WHERE oid = 'public.create_review(uuid, integer, text)'::regprocedure),
  false,
  'DB-01 F10: public.create_review(uuid, integer, text) is SECURITY INVOKER'
);

-- 55. None of the 5 public workflow wrappers grants EXECUTE to PUBLIC (grantee = 0)
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) AS acl
    WHERE n.nspname = 'public'
      AND p.proname IN (
        'accept_exchange_request',
        'decline_exchange_request',
        'cancel_exchange_request',
        'confirm_exchange_session',
        'create_review'
      )
      AND acl.grantee = 0
      AND acl.privilege_type = 'EXECUTE'
  ),
  0,
  'DB-01 F11: Zero public workflow wrappers grant EXECUTE to PUBLIC'
);

-- 56. All 5 public workflow wrappers enforce an explicitly EMPTY search_path
SELECT is(
  (
    SELECT count(*)::int
    FROM unnest(ARRAY[
      'public.accept_exchange_request(uuid)',
      'public.decline_exchange_request(uuid)',
      'public.cancel_exchange_request(uuid)',
      'public.confirm_exchange_session(uuid)',
      'public.create_review(uuid, integer, text)'
    ]) AS f(fn_sig)
    JOIN pg_proc p ON p.oid = f.fn_sig::regprocedure
    WHERE EXISTS (
      SELECT 1
      FROM unnest(COALESCE(p.proconfig, ARRAY[]::text[])) AS cfg
      WHERE cfg IN ('search_path=""', 'search_path=')
    )
  ),
  5,
  'DB-01 F12: All five public workflow wrappers enforce an explicitly empty search_path'
);

-- =============================================================================
-- SECTION G: Live Behavioural RLS Ownership & Participant Visibility (24 assertions)
-- =============================================================================
-- Fictional test users (rolled back automatically at end of file):
--   User A (Requester): 11111111-1111-4111-8111-111111111111
--   User B (Receiver):  22222222-2222-4222-8222-222222222222
--   User C (Outsider):  33333333-3333-4333-8333-333333333333

INSERT INTO auth.users (id, email, raw_user_meta_data, created_at, updated_at)
VALUES
  (
    '11111111-1111-4111-8111-111111111111'::uuid,
    'user_a@example.test',
    '{"display_name": "Alex Rivera"}'::jsonb,
    now(),
    now()
  ),
  (
    '22222222-2222-4222-8222-222222222222'::uuid,
    'user_b@example.test',
    '{"display_name": "Blair Chen"}'::jsonb,
    now(),
    now()
  ),
  (
    '33333333-3333-4333-8333-333333333333'::uuid,
    'user_c@example.test',
    '{"display_name": "Casey Patel"}'::jsonb,
    now(),
    now()
  );

-- 57. Trigger on_auth_user_created automatically created all 3 profile rows
SELECT is(
  (
    SELECT count(*)::int
    FROM public.profiles
    WHERE user_id IN (
      '11111111-1111-4111-8111-111111111111'::uuid,
      '22222222-2222-4222-8222-222222222222'::uuid,
      '33333333-3333-4333-8333-333333333333'::uuid
    )
  ),
  3,
  'DB-01 G1: Auth signup trigger automatically created profiles for fictional Users A, B, and C'
);

-- Switch to authenticated User A
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 58. User A can read all 3 profiles
SELECT is(
  (
    SELECT count(*)::int
    FROM public.profiles
    WHERE user_id IN (
      '11111111-1111-4111-8111-111111111111'::uuid,
      '22222222-2222-4222-8222-222222222222'::uuid,
      '33333333-3333-4333-8333-333333333333'::uuid
    )
  ),
  3,
  'DB-01 G2: Authenticated User A can SELECT all member profiles'
);

-- 59. User A can update their own profile bio
UPDATE public.profiles
SET bio = 'Updated by User A'
WHERE user_id = '11111111-1111-4111-8111-111111111111'::uuid;

SELECT is(
  (SELECT bio FROM public.profiles WHERE user_id = '11111111-1111-4111-8111-111111111111'::uuid),
  'Updated by User A',
  'DB-01 G3: Authenticated User A can UPDATE their own profile bio'
);

-- 60. User A cannot update User B's profile (RLS silently filters non-owned row)
UPDATE public.profiles
SET bio = 'Tampered by User A'
WHERE user_id = '22222222-2222-4222-8222-222222222222'::uuid;

SELECT is(
  (SELECT bio FROM public.profiles WHERE user_id = '22222222-2222-4222-8222-222222222222'::uuid),
  '',
  'DB-01 G4: User A cannot UPDATE User B profile (RLS blocks cross-user profile modification)'
);

-- 61. User A cannot update protected column user_id on profiles
SELECT throws_ok(
  $$UPDATE public.profiles SET user_id = '33333333-3333-4333-8333-333333333333'::uuid WHERE user_id = '11111111-1111-4111-8111-111111111111'::uuid$$,
  '42501',
  NULL,
  'DB-01 G5: Updating protected column user_id on public.profiles fails with SQLSTATE 42501'
);

-- 62. User A can insert their own offered skill with valid category and skill_type
SELECT lives_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('11111111-1111-4111-8111-111111111111'::uuid, 'Python Tutoring', 'Technology', 'advanced', 'offered', 'Intro to Python')$$,
  'DB-01 G6: User A can INSERT a skill with their own owner_user_id'
);

-- 63. User A cannot insert a skill owned by User B (RLS WITH CHECK violation 42501)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('22222222-2222-4222-8222-222222222222'::uuid, 'Spoofed Skill', 'Technology', 'beginner', 'offered', 'Spoofed owner')$$,
  '42501',
  NULL,
  'DB-01 G7: User A cannot INSERT a skill for User B (RLS WITH CHECK fails with 42501)'
);

-- Switch to User B to insert User B's offered skill
SELECT set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
VALUES ('22222222-2222-4222-8222-222222222222'::uuid, 'UI Design Coaching', 'Design', 'expert', 'offered', 'Figma fundamentals');

-- Switch back to User A
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 64. User A can update their own skill description and is_active flag
UPDATE public.skills
SET description = 'Updated Python curriculum', is_active = true
WHERE owner_user_id = '11111111-1111-4111-8111-111111111111'::uuid;

SELECT is(
  (SELECT description FROM public.skills WHERE owner_user_id = '11111111-1111-4111-8111-111111111111'::uuid LIMIT 1),
  'Updated Python curriculum',
  'DB-01 G8: User A can UPDATE their own skill mutable columns'
);

-- 65. User A cannot update User B's skill
UPDATE public.skills
SET description = 'Hijacked description'
WHERE owner_user_id = '22222222-2222-4222-8222-222222222222'::uuid;

SELECT is(
  (SELECT description FROM public.skills WHERE owner_user_id = '22222222-2222-4222-8222-222222222222'::uuid LIMIT 1),
  'Figma fundamentals',
  'DB-01 G9: User A cannot UPDATE User B skill (RLS blocks cross-user skill modification)'
);

-- 66. User A cannot update immutable column skill_type on their own skill
SELECT throws_ok(
  $$UPDATE public.skills SET skill_type = 'wanted' WHERE owner_user_id = '11111111-1111-4111-8111-111111111111'::uuid$$,
  '42501',
  NULL,
  'DB-01 G10: Updating immutable column skill_type on public.skills fails with SQLSTATE 42501'
);

-- 67. User A can insert an exchange request as requester
SELECT lives_ok(
  $$INSERT INTO public.exchange_requests (
      requester_user_id,
      receiver_user_id,
      offered_skill_id,
      wanted_skill_id,
      message,
      proposed_datetime,
      format
    )
    VALUES (
      '11111111-1111-4111-8111-111111111111'::uuid,
      '22222222-2222-4222-8222-222222222222'::uuid,
      (SELECT id FROM public.skills WHERE owner_user_id = '11111111-1111-4111-8111-111111111111'::uuid LIMIT 1),
      (SELECT id FROM public.skills WHERE owner_user_id = '22222222-2222-4222-8222-222222222222'::uuid LIMIT 1),
      'Let us swap Python for Figma!',
      now() + interval '7 days',
      'online'
    )$$,
  'DB-01 G11: User A can INSERT a pending exchange request as requester_user_id'
);

-- 68. User A cannot insert an exchange request impersonating User B as requester_user_id
SELECT throws_ok(
  $$INSERT INTO public.exchange_requests (
      requester_user_id,
      receiver_user_id,
      offered_skill_id,
      wanted_skill_id,
      message,
      proposed_datetime,
      format
    )
    VALUES (
      '22222222-2222-4222-8222-222222222222'::uuid,
      '11111111-1111-4111-8111-111111111111'::uuid,
      (SELECT id FROM public.skills WHERE owner_user_id = '22222222-2222-4222-8222-222222222222'::uuid LIMIT 1),
      (SELECT id FROM public.skills WHERE owner_user_id = '11111111-1111-4111-8111-111111111111'::uuid LIMIT 1),
      'Impersonated request',
      now() + interval '7 days',
      'online'
    )$$,
  '42501',
  NULL,
  'DB-01 G12: User A cannot INSERT an exchange request with requester_user_id = User B (fails with 42501)'
);

-- 69. Requester (User A) can SELECT the exchange request
SELECT is(
  (SELECT count(*)::int FROM public.exchange_requests WHERE requester_user_id = '11111111-1111-4111-8111-111111111111'::uuid),
  1,
  'DB-01 G13: Requester User A can SELECT their own exchange request'
);

-- 70. Receiver (User B) can SELECT the exchange request
SELECT set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT is(
  (SELECT count(*)::int FROM public.exchange_requests WHERE receiver_user_id = '22222222-2222-4222-8222-222222222222'::uuid),
  1,
  'DB-01 G14: Receiver User B can SELECT the exchange request addressed to them'
);

-- 71. Non-participant (User C) sees 0 rows in public.exchange_requests
SELECT set_config('request.jwt.claim.sub', '33333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
SELECT is(
  (SELECT count(*)::int FROM public.exchange_requests),
  0,
  'DB-01 G15: Non-participant User C sees 0 rows in public.exchange_requests'
);

-- 72. Direct UPDATE on public.exchange_requests is rejected with 42501
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
SELECT throws_ok(
  $$UPDATE public.exchange_requests SET status = 'cancelled'$$,
  '42501',
  NULL,
  'DB-01 G16: Direct UPDATE on public.exchange_requests.status fails with SQLSTATE 42501'
);

-- Receiver (User B) accepts the exchange request via the public RPC wrapper to create a session
SELECT set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT public.accept_exchange_request(
  (SELECT id FROM public.exchange_requests WHERE requester_user_id = '11111111-1111-4111-8111-111111111111'::uuid LIMIT 1)
);

-- 73. Participant (User A) can SELECT the resulting exchange session
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
SELECT is(
  (SELECT count(*)::int FROM public.exchange_sessions),
  1,
  'DB-01 G17: Participant User A can SELECT the exchange session'
);

-- 74. Non-participant (User C) sees 0 rows in public.exchange_sessions
SELECT set_config('request.jwt.claim.sub', '33333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
SELECT is(
  (SELECT count(*)::int FROM public.exchange_sessions),
  0,
  'DB-01 G18: Non-participant User C sees 0 rows in public.exchange_sessions'
);

-- 75. Participant (User A) can UPDATE notes on public.exchange_sessions
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
UPDATE public.exchange_sessions SET notes = 'Participant session note';

SELECT is(
  (SELECT notes FROM public.exchange_sessions LIMIT 1),
  'Participant session note',
  'DB-01 G19: Participant User A can UPDATE notes on public.exchange_sessions'
);

-- 76. Non-participant (User C) cannot UPDATE notes on public.exchange_sessions
SELECT set_config('request.jwt.claim.sub', '33333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
UPDATE public.exchange_sessions SET notes = 'Outsider note';

SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
SELECT is(
  (SELECT notes FROM public.exchange_sessions LIMIT 1),
  'Participant session note',
  'DB-01 G20: Non-participant User C cannot UPDATE notes on public.exchange_sessions'
);

-- 77. Participant cannot directly UPDATE protected column completion_status on exchange_sessions
SELECT throws_ok(
  $$UPDATE public.exchange_sessions SET completion_status = 'completed'$$,
  '42501',
  NULL,
  'DB-01 G21: Direct UPDATE on public.exchange_sessions.completion_status fails with SQLSTATE 42501'
);

-- NOTE ON EARLY SESSION CONFIRMATION (Current Database Behaviour):
-- In migration 20261028220700_private_workflow_functions.sql,
-- private.confirm_exchange_session(uuid) allows participants to confirm a
-- scheduled session before scheduled_datetime has passed. This test uses that
-- current database behaviour to seed a completed session and review fixture
-- for RLS visibility and direct-write restriction checks, pending final
-- product-policy approval on whether early confirmation should be restricted.
SELECT public.confirm_exchange_session((SELECT id FROM public.exchange_sessions LIMIT 1));
SELECT set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT public.confirm_exchange_session((SELECT id FROM public.exchange_sessions LIMIT 1));

SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
SELECT public.create_review(
  (SELECT id FROM public.exchange_sessions LIMIT 1),
  5,
  'Great Python and Figma session!'
);

-- 78. Any authenticated member (User C) can SELECT reviews
SELECT set_config('request.jwt.claim.sub', '33333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
SELECT is(
  (SELECT count(*)::int FROM public.reviews),
  1,
  'DB-01 G22: Authenticated User C can SELECT completed session reviews'
);

-- 79. Direct INSERT into public.reviews as authenticated fails with 42501
SELECT set_config('request.jwt.claim.sub', '22222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"22222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      '00000000-0000-4000-8000-000000000000'::uuid,
      '22222222-2222-4222-8222-222222222222'::uuid,
      '11111111-1111-4111-8111-111111111111'::uuid,
      5,
      'Direct insert bypass attempt'
    )$$,
  '42501',
  NULL,
  'DB-01 G23: Direct INSERT into public.reviews as authenticated fails with SQLSTATE 42501'
);

-- 80. Direct UPDATE on public.reviews as authenticated fails with 42501
SELECT set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
SELECT throws_ok(
  $$UPDATE public.reviews SET rating = 1, comment = 'Edited review'$$,
  '42501',
  NULL,
  'DB-01 G24: Direct UPDATE on public.reviews as authenticated fails with SQLSTATE 42501'
);

SET LOCAL ROLE postgres;

-- =============================================================================
-- SECTION H: Column Reference & Default Function Privileges (3 assertions)
-- =============================================================================

-- 81. authenticated has zero REFERENCES privileges on any column of the 5 tables
SELECT is(
  (
    SELECT count(*)::int
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
      AND c.table_name IN ('profiles', 'skills', 'exchange_requests', 'exchange_sessions', 'reviews')
      AND has_column_privilege('authenticated', format('public.%I', c.table_name), c.column_name, 'REFERENCES')
  ),
  0,
  'DB-01 H1: authenticated has zero column-level REFERENCES privileges across all five tables'
);

-- 82. Per-schema default function EXECUTE privileges for the migration-owning role
-- in public and private are not granted to PUBLIC, anon, or authenticated
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_default_acl d
    JOIN pg_namespace n ON n.oid = d.defaclnamespace
    CROSS JOIN LATERAL aclexplode(d.defaclacl) AS acl
    WHERE d.defaclrole = current_user::regrole
      AND d.defaclobjtype = 'f'
      AND n.nspname IN ('public', 'private')
      AND acl.grantee IN (0::oid, 'anon'::regrole::oid, 'authenticated'::regrole::oid)
      AND acl.privilege_type = 'EXECUTE'
  ),
  0,
  'DB-01 H2: Default function EXECUTE privileges for postgres in public and private schemas are not granted to PUBLIC, anon, or authenticated'
);

-- 83. Global default EXECUTE privilege on functions for PUBLIC (grantee = 0) is revoked
SELECT is(
  (
    SELECT count(*)::int
    FROM pg_default_acl d
    WHERE d.defaclrole = current_user::regrole
      AND d.defaclnamespace = 0
      AND d.defaclobjtype = 'f'
      AND NOT EXISTS (
        SELECT 1
        FROM aclexplode(d.defaclacl) acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
      )
  ),
  1,
  'DB-01 H3: Global default function EXECUTE privilege for PUBLIC is revoked in pg_default_acl'
);

SELECT * FROM finish();

ROLLBACK;
