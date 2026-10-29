-- =============================================================================
-- SkillSwap pgTAP Automated Business-Rule Regression Test Suite
-- File: supabase/tests/05_reviews_workflow.test.sql
-- Scope: DB-10 (Review Rejection Before Session Completion),
--        DB-11 (Review Creation After Completion & Bilateral Direction),
--        DB-12 (Duplicate Review Prevention: Workflow RPC & Table Unique Constraint),
--        DB-13 (Review Rating & Comment Validation Boundaries),
--        DB-14 (Non-Participant Prevention, Table Immutability & Trigger Backstops).
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

SELECT plan(26);

-- =============================================================================
-- TEST FIXTURES: Fictional Users, Active Skills & Exchange Requests
-- =============================================================================
--   User A (Requester): e1111111-1111-4111-8111-111111111111 ('Ahmad Razak')
--   User B (Receiver):  e2222222-2222-4222-8222-222222222222 ('Sarah Lim')
--   User C (Outsider):  e3333333-3333-4333-8333-333333333333 ('Daniel Wong')
--
--   Active Offered Skills:
--     User A skill: f1111111-1111-4111-8111-111111111111 ('Excel Financial Modelling')
--     User B skill: f2222222-2222-4222-8222-222222222222 ('Graphic Design Fundamentals')
--
--   Exchange Requests (advanced via workflow RPCs below):
--     Request 1 (10000000-0000-4000-8000-000000000001):
--       Used in Section A (scheduled -> 1st confirm -> 2nd confirm) and Section B (bilateral reviews).
--     Request 2 (10000000-0000-4000-8000-000000000002):
--       Accepted and then cancelled -> tests review rejection on a cancelled session.
--     Request 3 (10000000-0000-4000-8000-000000000003):
--       Accepted and confirmed by both participants -> used in Section C (duplicate prevention).
--     Request 4 (10000000-0000-4000-8000-000000000004):
--       Accepted and confirmed by both participants -> used in Section D (rating/comment boundaries).

INSERT INTO auth.users (id, email, raw_user_meta_data, created_at, updated_at)
VALUES
  (
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'rev_user_a@example.test',
    '{"display_name": "Ahmad Razak"}'::jsonb,
    now(),
    now()
  ),
  (
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'rev_user_b@example.test',
    '{"display_name": "Sarah Lim"}'::jsonb,
    now(),
    now()
  ),
  (
    'e3333333-3333-4333-8333-333333333333'::uuid,
    'rev_user_c@example.test',
    '{"display_name": "Daniel Wong"}'::jsonb,
    now(),
    now()
  );

INSERT INTO public.skills (id, owner_user_id, skill_name, category, proficiency_level, skill_type, description, is_active)
VALUES
  (
    'f1111111-1111-4111-8111-111111111111'::uuid,
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'Excel Financial Modelling',
    'Business',
    'advanced',
    'offered',
    'Pivot tables, lookup functions, and financial models',
    true
  ),
  (
    'f2222222-2222-4222-8222-222222222222'::uuid,
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'Graphic Design Fundamentals',
    'Design',
    'expert',
    'offered',
    'Typography, layout composition, and brand assets',
    true
  );

-- Insert deterministic exchange requests as postgres (authenticated cannot specify id)
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
VALUES
  (
    '10000000-0000-4000-8000-000000000001'::uuid,
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'f1111111-1111-4111-8111-111111111111'::uuid,
    'f2222222-2222-4222-8222-222222222222'::uuid,
    'Request 1 for review eligibility and bilateral review creation tests',
    now() + interval '3 days',
    'online'
  ),
  (
    '10000000-0000-4000-8000-000000000002'::uuid,
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'f1111111-1111-4111-8111-111111111111'::uuid,
    'f2222222-2222-4222-8222-222222222222'::uuid,
    'Request 2 for cancelled session review rejection test',
    now() + interval '4 days',
    'in_person'
  ),
  (
    '10000000-0000-4000-8000-000000000003'::uuid,
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'f1111111-1111-4111-8111-111111111111'::uuid,
    'f2222222-2222-4222-8222-222222222222'::uuid,
    'Request 3 for duplicate review prevention tests',
    now() + interval '5 days',
    'online'
  ),
  (
    '10000000-0000-4000-8000-000000000004'::uuid,
    'e1111111-1111-4111-8111-111111111111'::uuid,
    'e2222222-2222-4222-8222-222222222222'::uuid,
    'f1111111-1111-4111-8111-111111111111'::uuid,
    'f2222222-2222-4222-8222-222222222222'::uuid,
    'Request 4 for rating and comment validation boundary tests',
    now() + interval '6 days',
    'online'
  );

-- Switch to authenticated Receiver (User B) to accept all 4 requests via workflow RPC
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'e2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"e2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT set_config(
  'test.session_1_id',
  (SELECT id::text FROM public.accept_exchange_request('10000000-0000-4000-8000-000000000001'::uuid)),
  true
);
SELECT set_config(
  'test.session_2_id',
  (SELECT id::text FROM public.accept_exchange_request('10000000-0000-4000-8000-000000000002'::uuid)),
  true
);
SELECT set_config(
  'test.session_3_id',
  (SELECT id::text FROM public.accept_exchange_request('10000000-0000-4000-8000-000000000003'::uuid)),
  true
);
SELECT set_config(
  'test.session_4_id',
  (SELECT id::text FROM public.accept_exchange_request('10000000-0000-4000-8000-000000000004'::uuid)),
  true
);

-- Cancel Request 2 so Session 2 transitions to 'cancelled'
SELECT public.cancel_exchange_request('10000000-0000-4000-8000-000000000002'::uuid);

-- Complete Sessions 3 and 4 via two-participant confirmation (User B then User A)
SELECT public.confirm_exchange_session(current_setting('test.session_3_id')::uuid);
SELECT public.confirm_exchange_session(current_setting('test.session_4_id')::uuid);

SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT public.confirm_exchange_session(current_setting('test.session_3_id')::uuid);
SELECT public.confirm_exchange_session(current_setting('test.session_4_id')::uuid);

-- =============================================================================
-- SECTION A: Review Eligibility (6 assertions)
-- =============================================================================

-- 1. Unauthenticated caller (auth.uid() IS NULL) cannot submit a review (42501)
SELECT set_config('request.jwt.claim.sub', '', true);
SELECT set_config('request.jwt.claims', '{}', true);

SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_1_id')::uuid, 5, 'Unauthenticated attempt')$$,
  '42501',
  'not_authenticated',
  'DB-14 A1: Calling create_review when auth.uid() is NULL fails with SQLSTATE 42501 (not_authenticated)'
);

-- Restore authenticated Requester (User A)
SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 2. Nonexistent session ID is rejected with P0002 (session_not_found)
SELECT throws_ok(
  $$SELECT public.create_review('99999999-9999-4999-8999-999999999999'::uuid, 5, 'Nonexistent session')$$,
  'P0002',
  'session_not_found',
  'DB-14 A2: Calling create_review for a nonexistent session ID fails with SQLSTATE P0002 (session_not_found)'
);

-- 3. Review cannot be submitted for a scheduled session with zero confirmations (P0001)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_1_id')::uuid, 5, 'Premature review before any confirmation')$$,
  'P0001',
  'session_not_completed: reviews are only allowed after both participants confirm',
  'DB-10 A3: Calling create_review on a scheduled session with zero confirmations fails with SQLSTATE P0001 (session_not_completed)'
);

-- 4. First participant (User A) confirms Session 1; review is still rejected while awaiting second participant confirmation (P0001)
SELECT public.confirm_exchange_session(current_setting('test.session_1_id')::uuid);

SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_1_id')::uuid, 5, 'Premature review after only one confirmation')$$,
  'P0001',
  'session_not_completed: reviews are only allowed after both participants confirm',
  'DB-10 A4: Calling create_review after only one participant has confirmed still fails with SQLSTATE P0001 (session_not_completed)'
);

-- 5. Review cannot be submitted for a cancelled session (Session 2 -> P0001)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_2_id')::uuid, 4, 'Review on cancelled session')$$,
  'P0001',
  'session_not_completed: reviews are only allowed after both participants confirm',
  'DB-10 A5: Calling create_review on a cancelled session fails with SQLSTATE P0001 (session_not_completed)'
);

-- Now second participant (Receiver User B) confirms Session 1 so it becomes 'completed'
SELECT set_config('request.jwt.claim.sub', 'e2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"e2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);
SELECT public.confirm_exchange_session(current_setting('test.session_1_id')::uuid);

-- 6. Outsider (User C) cannot review an existing completed session (Session 1 -> P0002)
SELECT set_config('request.jwt.claim.sub', 'e3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"e3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_1_id')::uuid, 5, 'Outsider attempting to review Session 1')$$,
  'P0002',
  'session_not_found',
  'DB-14 A6: Outsider (User C) calling create_review on an existing completed session fails with SQLSTATE P0002 (session_not_found)'
);

-- =============================================================================
-- SECTION B: Successful Review Creation & Bilateral Direction (3 assertions)
-- =============================================================================

-- 7. Requester (User A) reviews Receiver (User B) after Session 1 completion:
-- Execute create_review in a standalone statement first, then verify persisted row.
SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT set_config(
  'test.review_1_a_id',
  (
    SELECT id::text
    FROM public.create_review(
      current_setting('test.session_1_id')::uuid,
      5,
      'Clear and well-structured design walkthrough!'
    )
  ),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      (rv.session_id = current_setting('test.session_1_id')::uuid)::text,
      rv.reviewer_user_id::text,
      rv.reviewee_user_id::text,
      rv.rating::text,
      rv.comment,
      (rv.created_at IS NOT NULL)::text
    ]
    FROM public.reviews rv
    WHERE rv.id = current_setting('test.review_1_a_id')::uuid
  ),
  ARRAY[
    'true',
    'e1111111-1111-4111-8111-111111111111',
    'e2222222-2222-4222-8222-222222222222',
    '5',
    'Clear and well-structured design walkthrough!',
    'true'
  ],
  'DB-11 B1: Requester (User A) review derives reviewer_user_id = User A and reviewee_user_id = User B and persists rating and comment'
);

-- 8. Receiver (User B) independently reviews Requester (User A) on the same completed Session 1 (reverse direction):
-- Execute create_review in a standalone statement first, then verify persisted row.
SELECT set_config('request.jwt.claim.sub', 'e2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"e2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT set_config(
  'test.review_1_b_id',
  (
    SELECT id::text
    FROM public.create_review(
      current_setting('test.session_1_id')::uuid,
      4,
      'Helpful Excel formulas and practical examples.'
    )
  ),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      (rv.session_id = current_setting('test.session_1_id')::uuid)::text,
      rv.reviewer_user_id::text,
      rv.reviewee_user_id::text,
      rv.rating::text,
      rv.comment,
      (rv.created_at IS NOT NULL)::text
    ]
    FROM public.reviews rv
    WHERE rv.id = current_setting('test.review_1_b_id')::uuid
  ),
  ARRAY[
    'true',
    'e2222222-2222-4222-8222-222222222222',
    'e1111111-1111-4111-8111-111111111111',
    '4',
    'Helpful Excel formulas and practical examples.',
    'true'
  ],
  'DB-11 B2: Receiver (User B) review derives reviewer_user_id = User B and reviewee_user_id = User A on the same completed session'
);

-- 9. Authenticated members (including non-participant User C) can read both reviews on Session 1 under reviews_select_authenticated
SELECT set_config('request.jwt.claim.sub', 'e3333333-3333-4333-8333-333333333333', true);
SELECT set_config('request.jwt.claims', '{"sub":"e3333333-3333-4333-8333-333333333333","role":"authenticated"}', true);

SELECT is(
  ARRAY(
    SELECT rv.reviewer_user_id::text || '->' || rv.reviewee_user_id::text || ':' || rv.rating::text
    FROM public.reviews rv
    WHERE rv.session_id = current_setting('test.session_1_id')::uuid
    ORDER BY rv.reviewer_user_id
  ),
  ARRAY[
    'e1111111-1111-4111-8111-111111111111->e2222222-2222-4222-8222-222222222222:5',
    'e2222222-2222-4222-8222-222222222222->e1111111-1111-4111-8111-111111111111:4'
  ],
  'DB-11 B3: Both bilateral reviews are linked to Session 1 and readable by authenticated members via reviews_select_authenticated'
);

-- =============================================================================
-- SECTION C: Duplicate Prevention (4 assertions)
-- =============================================================================
-- Use completed Session 3 (test.session_3_id) to verify:
--   1. User A submits their first review on Session 3.
--   2. User A cannot submit a second review on Session 3 via create_review (23505 review_already_exists).
--   3. The second participant (User B) can still submit their own review on Session 3.
--   4. User B cannot submit a second review on Session 3 via create_review (23505 review_already_exists).
--   5. The database-level unique constraint reviews_one_per_reviewer_per_session independently blocks duplicate inserts (23505).

SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- User A submits their first review for Session 3 in a standalone statement
SELECT public.create_review(
  current_setting('test.session_3_id')::uuid,
  4,
  'Initial review from User A on Session 3'
);

-- 10. A participant (User A) cannot submit a second review for the same session via create_review (23505)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_3_id')::uuid, 5, 'Duplicate review attempt by User A')$$,
  '23505',
  'review_already_exists: you have already reviewed this session',
  'DB-12 C1: Second review by User A on the same session fails in private.create_review with SQLSTATE 23505 (review_already_exists)'
);

-- 11. The second participant (Receiver User B) may still submit their own review for Session 3 after User A's duplicate is rejected
SELECT set_config('request.jwt.claim.sub', 'e2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"e2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT set_config(
  'test.review_3_b_id',
  (
    SELECT id::text
    FROM public.create_review(
      current_setting('test.session_3_id')::uuid,
      5,
      'User B independent review on Session 3'
    )
  ),
  true
);

SELECT is(
  (
    SELECT ARRAY[
      (SELECT count(*)::text FROM public.reviews WHERE session_id = current_setting('test.session_3_id')::uuid),
      rv.reviewer_user_id::text,
      rv.reviewee_user_id::text,
      rv.rating::text
    ]
    FROM public.reviews rv
    WHERE rv.id = current_setting('test.review_3_b_id')::uuid
  ),
  ARRAY[
    '2',
    'e2222222-2222-4222-8222-222222222222',
    'e1111111-1111-4111-8111-111111111111',
    '5'
  ],
  'DB-12 C2: Second participant (User B) can still submit their own review for Session 3 after User A duplicate was blocked'
);

-- 12. Receiver (User B) also cannot submit a second review for Session 3 via create_review (23505)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_3_id')::uuid, 3, 'Duplicate review attempt by User B')$$,
  '23505',
  'review_already_exists: you have already reviewed this session',
  'DB-12 C3: Second review by User B on the same session also fails in private.create_review with SQLSTATE 23505 (review_already_exists)'
);

-- 13. Database-level UNIQUE (session_id, reviewer_user_id) constraint independently blocks duplicate inserts when bypassing create_review
SET LOCAL ROLE postgres;

SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_3_id')::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      'e2222222-2222-4222-8222-222222222222'::uuid,
      5,
      'Direct insert bypassing create_review'
    )$$,
  '23505',
  'duplicate key value violates unique constraint "reviews_one_per_reviewer_per_session"',
  'DB-12 C4: Table unique constraint reviews_one_per_reviewer_per_session independently blocks duplicate (session_id, reviewer_user_id) rows (23505)'
);

-- =============================================================================
-- SECTION D: Rating and Comment Validation (6 assertions)
-- =============================================================================
-- Use completed Session 4 (test.session_4_id, which has zero reviews so far)
-- so all negative and positive boundary checks are completely isolated from
-- duplicate-review checks.

SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 14. Rating 0 is rejected with SQLSTATE 22023 (invalid_rating)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_4_id')::uuid, 0, 'Rating zero')$$,
  '22023',
  'invalid_rating: rating must be between 1 and 5',
  'DB-13 D1: Rating 0 is rejected by create_review with SQLSTATE 22023 (invalid_rating)'
);

-- 15. Rating 6 is rejected with SQLSTATE 22023 (invalid_rating)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_4_id')::uuid, 6, 'Rating six')$$,
  '22023',
  'invalid_rating: rating must be between 1 and 5',
  'DB-13 D2: Rating 6 is rejected by create_review with SQLSTATE 22023 (invalid_rating)'
);

-- 16. NULL rating is rejected with SQLSTATE 22023 (invalid_rating)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_4_id')::uuid, NULL, 'Null rating')$$,
  '22023',
  'invalid_rating: rating must be between 1 and 5',
  'DB-13 D3: NULL rating is rejected by create_review with SQLSTATE 22023 (invalid_rating)'
);

-- 17. Comment longer than 500 trimmed characters is rejected with SQLSTATE 22023 (invalid_comment)
SELECT throws_ok(
  $$SELECT public.create_review(current_setting('test.session_4_id')::uuid, 5, repeat('C', 501))$$,
  '22023',
  'invalid_comment: comment must be at most 500 characters',
  'DB-11 D4: Comment exceeding 500 characters is rejected by create_review with SQLSTATE 22023 (invalid_comment)'
);

-- 18. Minimum boundary Rating 1 and NULL comment (coalesced to empty string '') are accepted for User A on Session 4
SELECT set_config(
  'test.review_4_a_id',
  (
    SELECT id::text
    FROM public.create_review(
      current_setting('test.session_4_id')::uuid,
      1,
      NULL
    )
  ),
  true
);

SELECT is(
  (
    SELECT ARRAY[rv.rating::text, rv.comment]
    FROM public.reviews rv
    WHERE rv.id = current_setting('test.review_4_a_id')::uuid
  ),
  ARRAY['1', ''],
  'DB-13 D5: Rating 1 is accepted and a NULL comment is stored as an empty string default'
);

-- 19. Maximum boundary Rating 5 and comment with surrounding spaces (trimmed via btrim) are accepted for User B on Session 4
SELECT set_config('request.jwt.claim.sub', 'e2222222-2222-4222-8222-222222222222', true);
SELECT set_config('request.jwt.claims', '{"sub":"e2222222-2222-4222-8222-222222222222","role":"authenticated"}', true);

SELECT set_config(
  'test.review_4_b_id',
  (
    SELECT id::text
    FROM public.create_review(
      current_setting('test.session_4_id')::uuid,
      5,
      '   Practical tips and patient explanations.   '
    )
  ),
  true
);

SELECT is(
  (
    SELECT ARRAY[rv.rating::text, rv.comment]
    FROM public.reviews rv
    WHERE rv.id = current_setting('test.review_4_b_id')::uuid
  ),
  ARRAY['5', 'Practical tips and patient explanations.'],
  'DB-11 D6: Rating 5 is accepted and leading/trailing spaces are trimmed from comment'
);

-- =============================================================================
-- SECTION E: Review Permissions, Immutability & Trigger/Constraint Backstops (7 assertions)
-- =============================================================================

-- 20. Authenticated member cannot directly INSERT into public.reviews (42501)
SELECT set_config('request.jwt.claim.sub', 'e1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"e1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_1_id')::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      'e2222222-2222-4222-8222-222222222222'::uuid,
      5,
      'Direct insert attempt by authenticated user'
    )$$,
  '42501',
  NULL,
  'DB-14 E1: Authenticated members cannot directly INSERT into public.reviews (42501)'
);

-- 21. Authenticated member cannot UPDATE a submitted review (42501)
SELECT throws_ok(
  $$UPDATE public.reviews
    SET rating = 2,
        comment = 'Attempted edit of submitted review'
    WHERE id = current_setting('test.review_1_a_id')::uuid$$,
  '42501',
  NULL,
  'DB-14 E2: Authenticated members cannot UPDATE submitted reviews in public.reviews (42501)'
);

-- 22. Authenticated member cannot DELETE a submitted review (42501)
SELECT throws_ok(
  $$DELETE FROM public.reviews
    WHERE id = current_setting('test.review_1_a_id')::uuid$$,
  '42501',
  NULL,
  'DB-14 E3: Authenticated members cannot DELETE submitted reviews from public.reviews (42501)'
);

-- Switch to postgres to exercise the BEFORE INSERT trigger private.validate_review_insert()
-- and table-level CHECK constraints directly as defence-in-depth backstops.
SET LOCAL ROLE postgres;

-- 23. Trigger private.validate_review_insert() independently blocks inserting a review for a non-completed (cancelled) session (P0001)
SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_2_id')::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      'e2222222-2222-4222-8222-222222222222'::uuid,
      5,
      'Direct insert on cancelled Session 2'
    )$$,
  'P0001',
  'session_not_completed: reviews are only allowed after both participants confirm',
  'DB-10 E4: Trigger validate_review_insert independently rejects inserting a review for a non-completed session (P0001)'
);

-- 24. Trigger private.validate_review_insert() independently blocks an outsider reviewer on a completed session (42501)
SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_1_id')::uuid,
      'e3333333-3333-4333-8333-333333333333'::uuid,
      'e2222222-2222-4222-8222-222222222222'::uuid,
      5,
      'Direct insert by outsider User C'
    )$$,
  '42501',
  'review_not_permitted: reviewer must be a participant reviewing the other participant',
  'DB-14 E5: Trigger validate_review_insert independently rejects an outsider reviewer on a completed session (42501)'
);

-- 25. Trigger private.validate_review_insert() independently blocks a participant attempting to review themselves on a completed session (42501)
SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_1_id')::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      5,
      'Direct self-review insert attempt'
    )$$,
  '42501',
  'review_not_permitted: reviewer must be a participant reviewing the other participant',
  'DB-14 E6: Trigger validate_review_insert independently rejects a self-review where reviewer equals reviewee (42501)'
);

-- 26. Table constraint reviews_rating_range independently blocks out-of-range ratings on direct insert (23514)
SELECT throws_ok(
  $$INSERT INTO public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
    VALUES (
      current_setting('test.session_1_id')::uuid,
      'e1111111-1111-4111-8111-111111111111'::uuid,
      'e2222222-2222-4222-8222-222222222222'::uuid,
      6,
      'Direct insert with out-of-range rating 6'
    )$$,
  '23514',
  NULL,
  'DB-13 E7: Table CHECK constraint reviews_rating_range independently blocks ratings outside 1..5 on direct insert (23514)'
);

SELECT * FROM finish();

ROLLBACK;
