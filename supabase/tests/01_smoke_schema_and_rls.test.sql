-- =============================================================================
-- 01_smoke_schema_and_rls.test.sql
-- Initial pgTAP smoke test: verifies the public and private schemas, the five
-- SkillSwap application tables, RLS enabled on all five tables, and the five
-- public workflow RPC wrapper functions with their exact signatures.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap WITH SCHEMA extensions;
SET LOCAL search_path = extensions, public, pg_catalog;

SELECT plan(17);

-- 1. Verify schemas exist (2 assertions)
SELECT has_schema('public',  'public schema exists');
SELECT has_schema('private', 'private schema exists');

-- 2. Verify all five SkillSwap application tables exist in public (5 assertions)
SELECT has_table('public', 'profiles',          'public.profiles table exists');
SELECT has_table('public', 'skills',            'public.skills table exists');
SELECT has_table('public', 'exchange_requests', 'public.exchange_requests table exists');
SELECT has_table('public', 'exchange_sessions', 'public.exchange_sessions table exists');
SELECT has_table('public', 'reviews',           'public.reviews table exists');

-- 3. Verify Row Level Security (RLS) is enabled on all five tables (5 assertions)
SELECT is(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.profiles'::regclass),
  true,
  'RLS is enabled on public.profiles'
);
SELECT is(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.skills'::regclass),
  true,
  'RLS is enabled on public.skills'
);
SELECT is(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.exchange_requests'::regclass),
  true,
  'RLS is enabled on public.exchange_requests'
);
SELECT is(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.exchange_sessions'::regclass),
  true,
  'RLS is enabled on public.exchange_sessions'
);
SELECT is(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.reviews'::regclass),
  true,
  'RLS is enabled on public.reviews'
);

-- 4. Verify the five public workflow RPC functions with their signatures (5 assertions)
SELECT has_function(
  'public', 'accept_exchange_request', ARRAY['uuid'],
  'public.accept_exchange_request(uuid) exists'
);
SELECT has_function(
  'public', 'decline_exchange_request', ARRAY['uuid'],
  'public.decline_exchange_request(uuid) exists'
);
SELECT has_function(
  'public', 'cancel_exchange_request', ARRAY['uuid'],
  'public.cancel_exchange_request(uuid) exists'
);
SELECT has_function(
  'public', 'confirm_exchange_session', ARRAY['uuid'],
  'public.confirm_exchange_session(uuid) exists'
);
SELECT has_function(
  'public', 'create_review', ARRAY['uuid', 'integer', 'text'],
  'public.create_review(uuid, integer, text) exists'
);

SELECT * FROM finish();

ROLLBACK;