-- =============================================================================
-- SkillSwap pgTAP Automated Business-Rule Regression Test Suite
-- File: supabase/tests/03_profiles_and_skills_rules.test.sql
-- Scope: DB-02 (Profile Creation, Sanitisation, and Constraints) and
--        DB-03 (Skills Constraints, Duplicate Active Index, Referenced-Skill
--        Protection, and Immutable Identity Trigger).
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

SELECT plan(31);

-- =============================================================================
-- SECTION A: Automatic Profile Creation & Display Name Sanitisation (6 assertions)
-- =============================================================================
-- Fictional registration test accounts:
--   User 1 (Valid trimmed name):   a1111111-1111-4111-8111-111111111111
--   User 2 (Missing display_name): a2222222-2222-4222-8222-222222222222
--   User 3 (Too short < 2 chars):  a3333333-3333-4333-8333-333333333333
--   User 4 (Too long > 60 chars):  a4444444-4444-4444-8444-444444444444
--   User 5 (Non-string JSON):      a5555555-5555-4555-8555-555555555555
--   User 6 (Receiver for req):     a6666666-6666-4666-8666-666666666666

INSERT INTO auth.users (id, email, raw_user_meta_data, created_at, updated_at)
VALUES
  (
    'a1111111-1111-4111-8111-111111111111'::uuid,
    'trimmed@example.test',
    '{"display_name": "   Nadia Karim \n\t "}'::jsonb,
    now(),
    now()
  ),
  (
    'a2222222-2222-4222-8222-222222222222'::uuid,
    'missing_name@example.test',
    '{}'::jsonb,
    now(),
    now()
  ),
  (
    'a3333333-3333-4333-8333-333333333333'::uuid,
    'short_name@example.test',
    '{"display_name": "A"}'::jsonb,
    now(),
    now()
  ),
  (
    'a4444444-4444-4444-8444-444444444444'::uuid,
    'long_name@example.test',
    jsonb_build_object('display_name', repeat('X', 61)),
    now(),
    now()
  ),
  (
    'a5555555-5555-4555-8555-555555555555'::uuid,
    'non_string@example.test',
    '{"display_name": 12345}'::jsonb,
    now(),
    now()
  ),
  (
    'a6666666-6666-4666-8666-666666666666'::uuid,
    'partner@example.test',
    '{"display_name": "Tariq Mansoor"}'::jsonb,
    now(),
    now()
  );

-- 1. Valid display_name with surrounding whitespace/newlines is trimmed and stored
SELECT is(
  (SELECT display_name FROM public.profiles WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid),
  'Nadia Karim',
  'DB-02 A1: handle_new_user trims surrounding whitespace and control characters from display_name'
);

-- 2. Missing display_name falls back to 'New member'
SELECT is(
  (SELECT display_name FROM public.profiles WHERE user_id = 'a2222222-2222-4222-8222-222222222222'::uuid),
  'New member',
  'DB-02 A2: handle_new_user falls back to New member when display_name is missing'
);

-- 3. Too-short display_name (< 2 chars after trim) falls back to 'New member'
SELECT is(
  (SELECT display_name FROM public.profiles WHERE user_id = 'a3333333-3333-4333-8333-333333333333'::uuid),
  'New member',
  'DB-02 A3: handle_new_user falls back to New member when display_name is shorter than 2 characters'
);

-- 4. Too-long display_name (> 60 chars) falls back to 'New member'
SELECT is(
  (SELECT display_name FROM public.profiles WHERE user_id = 'a4444444-4444-4444-8444-444444444444'::uuid),
  'New member',
  'DB-02 A4: handle_new_user falls back to New member when display_name exceeds 60 characters'
);

-- 5. Non-string JSON display_name falls back to 'New member'
SELECT is(
  (SELECT display_name FROM public.profiles WHERE user_id = 'a5555555-5555-4555-8555-555555555555'::uuid),
  'New member',
  'DB-02 A5: handle_new_user falls back to New member when display_name is not a JSON string'
);

-- 6. Default profile columns are initialised accurately
SELECT is(
  (
    SELECT ARRAY[bio, interests::text, learning_preferences, availability]
    FROM public.profiles
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
  ),
  ARRAY['', '{}', '', ''],
  'DB-02 A6: Newly created profile initialises bio, interests, learning_preferences, and availability defaults'
);

-- =============================================================================
-- SECTION B: Profile Constraints & Timestamp Trigger (8 assertions)
-- =============================================================================

-- Attempt to set User 1's updated_at to yesterday as postgres. Because the
-- BEFORE UPDATE trigger profiles_set_updated_at (private.set_updated_at())
-- runs on every UPDATE, it immediately overwrites the attempted historical
-- timestamp with the current transaction's now().
UPDATE public.profiles
SET updated_at = now() - interval '1 day'
WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid;

-- 7. Immediately verify that profiles_set_updated_at overrode the backdated value with now()
SELECT is(
  (SELECT updated_at FROM public.profiles WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid),
  now(),
  'DB-02 B1: Trigger profiles_set_updated_at overrides an attempted historical updated_at with now()'
);

-- Switch to authenticated User 1
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', 'a1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"a1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

-- 8. Valid profile update (2-char display_name, 10 valid interests, bio, preferences, availability) succeeds
SELECT lives_ok(
  $$UPDATE public.profiles
    SET display_name = 'NK',
        bio = 'Software engineer interested in design systems.',
        interests = ARRAY['Python', 'SQL', 'UI Design', 'Music', 'Cooking', 'Languages', 'Chess', 'Writing', 'Photography', 'Running'],
        learning_preferences = 'Hands-on pair sessions',
        availability = 'Weekdays after 18:00 UTC'
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  'DB-02 B2: Valid profile update with 2-char display_name and 10 valid interests succeeds'
);

-- 9. Invalid display_name too short (< 2 trimmed characters) fails with 23514
SELECT throws_ok(
  $$UPDATE public.profiles
    SET display_name = ' A '
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B3: display_name shorter than 2 trimmed characters fails check constraint (23514)'
);

-- 10. Invalid display_name too long (> 60 trimmed characters) fails with 23514
SELECT throws_ok(
  $$UPDATE public.profiles
    SET display_name = repeat('N', 61)
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B4: display_name exceeding 60 characters fails check constraint (23514)'
);

-- 11. Bio exceeding 500 characters fails with 23514
SELECT throws_ok(
  $$UPDATE public.profiles
    SET bio = repeat('B', 501)
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B5: bio exceeding 500 characters fails check constraint (23514)'
);

-- 12. More than 10 interests fails private.valid_interests check constraint (23514)
SELECT throws_ok(
  $$UPDATE public.profiles
    SET interests = ARRAY['1','2','3','4','5','6','7','8','9','10','11']
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B6: interests array with more than 10 items fails profiles_interests_valid (23514)'
);

-- 13. Empty or whitespace-only interest item fails private.valid_interests check constraint (23514)
SELECT throws_ok(
  $$UPDATE public.profiles
    SET interests = ARRAY['Python', '   ']
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B7: interests array containing a whitespace-only item fails profiles_interests_valid (23514)'
);

-- 14. Interest item exceeding 40 characters fails private.valid_interests check constraint (23514)
SELECT throws_ok(
  $$UPDATE public.profiles
    SET interests = ARRAY[repeat('I', 41)]
    WHERE user_id = 'a1111111-1111-4111-8111-111111111111'::uuid$$,
  '23514',
  NULL,
  'DB-02 B8: interest item exceeding 40 characters fails profiles_interests_valid (23514)'
);

-- =============================================================================
-- SECTION C: Skills Constraints (5 assertions)
-- =============================================================================

-- 15. Skill name shorter than 2 trimmed characters fails skills_name_length (23514)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, ' Z ', 'Technology', 'intermediate', 'offered', 'Too short name')$$,
  '23514',
  NULL,
  'DB-03 C1: skill_name shorter than 2 trimmed characters fails skills_name_length (23514)'
);

-- 16. Invalid skill category fails skills_category_allowed (23514)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'Quantum Computing', 'InvalidCategory', 'intermediate', 'offered', 'Bad category')$$,
  '23514',
  NULL,
  'DB-03 C2: Disallowed skill category fails skills_category_allowed (23514)'
);

-- 17. Invalid proficiency_level fails skills_level_allowed (23514)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'Data Analysis', 'Technology', 'master', 'offered', 'Bad level')$$,
  '23514',
  NULL,
  'DB-03 C3: Disallowed proficiency_level fails skills_level_allowed (23514)'
);

-- 18. Invalid skill_type fails skills_type_allowed (23514)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'Data Analysis', 'Technology', 'intermediate', 'offer', 'Bad type')$$,
  '23514',
  NULL,
  'DB-03 C4: Disallowed skill_type fails skills_type_allowed (23514)'
);

-- 19. Skill description exceeding 500 characters fails skills_description_length (23514)
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'Data Analysis', 'Technology', 'intermediate', 'offered', repeat('D', 501))$$,
  '23514',
  NULL,
  'DB-03 C5: Skill description exceeding 500 characters fails skills_description_length (23514)'
);

-- =============================================================================
-- SECTION D: Duplicate Active Skills & Soft-Deactivation Replacement (4 assertions)
-- =============================================================================

-- Insert initial active offered skill 'SQL Optimization' for User 1
INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
VALUES (
  'a1111111-1111-4111-8111-111111111111'::uuid,
  'SQL Optimization',
  'Technology',
  'advanced',
  'offered',
  'Query tuning and indexing'
);

-- 20. Duplicate active skill name (case-insensitive and trimmed) for same owner and skill_type fails with 23505
SELECT throws_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, '  sql optimization  ', 'Technology', 'expert', 'offered', 'Duplicate active offer')$$,
  '23505',
  NULL,
  'DB-03 D1: Duplicate active skill name (case-insensitive, trimmed) for same owner and skill_type fails with 23505'
);

-- 21. Same skill name for same owner with different skill_type ('wanted') is permitted
SELECT lives_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'SQL Optimization', 'Technology', 'expert', 'wanted', 'Want advanced partitioning tips')$$,
  'DB-03 D2: Same skill name with different skill_type (wanted vs offered) is permitted'
);

-- 22. Soft-deactivating the original offered skill (is_active = false) succeeds
UPDATE public.skills
SET is_active = false
WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
  AND skill_name = 'SQL Optimization'
  AND skill_type = 'offered';

SELECT is(
  (
    SELECT is_active
    FROM public.skills
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'offered'
  ),
  false,
  'DB-03 D3: Owner can soft-deactivate an active skill by setting is_active = false'
);

-- 23. After soft-deactivation, inserting a new active replacement skill with the same name and type succeeds
SELECT lives_ok(
  $$INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
    VALUES ('a1111111-1111-4111-8111-111111111111'::uuid, 'SQL Optimization', 'Technology', 'expert', 'offered', 'Replacement active listing')$$,
  'DB-03 D4: Soft-deactivation permits creating a new active replacement skill with the same name and skill_type'
);

-- =============================================================================
-- SECTION E: Referenced-Skill Protection (private.protect_referenced_skill) (5 assertions)
-- =============================================================================

-- User 6 creates an offered skill so User 1 can send an exchange request referencing
-- User 1's active 'SQL Optimization' skill and User 6's 'Brand Illustration' skill.
SELECT set_config('request.jwt.claim.sub', 'a6666666-6666-4666-8666-666666666666', true);
SELECT set_config('request.jwt.claims', '{"sub":"a6666666-6666-4666-8666-666666666666","role":"authenticated"}', true);

INSERT INTO public.skills (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
VALUES (
  'a6666666-6666-4666-8666-666666666666'::uuid,
  'Brand Illustration',
  'Design',
  'advanced',
  'offered',
  'Vector illustration coaching'
);

-- Switch back to User 1 and create an exchange request referencing both active offered skills
SELECT set_config('request.jwt.claim.sub', 'a1111111-1111-4111-8111-111111111111', true);
SELECT set_config('request.jwt.claims', '{"sub":"a1111111-1111-4111-8111-111111111111","role":"authenticated"}', true);

INSERT INTO public.exchange_requests (
  requester_user_id,
  receiver_user_id,
  offered_skill_id,
  wanted_skill_id,
  message,
  proposed_datetime,
  format
)
VALUES (
  'a1111111-1111-4111-8111-111111111111'::uuid,
  'a6666666-6666-4666-8666-666666666666'::uuid,
  (
    SELECT id FROM public.skills
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'offered'
      AND is_active = true
  ),
  (
    SELECT id FROM public.skills
    WHERE owner_user_id = 'a6666666-6666-4666-8666-666666666666'::uuid
      AND skill_name = 'Brand Illustration'
      AND skill_type = 'offered'
      AND is_active = true
  ),
  'Let us trade SQL Optimization for Brand Illustration!',
  now() + interval '5 days',
  'online'
);

-- 24. Editing skill_name on a skill referenced by an exchange request fails with P0001 (skill_in_use)
SELECT throws_ok(
  $$UPDATE public.skills
    SET skill_name = 'Renamed SQL Skill'
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'offered'
      AND is_active = true$$,
  'P0001',
  'skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead',
  'DB-03 E1: Editing skill_name on a referenced skill is blocked by protect_referenced_skill (P0001)'
);

-- 25. Editing only category on a referenced skill fails with P0001 (skill_in_use)
SELECT throws_ok(
  $$UPDATE public.skills
    SET category = 'Academics'
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'offered'
      AND is_active = true$$,
  'P0001',
  'skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead',
  'DB-03 E2: Editing category on a referenced skill is blocked by protect_referenced_skill (P0001)'
);

-- 26. Editing only proficiency_level on a referenced skill fails with P0001 (skill_in_use)
SELECT throws_ok(
  $$UPDATE public.skills
    SET proficiency_level = 'beginner'
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'offered'
      AND is_active = true$$,
  'P0001',
  'skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead',
  'DB-03 E3: Editing proficiency_level on a referenced skill is blocked by protect_referenced_skill (P0001)'
);

-- 27. Editing description on the receiver's referenced wanted_skill_id also fails with P0001 (skill_in_use)
SELECT set_config('request.jwt.claim.sub', 'a6666666-6666-4666-8666-666666666666', true);
SELECT set_config('request.jwt.claims', '{"sub":"a6666666-6666-4666-8666-666666666666","role":"authenticated"}', true);

SELECT throws_ok(
  $$UPDATE public.skills
    SET description = 'Changed description after request'
    WHERE owner_user_id = 'a6666666-6666-4666-8666-666666666666'::uuid
      AND skill_name = 'Brand Illustration'$$,
  'P0001',
  'skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead',
  'DB-03 E4: Editing description on receiver referenced skill is blocked by protect_referenced_skill (P0001)'
);

-- 28. Soft-deactivating (is_active = false) a referenced skill is still permitted
SELECT lives_ok(
  $$UPDATE public.skills
    SET is_active = false
    WHERE owner_user_id = 'a6666666-6666-4666-8666-666666666666'::uuid
      AND skill_name = 'Brand Illustration'$$,
  'DB-03 E5: Soft-deactivating (is_active = false) a skill referenced by an exchange request succeeds'
);

-- =============================================================================
-- SECTION F: Immutable Skill Identity Trigger (private.guard_skill_identity) (3 assertions)
-- =============================================================================
-- Switch back to postgres (which has table-level UPDATE privileges) so the tests
-- reach the BEFORE UPDATE trigger private.guard_skill_identity() directly.
-- Target User 1's unreferenced 'wanted' skill ('SQL Optimization') so each test
-- isolates private.guard_skill_identity() cleanly.
SET LOCAL ROLE postgres;

-- 29. Trigger skills_guard_identity blocks changing skill_type even for privileged callers
SELECT throws_ok(
  $$UPDATE public.skills
    SET skill_type = 'offered'
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'wanted'$$,
  'P0001',
  'skill_identity_immutable: id, owner and type of a skill cannot change',
  'DB-03 F1: Trigger guard_skill_identity blocks changing skill_type (P0001)'
);

-- 30. Trigger skills_guard_identity blocks changing owner_user_id even for privileged callers
SELECT throws_ok(
  $$UPDATE public.skills
    SET owner_user_id = 'a2222222-2222-4222-8222-222222222222'::uuid
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'wanted'$$,
  'P0001',
  'skill_identity_immutable: id, owner and type of a skill cannot change',
  'DB-03 F2: Trigger guard_skill_identity blocks changing owner_user_id (P0001)'
);

-- 31. Trigger skills_guard_identity blocks changing id even for privileged callers
SELECT throws_ok(
  $$UPDATE public.skills
    SET id = '99999999-9999-4999-8999-999999999999'::uuid
    WHERE owner_user_id = 'a1111111-1111-4111-8111-111111111111'::uuid
      AND skill_name = 'SQL Optimization'
      AND skill_type = 'wanted'$$,
  'P0001',
  'skill_identity_immutable: id, owner and type of a skill cannot change',
  'DB-03 F3: Trigger guard_skill_identity blocks changing skill id (P0001)'
);

SELECT * FROM finish();

ROLLBACK;
