-- =============================================================================
-- SkillSwap pgTAP Automated Business-Rule Regression Test Suite
-- File: supabase/tests/04_requests_and_sessions_workflow.test.sql
-- Scope: DB-04 (Exchange Request Creation & Validation),
--        DB-05 (Request Acceptance & Safeguards),
--        DB-06 (Request Decline, Cancellation & Terminal States),
--        DB-07 (Session Creation & Two-Participant Confirmation),
--        DB-08 (Repeated Confirmation Idempotency & Cancelled Sessions),
--        DB-09 (Unauthorised Session Confirmation & Database Integrity Guards).
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap WITH SCHEMA extensions;
SET LOCAL search_path = extensions, public, pg_catalog;

-- Grant EXECUTE only on functions in schema extensions owned by the current
-- migration role (postgres) so pgTAP assertions run under anon/authenticated
-- without emitting warnings for supabase_admin-owned functions.
GRANT USAGE ON SCHEMA extensions TO anon, authenticated;
DO $$
DECLARE
  v_fn regprocedure;
BEGIN
  FOR v_fn IN
    SELECT p.oid::regprocedure
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'extensions'
      AND p.proowner = current_user::regrole
  LOOP
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO anon, authenticated', v_fn);
  END LOOP;
END;
$$;

SELECT plan(48);

-- =============================================================================
-- TEST FIXTURES: Fictional Users & Skills (Rolled Back Automatically)
-- =============================================================================
--   User A (Requester): b1111111-1111-4111-8111-111111111111
--   User B (Receiver):  b2222222-2222-4222-8222-222222222222
--   User C (Outsider):  b3333333-3333-4333-8333-333333333333
--
--   Skills:
--     User A active offered skill 1:  c1111111-1111-4111-8111-111111111111 ('Python Automation')
--     User A active offered skill 2:  c1222222-2222-4222-8222-222222222222 ('Docker Basics')
--     User A active wanted skill:     c1333333-3333-4333-8333-333333333333 ('UX Research')
--     User A inactive offered skill:  c1444444-4444-4444-8444-444444444444 ('Legacy Perl')
--     User B active offered skill 1:  c2111111-1111-4111-8111-111111111111 ('Figma Prototyping')
--     User B active offered skill 2:  c2222222-2222-4222-8222-222222222222 ('Design Systems')
--     User B active wanted skill:     c2333333-3333-4333-8333-333333333333 ('Cloud Deployment')
--     User B inactive offered skill:  c2444444-4444-4444-8444-444444444444 ('Flash Animation')
--     User C active offered skill:    c3111111-1111-4111-8111-111111111111 ('Spanish Conversation')

INSERT INTO auth.users (id, email, raw_user_meta_data, created_at, updated_at)
VALUES
  (
    'b1111111-1111-4111-8111-111111111111'::uuid,
    'req_user_a@example.test',
    '{"display_name": "Ahmad Razak"}'::jsonb,
    now(),
    now()
  ),
  (
    'b2222222-2222-4222-8222-222222222222'::uuid,
    'rec_user_b@example.test',
    '{"display_name": "Sarah Lim"}'::jsonb,
    now(),
    now()
  ),
  (
    'b3333333-3333-4333-8333-333333333333'::uuid,
    'out_user_c@example.test',
    '{"display_name": "Daniel Wong"}'::jsonb,
    now(),
    now()
  );

INSERT INTO public.skills (id, owner_user_id, skill_name, category, proficiency_level, skill_type, description, is_active)
VALUES
  (
    'c1111111-1111-4111-8111-111111111111'::uuid,
    'b1111111-1111-4111-8111-111111111111'::uuid,
    'Python Automation',
    'Technology',
    'advanced',
    'offered',
    'Automating workflows with Python scripts',
    true
  ),
  (
    'c1222222-2222-4222-8222-222222222222'::uuid,
    'b1111111-1111-4111-8111-111111111111'::uuid,
    'Docker Basics',
    'Technology',
    'intermediate',
    'offered',
    'Containerising development environments',
    true
  ),
  (
    'c1333333-3333-4333-8333-333333333333'::uuid,
    'b1111111-1111-4111-8111-111111111111'::uuid,
    'UX Research',
    'Design',
    'beginner',
    'wanted',
    'Looking to learn usability testing',
    true
  ),
  (
    'c1444444-4444-4444-8444-444444444444'::uuid,
    'b1111111-1111-4111-8111-111111111111'::uuid,
    'Legacy Perl',
    'Technology',
    'intermediate',
    'offered',
    'Inactive skill fixture',
    false
  ),
  (
    'c2111111-1111-4111-8111-111111111111'::uuid,
    'b2222222-2222-4222-8222-222222222222'::uuid,
    'Figma Prototyping',
    'Design',
    'expert',
    'offered',
    'Interactive prototypes and components',
    true
  ),
  (
    'c2222222-2222-4222-8222-222222222222'::uuid,
    'b2222222-2222-4222-8222-222222222222'::uuid,
    'Design Systems',
    'Design',
    'advanced',
    'offered',
    'Component tokens and accessibility',
    true
  ),
  (
    'c2333333-3333-4333-8333-333333333333'::uuid,
    'b2222222-2222-4222-8222-222222222222'::uuid,
    'Cloud Deployment',
    'Technology',
    'beginner',
    'wanted',
    'Want to learn cloud hosting basics',
    true
  ),
  (
    'c2444444-4444-4444-8444-444444444444'::uuid,
    'b2222222-2222-4222-8222-222222222222'::uuid,
    'Flash Animation',
    'Design',
    'intermediate',
    'offered',
    'Inactive receiver skill fixture',
    false
  ),
  (
    'c3111111-1111-4111-8111-111111111111'::uuid,
    'b3333333-3333-4333-8333-333333333333'::uuid,
    'Spanish Conversation',
    'Languages',
    'expert',
    'offered',
    'Conversational Spanish practice',
    true
  );

-- =============================================================================
-- SECTION A: Exchange Request Creation & Validation (DB-04) (13 assertions)
-- =============================================================================

-- Switch to authenticated User A
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 1. Valid exchange request creation (using only the 7 member-insertable columns) succeeds
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Would love to trade Python Automation for Figma Prototyping!',
      now() + interval '3 days',
      'online'
    )$$,
  'DB-04 A1: Valid exchange request creation by authenticated requester succeeds'
);

-- Capture the actual generated request UUID while acting as authorised participant User A
-- so subsequent outsider tests (under User C, where RLS hides the row) can pass the real UUID.
SELECT set_config(
  'test.req_a1_id',
  (
    SELECT id::text
    FROM public.exchange_requests
    WHERE requester_user_id = 'b1111111-1111-4111-8111-111111111111'::uuid
      AND receiver_user_id = 'b2222222-2222-4222-8222-222222222222'::uuid
    LIMIT 1
  ),
  true
);

-- 2. Created exchange request starts with status = 'pending'
SELECT is(
  (
    SELECT status
    FROM public.exchange_requests
    WHERE id = current_setting('test.req_a1_id')::uuid
  ),
  'pending',
  'DB-04 A2: Newly created exchange request starts in pending status'
);

-- 3. Self-request (requester_user_id = receiver_user_id) fails check constraint exchange_requests_members_differ (23514)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c1222222-2222-4222-8222-222222222222'::uuid,
      'Attempting to swap skills with myself',
      now() + interval '3 days',
      'online'
    )$$,
  '23514',
  NULL,
  'DB-04 A3: Self-request (requester_user_id = receiver_user_id) fails exchange_requests_members_differ (23514)'
);

-- 4. Proposed datetime in the past or equal to now() fails BEFORE INSERT trigger with 22023 (proposed_time_in_past)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Past proposed datetime',
      now() - interval '1 hour',
      'online'
    )$$,
  '22023',
  'proposed_time_in_past: the proposed date and time must be in the future',
  'DB-04 A4: Request with proposed_datetime in the past fails with SQLSTATE 22023 (proposed_time_in_past)'
);

-- 5. Incorrect offered_skill_id ownership fails BEFORE INSERT trigger with P0001 (invalid_offered_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c3111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Offering User C skill instead of my own',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_offered_skill: must be an active offered skill owned by the requester',
  'DB-04 A5: Offering a skill not owned by requester fails BEFORE INSERT trigger with P0001 (invalid_offered_skill)'
);

-- 6. Incorrect wanted_skill_id ownership fails BEFORE INSERT trigger with P0001 (invalid_wanted_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c3111111-1111-4111-8111-111111111111'::uuid,
      'Requesting User C skill from User B',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_wanted_skill: must be an active offered skill owned by the receiver',
  'DB-04 A6: Requesting a skill not owned by receiver fails BEFORE INSERT trigger with P0001 (invalid_wanted_skill)'
);

-- 7. Using a 'wanted' skill as offered_skill_id fails BEFORE INSERT trigger with P0001 (invalid_offered_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1333333-3333-4333-8333-333333333333'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Using wanted skill as offered_skill_id',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_offered_skill: must be an active offered skill owned by the requester',
  'DB-04 A7: Supplying a wanted-type skill as offered_skill_id fails with P0001 (invalid_offered_skill)'
);

-- 8. Using receiver's 'wanted' skill as wanted_skill_id fails BEFORE INSERT trigger with P0001 (invalid_wanted_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2333333-3333-4333-8333-333333333333'::uuid,
      'Using receiver wanted skill instead of receiver offered skill',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_wanted_skill: must be an active offered skill owned by the receiver',
  'DB-04 A8: Supplying a receiver wanted-type skill as wanted_skill_id fails with P0001 (invalid_wanted_skill)'
);

-- 9. Using an inactive requester offered skill (is_active = false) fails BEFORE INSERT trigger with P0001 (invalid_offered_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1444444-4444-4444-8444-444444444444'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Using an inactive offered skill',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_offered_skill: must be an active offered skill owned by the requester',
  'DB-04 A9: Supplying an inactive requester offered skill fails with P0001 (invalid_offered_skill)'
);

-- 10. Using an inactive receiver offered skill (is_active = false) fails BEFORE INSERT trigger with P0001 (invalid_wanted_skill)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2444444-4444-4444-8444-444444444444'::uuid,
      'Using an inactive receiver offered skill',
      now() + interval '3 days',
      'online'
    )$$,
  'P0001',
  'invalid_wanted_skill: must be an active offered skill owned by the receiver',
  'DB-04 A10: Supplying an inactive receiver offered skill fails with P0001 (invalid_wanted_skill)'
);

-- 11. Invalid format (not 'online' or 'in_person') fails check constraint exchange_requests_format_allowed (23514)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      'Valid message with bad format',
      now() + interval '3 days',
      'hybrid'
    )$$,
  '23514',
  NULL,
  'DB-04 A11: Disallowed request format fails exchange_requests_format_allowed (23514)'
);

-- 12. Empty/whitespace-only message fails exchange_requests_message_length (23514)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      '    ',
      now() + interval '3 days',
      'in_person'
    )$$,
  '23514',
  NULL,
  'DB-04 A12: Whitespace-only request message fails exchange_requests_message_length (23514)'
);

-- 13. Message exceeding 500 characters fails exchange_requests_message_length (23514)
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
      'b1111111-1111-4111-8111-111111111111'::uuid,
      'b2222222-2222-4222-8222-222222222222'::uuid,
      'c1111111-1111-4111-8111-111111111111'::uuid,
      'c2111111-1111-4111-8111-111111111111'::uuid,
      repeat('M', 501),
      now() + interval '3 days',
      'in_person'
    )$$,
  '23514',
  NULL,
  'DB-04 A13: Request message exceeding 500 characters fails exchange_requests_message_length (23514)'
);

-- =============================================================================
-- SECTION B: Accepting Requests & Safeguards (DB-05) (10 assertions)
-- =============================================================================

-- 14. Requester (User A) cannot accept their own outgoing request (42501)
SELECT throws_ok(
  $$SELECT public.accept_exchange_request(current_setting('test.req_a1_id')::uuid)$$,
  '42501',
  'not_permitted: only the receiver can accept a request',
  'DB-05 B1: Requester calling accept_exchange_request fails with SQLSTATE 42501 (not_permitted)'
);

-- 15. Outsider (User C) cannot accept an existing request (using captured real UUID test.req_a1_id -> P0002 request_not_found)
SELECT set_config('request.jwt.claim.sub', 'b3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"b3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.accept_exchange_request(current_setting('test.req_a1_id')::uuid)$$,
  'P0002',
  'request_not_found',
  'DB-05 B2: Outsider calling accept_exchange_request with real request UUID fails with SQLSTATE P0002 (request_not_found)'
);

-- 16. Unauthenticated caller (auth.uid() IS NULL) cannot accept a request (42501 not_authenticated)
SELECT set_config('request.jwt.claim.sub', '', true);
SELECT set_config('request.jwt.claims', '{}', true);

SELECT throws_ok(
  $$SELECT public.accept_exchange_request(current_setting('test.req_a1_id')::uuid)$$,
  '42501',
  'not_authenticated',
  'DB-05 B3: Unauthenticated caller calling accept_exchange_request fails with SQLSTATE 42501 (not_authenticated)'
);

-- 17. Receiver (User B) successfully accepts the pending request; status becomes 'accepted'
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT public.accept_exchange_request(current_setting('test.req_a1_id')::uuid);

SELECT is(
  (SELECT status FROM public.exchange_requests WHERE id = current_setting('test.req_a1_id')::uuid),
  'accepted',
  'DB-05 B4: Receiver calling accept_exchange_request transitions request status from pending to accepted'
);

-- 18. Accepting a request atomically creates 1 scheduled session with matching scheduled_datetime and null confirmation timestamps
SELECT is(
  (
    SELECT ARRAY[
      s.completion_status,
      (s.scheduled_datetime = r.proposed_datetime)::text,
      (s.requester_confirmed_at IS NULL)::text,
      (s.receiver_confirmed_at IS NULL)::text,
      (s.completed_at IS NULL)::text
    ]
    FROM public.exchange_sessions s
    JOIN public.exchange_requests r ON r.id = s.request_id
    WHERE r.id = current_setting('test.req_a1_id')::uuid
  ),
  ARRAY['scheduled', 'true', 'true', 'true', 'true'],
  'DB-05 B5: Accepted request creates one scheduled session with matching scheduled_datetime and null confirmations'
);

-- 19. Repeated acceptance on the same already-accepted request fails with P0001 (invalid_state)
SELECT throws_ok(
  $$SELECT public.accept_exchange_request(current_setting('test.req_a1_id')::uuid)$$,
  'P0001',
  'invalid_state: only a pending request can be accepted',
  'DB-05 B6: Repeated accept_exchange_request on an accepted request fails with SQLSTATE P0001 (invalid_state)'
);

-- 20. Safeguard 2 (skill_inactive): If a referenced skill is deactivated after request creation, acceptance fails with P0001
-- Temporarily switch to postgres to seed deterministic request ID d2222222 (since authenticated cannot insert id).
SET LOCAL ROLE postgres;
INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'd2222222-2222-4222-8222-222222222222'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1222222-2222-4222-8222-222222222222'::uuid,
  'c2222222-2222-4222-8222-222222222222'::uuid,
  'Request before skill deactivation',
  now() + interval '4 days',
  'online'
);

-- Switch to authenticated User A to soft-deactivate their offered skill c1222222
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

UPDATE public.skills
SET is_active = false
WHERE id = 'c1222222-2222-4222-8222-222222222222'::uuid;

-- Switch to Receiver User B and attempt to accept d2222222
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.accept_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  'P0001',
  'skill_inactive: a skill in this request has been deactivated',
  'DB-05 B7: Accepting a request whose skill was deactivated after creation fails with P0001 (skill_inactive)'
);

-- Re-activate c1222222 as User A for subsequent tests
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);
UPDATE public.skills
SET is_active = true
WHERE id = 'c1222222-2222-4222-8222-222222222222'::uuid;

-- 21. Expired proposed_datetime check (proposed_time_passed):
-- Because PostgreSQL now() is constant within a transaction, we deterministically
-- seed one expired pending request by briefly disabling user triggers on
-- public.exchange_requests as postgres, inserting a row with proposed_datetime =
-- now() - interval '1 hour', and immediately re-enabling triggers before testing
-- public.accept_exchange_request as authenticated User B.
SET LOCAL ROLE postgres;
ALTER TABLE public.exchange_requests DISABLE TRIGGER USER;

INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  status,
  proposed_datetime,
  format
)
VALUES (
  'd3333333-3333-4333-8333-333333333333'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1111111-1111-4111-8111-111111111111'::uuid,
  'c2111111-1111-4111-8111-111111111111'::uuid,
  'Request that expired before receiver accepted',
  'pending',
  now() - interval '1 hour',
  'online'
);

ALTER TABLE public.exchange_requests ENABLE TRIGGER USER;

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.accept_exchange_request('d3333333-3333-4333-8333-333333333333'::uuid)$$,
  'P0001',
  'proposed_time_passed: the proposed time is in the past; ask for a new request',
  'DB-05 B8: Accepting a pending request whose proposed_datetime has passed fails with P0001 (proposed_time_passed)'
);

-- 22. 1:1 session uniqueness constraint (exchange_sessions_request_id_key) blocks duplicate session for same request_id
SET LOCAL ROLE postgres;
SELECT throws_ok(
  $$INSERT INTO public.exchange_sessions (request_id, scheduled_datetime)
    VALUES (
      current_setting('test.req_a1_id')::uuid,
      now() + interval '3 days'
    )$$,
  '23505',
  NULL,
  'DB-05 B9: Unique constraint on exchange_sessions.request_id blocks creating a second session for one request (23505)'
);

-- 23. Total sessions created for the accepted request remains exactly 1
SELECT is(
  (SELECT count(*)::int FROM public.exchange_sessions WHERE request_id = current_setting('test.req_a1_id')::uuid),
  1,
  'DB-05 B10: Exactly one session row exists for the accepted request after rejected duplicate attempts'
);

-- =============================================================================
-- SECTION C: Declining and Cancelling Requests (DB-06) (11 assertions)
-- =============================================================================
-- Reuse pending request d2222222-2222-4222-8222-222222222222 for decline tests.

SET LOCAL ROLE authenticated;

-- 24. Requester (User A) cannot decline a pending request (42501)
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.decline_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  '42501',
  'not_permitted: only the receiver can decline a request',
  'DB-06 C1: Requester calling decline_exchange_request fails with SQLSTATE 42501 (not_permitted)'
);

-- 25. Outsider (User C) cannot decline a request (P0002)
SELECT set_config('request.jwt.claim.sub', 'b3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"b3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.decline_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  'P0002',
  'request_not_found',
  'DB-06 C2: Outsider calling decline_exchange_request fails with SQLSTATE P0002 (request_not_found)'
);

-- 26. Receiver (User B) cannot cancel a pending request (42501 - receiver must decline)
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.cancel_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  '42501',
  'not_permitted: only the requester can cancel a pending request (the receiver can decline)',
  'DB-06 C3: Receiver calling cancel_exchange_request on a pending request fails with SQLSTATE 42501'
);

-- 27. Receiver (User B) successfully declines the pending request -> status becomes 'declined'
SELECT is(
  (SELECT status FROM public.decline_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)),
  'declined',
  'DB-06 C4: Receiver calling decline_exchange_request transitions pending request to declined'
);

-- 28. Terminal state protection: a declined request cannot be accepted (P0001)
SELECT throws_ok(
  $$SELECT public.accept_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  'P0001',
  'invalid_state: only a pending request can be accepted',
  'DB-06 C5: Accepting a declined request fails with SQLSTATE P0001 (invalid_state)'
);

-- 29. Terminal state protection: a declined request cannot be cancelled (P0001)
SELECT throws_ok(
  $$SELECT public.cancel_exchange_request('d2222222-2222-4222-8222-222222222222'::uuid)$$,
  'P0001',
  'invalid_state: only a pending or accepted request can be cancelled',
  'DB-06 C6: Cancelling a declined request fails with SQLSTATE P0001 (invalid_state)'
);

-- Seed deterministic pending request d4444444 as postgres to test requester cancelling a pending request
SET LOCAL ROLE postgres;
INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'd4444444-4444-4444-8444-444444444444'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1222222-2222-4222-8222-222222222222'::uuid,
  'c2222222-2222-4222-8222-222222222222'::uuid,
  'Pending request to be cancelled by requester',
  now() + interval '5 days',
  'online'
);

-- 30. Outsider (User C) cannot cancel a pending request (P0002)
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"b3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.cancel_exchange_request('d4444444-4444-4444-8444-444444444444'::uuid)$$,
  'P0002',
  'request_not_found',
  'DB-06 C7: Outsider calling cancel_exchange_request fails with SQLSTATE P0002 (request_not_found)'
);

-- 31. Requester (User A) successfully cancels the pending request -> status becomes 'cancelled'
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT is(
  (SELECT status FROM public.cancel_exchange_request('d4444444-4444-4444-8444-444444444444'::uuid)),
  'cancelled',
  'DB-06 C8: Requester calling cancel_exchange_request transitions pending request to cancelled'
);

-- 32. Terminal state protection: a cancelled request cannot be declined (P0001)
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.decline_exchange_request('d4444444-4444-4444-8444-444444444444'::uuid)$$,
  'P0001',
  'invalid_state: only a pending request can be declined',
  'DB-06 C9: Declining a cancelled request fails with SQLSTATE P0001 (invalid_state)'
);

-- 33. Requester (User A) cancels the accepted request (test.req_a1_id):
-- First invoke cancel_exchange_request in a separate statement, then assert persisted statuses.
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT public.cancel_exchange_request(current_setting('test.req_a1_id')::uuid);

SELECT is(
  ARRAY[
    (SELECT status FROM public.exchange_requests WHERE id = current_setting('test.req_a1_id')::uuid),
    (SELECT completion_status FROM public.exchange_sessions WHERE request_id = current_setting('test.req_a1_id')::uuid)
  ],
  ARRAY['cancelled', 'cancelled'],
  'DB-06 C10: Requester cancelling an accepted request persists cancelled status on both request and session'
);

-- 34. Seed deterministic request d5555555 as postgres, accept it as Receiver (User B),
-- then cancel it as Receiver (User B) in a separate statement and verify persisted statuses.
SET LOCAL ROLE postgres;
INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'd5555555-5555-4555-8555-555555555555'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1222222-2222-4222-8222-222222222222'::uuid,
  'c2222222-2222-4222-8222-222222222222'::uuid,
  'Accepted request to be cancelled by receiver',
  now() + interval '6 days',
  'in_person'
);

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT public.accept_exchange_request('d5555555-5555-4555-8555-555555555555'::uuid);
SELECT public.cancel_exchange_request('d5555555-5555-4555-8555-555555555555'::uuid);

SELECT is(
  ARRAY[
    (SELECT status FROM public.exchange_requests WHERE id = 'd5555555-5555-4555-8555-555555555555'::uuid),
    (SELECT completion_status FROM public.exchange_sessions WHERE request_id = 'd5555555-5555-4555-8555-555555555555'::uuid)
  ],
  ARRAY['cancelled', 'cancelled'],
  'DB-06 C11: Receiver cancelling an accepted request persists cancelled status on both request and session'
);

-- =============================================================================
-- SECTION D: Session Confirmation & Idempotency (DB-07, DB-08, DB-09) (10 assertions)
-- =============================================================================
-- NOTE ON EARLY SESSION CONFIRMATION (Current Database Behaviour):
-- private.confirm_exchange_session(uuid) currently allows participants to
-- confirm a scheduled session before scheduled_datetime has passed. This section
-- tests that existing database behaviour directly; whether early confirmation
-- should be restricted remains an open product-policy decision (see report §6.1).

-- Seed deterministic request d6666666 as postgres for the two-sided confirmation lifecycle
SET LOCAL ROLE postgres;
INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'd6666666-6666-4666-8666-666666666666'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1111111-1111-4111-8111-111111111111'::uuid,
  'c2111111-1111-4111-8111-111111111111'::uuid,
  'Request for full two-sided session confirmation test',
  now() + interval '7 days',
  'online'
);

-- Accept d6666666 as Receiver (User B) and capture the actual session UUID while
-- operating as an authorised participant so outsider User C tests a real non-NULL UUID.
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT public.accept_exchange_request('d6666666-6666-4666-8666-666666666666'::uuid);

SELECT set_config(
  'test.session_d6_id',
  (SELECT id::text FROM public.exchange_sessions WHERE request_id = 'd6666666-6666-4666-8666-666666666666'::uuid),
  true
);

-- 35. Outsider (User C) cannot confirm the existing session (using captured real UUID test.session_d6_id -> P0002 session_not_found)
SELECT set_config('request.jwt.claim.sub', 'b3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"b3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid)$$,
  'P0002',
  'session_not_found',
  'DB-09 D1: Outsider calling confirm_exchange_session with real session UUID fails with SQLSTATE P0002 (session_not_found)'
);

-- 36. Unauthenticated caller cannot confirm a session (42501 not_authenticated)
SELECT set_config('request.jwt.claim.sub', '', true);
SELECT set_config('request.jwt.claims', '{}', true);

SELECT throws_ok(
  $$SELECT public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid)$$,
  '42501',
  'not_authenticated',
  'DB-09 D2: Unauthenticated caller calling confirm_exchange_session fails with SQLSTATE 42501 (not_authenticated)'
);

-- 37. First participant (Requester User A) confirms: sets requester_confirmed_at, leaves receiver_confirmed_at & completed_at NULL, and keeps session 'scheduled' and request 'accepted'
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid);

SELECT is(
  (
    SELECT ARRAY[
      s.completion_status,
      r.status,
      (s.requester_confirmed_at IS NOT NULL)::text,
      (s.receiver_confirmed_at IS NULL)::text,
      (s.completed_at IS NULL)::text
    ]
    FROM public.exchange_sessions s
    JOIN public.exchange_requests r ON r.id = s.request_id
    WHERE s.id = current_setting('test.session_d6_id')::uuid
  ),
  ARRAY['scheduled', 'accepted', 'true', 'true', 'true'],
  'DB-07 D3: First confirmation sets requester_confirmed_at only and keeps session scheduled and request accepted'
);

-- 38. Repeated confirmation by User A while scheduled is idempotent:
-- Capture ctid and requester_confirmed_at before the repeated call, execute
-- confirm_exchange_session in a separate statement (recording its returned
-- completion_status), and then verify persisted state, ctid, and timestamps.
SELECT set_config(
  'test.d6_ctid_scheduled',
  (SELECT ctid::text FROM public.exchange_sessions WHERE id = current_setting('test.session_d6_id')::uuid),
  true
);
SELECT set_config(
  'test.d6_req_confirmed_at',
  (SELECT requester_confirmed_at::text FROM public.exchange_sessions WHERE id = current_setting('test.session_d6_id')::uuid),
  true
);

SELECT set_config(
  'test.d6_repeat_a_sched_ret',
  (SELECT completion_status FROM public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid)),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      current_setting('test.d6_repeat_a_sched_ret'),
      s.completion_status,
      (s.ctid::text = current_setting('test.d6_ctid_scheduled'))::text,
      (s.requester_confirmed_at::text = current_setting('test.d6_req_confirmed_at'))::text,
      (s.receiver_confirmed_at IS NULL)::text,
      (s.completed_at IS NULL)::text
    ]
    FROM public.exchange_sessions s
    WHERE s.id = current_setting('test.session_d6_id')::uuid
  ),
  ARRAY['scheduled', 'scheduled', 'true', 'true', 'true', 'true'],
  'DB-08 D4: Repeated confirmation by User A while scheduled is a no-op (ctid and confirmation timestamps unchanged)'
);

-- 39. Second participant (Receiver User B) confirms: sets receiver_confirmed_at and completed_at, and marks both session and request 'completed'
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid);

SELECT is(
  (
    SELECT ARRAY[
      s.completion_status,
      r.status,
      (s.requester_confirmed_at IS NOT NULL)::text,
      (s.receiver_confirmed_at IS NOT NULL)::text,
      (s.completed_at IS NOT NULL)::text
    ]
    FROM public.exchange_sessions s
    JOIN public.exchange_requests r ON r.id = s.request_id
    WHERE s.id = current_setting('test.session_d6_id')::uuid
  ),
  ARRAY['completed', 'completed', 'true', 'true', 'true'],
  'DB-07 D5: Second participant confirmation sets receiver_confirmed_at and completed_at and marks both session and request completed'
);

-- Capture ctid and all three timestamps on the completed session before post-completion idempotency checks
SELECT set_config(
  'test.d6_ctid_completed',
  (SELECT ctid::text FROM public.exchange_sessions WHERE id = current_setting('test.session_d6_id')::uuid),
  true
);
SELECT set_config(
  'test.d6_rec_confirmed_at',
  (SELECT receiver_confirmed_at::text FROM public.exchange_sessions WHERE id = current_setting('test.session_d6_id')::uuid),
  true
);
SELECT set_config(
  'test.d6_completed_at',
  (SELECT completed_at::text FROM public.exchange_sessions WHERE id = current_setting('test.session_d6_id')::uuid),
  true
);

-- 40. Repeated confirmation by Receiver (User B) after completion is idempotent:
-- Call confirm_exchange_session in a separate statement first, then verify persisted state.
SELECT set_config(
  'test.d6_repeat_b_comp_ret',
  (SELECT completion_status FROM public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid)),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      current_setting('test.d6_repeat_b_comp_ret'),
      s.completion_status,
      (s.ctid::text = current_setting('test.d6_ctid_completed'))::text,
      (s.requester_confirmed_at::text = current_setting('test.d6_req_confirmed_at'))::text,
      (s.receiver_confirmed_at::text = current_setting('test.d6_rec_confirmed_at'))::text,
      (s.completed_at::text = current_setting('test.d6_completed_at'))::text
    ]
    FROM public.exchange_sessions s
    WHERE s.id = current_setting('test.session_d6_id')::uuid
  ),
  ARRAY['completed', 'completed', 'true', 'true', 'true', 'true'],
  'DB-08 D6: Repeated confirmation by User B after completion is a no-op (ctid and all timestamps unchanged)'
);

-- 41. Repeated confirmation by Requester (User A) after completion is also idempotent:
-- Switch to User A, call confirm_exchange_session in a separate statement, then verify persisted state.
SELECT set_config('request.jwt.claim.sub', 'b1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"b1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT set_config(
  'test.d6_repeat_a_comp_ret',
  (SELECT completion_status FROM public.confirm_exchange_session(current_setting('test.session_d6_id')::uuid)),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      current_setting('test.d6_repeat_a_comp_ret'),
      s.completion_status,
      (s.ctid::text = current_setting('test.d6_ctid_completed'))::text,
      (s.requester_confirmed_at::text = current_setting('test.d6_req_confirmed_at'))::text,
      (s.receiver_confirmed_at::text = current_setting('test.d6_rec_confirmed_at'))::text,
      (s.completed_at::text = current_setting('test.d6_completed_at'))::text
    ]
    FROM public.exchange_sessions s
    WHERE s.id = current_setting('test.session_d6_id')::uuid
  ),
  ARRAY['completed', 'completed', 'true', 'true', 'true', 'true'],
  'DB-08 D7: Repeated confirmation by User A after completion is a no-op (ctid and all timestamps unchanged)'
);

-- 42. Completed request cannot be cancelled (terminal state protection -> P0001)
SELECT throws_ok(
  $$SELECT public.cancel_exchange_request('d6666666-6666-4666-8666-666666666666'::uuid)$$,
  'P0001',
  'invalid_state: only a pending or accepted request can be cancelled',
  'DB-06 D8: Cancelling a completed request fails with SQLSTATE P0001 (invalid_state)'
);

-- 43. Cancelled session (from d5555555 in Section C) cannot be confirmed (P0001 invalid_state)
SELECT throws_ok(
  $$SELECT public.confirm_exchange_session(
      (SELECT id FROM public.exchange_sessions WHERE request_id = 'd5555555-5555-4555-8555-555555555555'::uuid)
    )$$,
  'P0001',
  'invalid_state: only a scheduled session of an accepted request can be confirmed',
  'DB-08 D9: Calling confirm_exchange_session on a cancelled session fails with SQLSTATE P0001 (invalid_state)'
);

-- 44. Participants cannot update notes on a cancelled session (RLS exchange_sessions_update_notes_participants blocks it)
UPDATE public.exchange_sessions
SET notes = 'Attempted note on cancelled session'
WHERE request_id = 'd5555555-5555-4555-8555-555555555555'::uuid;

SELECT is(
  (SELECT notes FROM public.exchange_sessions WHERE request_id = 'd5555555-5555-4555-8555-555555555555'::uuid),
  '',
  'DB-08 D10: RLS policy exchange_sessions_update_notes_participants prevents updating notes on a cancelled session'
);

-- =============================================================================
-- SECTION E: Database Integrity Constraints & Trigger Guards (4 assertions)
-- =============================================================================
-- Switch back to postgres to test table-level CHECK constraints and BEFORE UPDATE
-- guard triggers directly (defence-in-depth backstops).
SET LOCAL ROLE postgres;

-- 45. Constraint exchange_sessions_completion_requires_both prevents marking a session completed without both confirmation timestamps (23514)
-- Create and accept a fresh request d7777777 to get a clean scheduled session
INSERT INTO public.exchange_requests (
  id,
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'd7777777-7777-4777-8777-777777777777'::uuid,
  'b1111111-1111-4111-8111-111111111111'::uuid,
  'b2222222-2222-4222-8222-222222222222'::uuid,
  'c1111111-1111-4111-8111-111111111111'::uuid,
  'c2111111-1111-4111-8111-111111111111'::uuid,
  'Request for session constraint backstop checks',
  now() + interval '8 days',
  'online'
);

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'b2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"b2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT public.accept_exchange_request('d7777777-7777-4777-8777-777777777777'::uuid);

SET LOCAL ROLE postgres;

SELECT throws_ok(
  $$UPDATE public.exchange_sessions
    SET completion_status = 'completed',
        requester_confirmed_at = now(),
        completed_at = now()
    WHERE request_id = 'd7777777-7777-4777-8777-777777777777'::uuid$$,
  '23514',
  NULL,
  'DB-07 E1: Constraint exchange_sessions_completion_requires_both blocks completion when receiver_confirmed_at is NULL (23514)'
);

-- 46. Trigger guard_exchange_request_update blocks modifying immutable request fields (e.g. message) even for privileged callers (P0001)
SELECT throws_ok(
  $$UPDATE public.exchange_requests
    SET message = 'Tampered request message'
    WHERE id = 'd7777777-7777-4777-8777-777777777777'::uuid$$,
  'P0001',
  'request_fields_immutable: only the status of a request can change',
  'DB-06 E2: Trigger guard_exchange_request_update blocks modifying immutable request columns (P0001)'
);

-- 47. Trigger guard_exchange_session_update blocks modifying immutable session fields (e.g. scheduled_datetime) even for privileged callers (P0001)
SELECT throws_ok(
  $$UPDATE public.exchange_sessions
    SET scheduled_datetime = now() + interval '30 days'
    WHERE request_id = 'd7777777-7777-4777-8777-777777777777'::uuid$$,
  'P0001',
  'session_fields_immutable: request, schedule and id cannot change',
  'DB-07 E3: Trigger guard_exchange_session_update blocks modifying immutable session columns (P0001)'
);

-- 48. Trigger guard_exchange_session_update blocks altering or clearing a recorded confirmation timestamp on completed session d6666666 (P0001)
SELECT throws_ok(
  $$UPDATE public.exchange_sessions
    SET requester_confirmed_at = NULL
    WHERE request_id = 'd6666666-6666-4666-8666-666666666666'::uuid$$,
  'P0001',
  'confirmation_immutable: a recorded confirmation cannot be changed',
  'DB-08 E4: Trigger guard_exchange_session_update blocks clearing or altering a recorded confirmation timestamp (P0001)'
);

SELECT * FROM finish();

ROLLBACK;
