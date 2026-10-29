# SkillSwap — Database Testing Report (Phase 3 Manual SQL Verification)

- **Project:** SkillSwap — AI-Powered Peer-to-Peer Skill Exchange Platform
- **Baseline Specification:** [SkillSwap_PRD_v1.0.md](../SkillSwap_PRD_v1.0.md)
- **Technical Decisions:** [docs/decisions.md](decisions.md)
- **Target Layer:** Supabase PostgreSQL Schema, Row Level Security (RLS), Triggers, and Workflow Functions

---

## 1. Executive Summary & Evidence Classification

This report documents the results of the manual database workflow testing and static SQL inspection conducted against the eight SkillSwap Supabase PostgreSQL migrations (`20261028220100_foundation.sql` through `20261028220800_public_wrappers_and_permissions.sql`).

### Evidence Classification & Verification Boundaries

To maintain strict transparency and audit honesty, every finding in this report is classified into one of three distinct evidence categories:

1. **Manually Observed PASS (User-Provided SQL Editor Runs & Dashboard Screenshots):**
   - Executed manually by the project owner in the hosted Supabase SQL Editor using transactional test blocks (`BEGIN ... ROLLBACK`) and simulated session claims (`set_config('request.jwt.claims', ...)` / `SET LOCAL ROLE authenticated`), or verified via user-provided Supabase Dashboard screenshots.
   - Where a test group contains both manually executed scenarios and additional SQL-enforced rules that were not individually run in the SQL Editor, this report marks the group as **PASS (Manually Observed Core Scenarios; Remaining Branches Statically Verified)** rather than claiming every sub-branch was manually executed.
   - No execution timestamps, raw server logs, or screenshot files have been fabricated or invented in this report.

2. **Static Migration Verification (Independently Verified by AI Assistant):**
   - Independently verified by reading the eight SQL migration files in `supabase/migrations/` and cross-checking every table definition, `CHECK` constraint, composite foreign key, trigger, `SECURITY DEFINER` / `SECURITY INVOKER` function, `GRANT`/`REVOKE` statement, and the read-only catalog self-check block against [SkillSwap_PRD_v1.0.md](../SkillSwap_PRD_v1.0.md) (Sections 4, 5, 7, and 8).
   - **Not Independently Executed by AI:** The AI assistant did not connect to the live Supabase instance, did not execute live SQL queries, and did not independently run HTTP/REST requests against PostgREST or FastAPI.

3. **Scenarios Not Individually Demonstrated in SQL Editor (Statically Enforced Only):**
   - Specific sub-cases or alternate directions that are enforced by SQL constraints, triggers, or PL/pgSQL branches in the migration files, but were not individually run as separate manual test steps in the SQL Editor (for example, the reverse review direction where User B reviews User A, or specific individual constraint permutations). These are explicitly called out in Sections 3 and 4 for automated regression coverage.

---

## 2. Scope of Migrations & Security Model

### 2.1 Eight Migration Files Reviewed

| # | Migration File | Primary Responsibilities |
|---|---|---|
| 1 | `20261028220100_foundation.sql` | Creates the `private` schema (which must be kept out of Supabase's *Exposed schemas* setting), revokes global `PUBLIC` default function execution privileges, and defines `private.set_updated_at()`. |
| 2 | `20261028220200_create_profiles.sql` | Creates `public.profiles`, `private.valid_interests()`, `on_auth_user_created` registration trigger (`private.handle_new_user()`), existing-user backfill, and profile RLS/column grants. |
| 3 | `20261028220300_create_skills.sql` | Creates `public.skills`, partial unique index for active skills per owner, identity-immutability trigger (`private.guard_skill_identity()`), and skill RLS/column grants. |
| 4 | `20261028220400_create_exchange_requests.sql` | Creates `public.exchange_requests`, composite foreign keys proving skill ownership, creation validator (`private.validate_exchange_request_insert()`), update guard (`private.guard_exchange_request_update()`), historical skill protection (`private.protect_referenced_skill()`), and request RLS/column grants. |
| 5 | `20261028220500_create_exchange_sessions.sql` | Creates `public.exchange_sessions` (1:1 with accepted request), bilateral confirmation constraint, update guard (`private.guard_exchange_session_update()`), and session RLS/column grants. |
| 6 | `20261028220600_create_reviews.sql` | Creates `public.reviews`, rating range constraint (`1..5`), unique `(session_id, reviewer_user_id)` constraint, insert eligibility trigger (`private.validate_review_insert()`), and read-only RLS/grants. |
| 7 | `20261028220700_private_workflow_functions.sql` | Defines the five `SECURITY DEFINER` workflow functions in `private`: `accept_exchange_request`, `decline_exchange_request`, `cancel_exchange_request`, `confirm_exchange_session`, and `create_review`. |
| 8 | `20261028220800_public_wrappers_and_permissions.sql` | Exposes thin `SECURITY INVOKER` RPC wrappers in `public`, applies final `REVOKE`/`GRANT` rules, and runs the automated `DO $$ ... $$` catalog permission self-check. |

> **Important Note on Schema Exposure:** Creating a schema with `CREATE SCHEMA private` in PostgreSQL does **not** by itself prevent Supabase's Data API (PostgREST) from exposing it; exclusion depends on the Supabase Dashboard platform setting (*Settings → API → Exposed schemas*). A user-provided Supabase Dashboard screenshot confirmed that only `public` and `graphql_public` are listed under *Exposed schemas*, and `private` is absent. Live HTTP verification of this API boundary remains scheduled for the backend integration phase.

### 2.2 Interaction Between RLS, `SECURITY DEFINER` Functions, and the Supabase Data API

Understanding how Row Level Security (RLS) interacts with PostgreSQL functions and the Supabase Data API is essential for FastAPI development:

1. **Ordinary Table Operations & User-Scoped RLS:**
   - When FastAPI forwards a signed-in member's JSON Web Token (JWT) to Supabase alongside the publishable key (`sb_publishable_...`), ordinary table queries (`SELECT`, `INSERT`, `UPDATE` on `profiles`, `skills`, `exchange_requests`, `exchange_sessions`, and `reviews`) run as the `authenticated` role with `auth.uid()` set to the caller's UUID.
   - For these ordinary table requests, PostgreSQL enforces table-level RLS policies and column-level `GRANT` restrictions directly.
2. **`SECURITY DEFINER` Workflow Functions Bypass Table RLS:**
   - Members have no direct `UPDATE` grant on `exchange_requests`, no direct `INSERT` or confirmation `UPDATE` grant on `exchange_sessions`, and no direct `INSERT` grant on `reviews`.
   - Instead, workflow transitions are performed by the five functions in the `private` schema (`private.accept_exchange_request`, `private.decline_exchange_request`, `private.cancel_exchange_request`, `private.confirm_exchange_session`, and `private.create_review`), which are declared `SECURITY DEFINER`.
   - Because `SECURITY DEFINER` functions execute with the privileges of their owner (the migration role, typically `postgres`), **queries and writes inside those functions bypass table-level RLS**.
   - Consequently, **explicit validation inside every `SECURITY DEFINER` function is essential and is the primary security boundary for workflow transitions**: each function derives caller identity exclusively from `auth.uid()`, locks the target rows (`FOR UPDATE` / `FOR SHARE`), verifies that the caller is an authorised participant (or the specific role such as receiver/requester), and validates the current state and input parameters before modifying any row.
3. **Direct Reachability of `public` RPC Wrappers via the Supabase Data API:**
   - Although the approved SkillSwap architecture routes all business operations through FastAPI (`React -> FastAPI -> Supabase`), the five wrapper functions in `public` (`public.accept_exchange_request`, etc.) are granted `EXECUTE` to `authenticated` in the `public` schema, and `public` is exposed in the Supabase Data API.
   - Therefore, any client holding the public `sb_publishable_...` key and a valid signed-in user JWT can technically call `/rest/v1/rpc/<function_name>` directly against Supabase without going through FastAPI.
   - Because of this, **all critical security, ownership, participant, and business-state invariants must be enforced inside the database functions and constraints themselves**, never in FastAPI alone.

---

## 3. Summary of Manual SQL Editor Test Results

Each test area below distinguishes between **Manually Observed PASS** results (executed in the Supabase SQL Editor), **Static Migration Verification**, and **Scenarios Not Individually Demonstrated**.

### 3.1 RLS and Permissions Verification (`DB-01`)
- **Manually Observed PASS (Supabase CLI Migration Self-Check, SQL Editor Catalog Queries & Dashboard Screenshot):**
  - Migration 8's built-in `DO $$ ... $$` permission self-check ran automatically during **Supabase CLI migration application** and passed without error, verifying: RLS enabled on all five tables; zero table or column privileges for `anon`; exact expected column-level `INSERT`/`UPDATE` privileges for `authenticated`; no `DELETE` policies; `EXECUTE` on the five workflow functions restricted to `authenticated`; trigger/helper functions in `private` not executable by `authenticated` (except `private.valid_interests` required by `CHECK`); fixed `search_path = ''` on all `private` functions; and revocation of the global `PUBLIC` function execution default.
  - Subsequent **SQL Editor catalog inspection queries** independently confirmed RLS flags, table/column grants, and policy definitions across all five tables.
  - User-provided **Supabase Dashboard screenshot** confirmed *Exposed schemas* contains only `public` and `graphql_public` (`private` is absent).
- **Outstanding Live HTTP Tests:**
  - Live HTTP requests with `anon`/publishable key and real JWT tokens against PostgREST to confirm schema exposure and RLS enforcement over the network.

### 3.2 Profile Creation and Ownership (`DB-02`)
- **Manually Observed PASS (SQL Editor):**
  - Profile creation and ownership checks passed: an authenticated user can update their own profile (`user_id = auth.uid()`), and attempts by another user to update that profile row are blocked by `profiles_update_own`.
- **Static Migration Verification / Scenarios Not Individually Demonstrated:**
  - `private.handle_new_user()` sanitises `raw_user_meta_data ->> 'display_name'` and falls back to `'New member'` when missing or outside 2–60 characters; boundary tests for invalid `interests` array lengths (>10 items or item >40 chars) and bio/preferences length constraints were verified statically in `20261028220200_create_profiles.sql` but not individually run in the manual SQL Editor session.

### 3.3 Skills Insertion and Ownership (`DB-03`)
- **Manually Observed PASS (SQL Editor):**
  - Authenticated members inserted valid skills for their own `owner_user_id`.
  - Attempting to insert a skill for another user's `owner_user_id` or update another user's skill was blocked by RLS (`skills_insert_own`, `skills_update_own`).
- **Static Migration Verification / Scenarios Not Individually Demonstrated:**
  - Trigger `private.guard_skill_identity()` (preventing changes to `id`, `owner_user_id`, `skill_type`), partial unique index `skills_unique_active_per_owner` (preventing duplicate active skill names per owner/type while allowing replacement after deactivation), and trigger `private.protect_referenced_skill()` (blocking edits to name/category/level/description once referenced by a request while permitting `is_active = false`) were verified statically in migrations 3 and 4, and were not individually demonstrated in the manual SQL Editor run.

### 3.4 Exchange Request Creation and Requester Protection (`DB-04`)
- **Manually Observed PASS (SQL Editor):**
  - Valid `pending` exchange request creation succeeded when User A (`requester_user_id = auth.uid()`) requested User B's active offered skill while offering User A's active offered skill with a future `proposed_datetime`.
  - Requester impersonation (`requester_user_id <> auth.uid()`) was blocked by `exchange_requests_insert_as_requester`.
- **Static Migration Verification / Scenarios Not Individually Demonstrated:**
  - Additional negative creation checks enforced by `private.validate_exchange_request_insert()` and table `CHECK`/FK constraints—such as self-requests (`requester_user_id = receiver_user_id`), past `proposed_datetime`, inactive skills (`is_active = false`), or using a `'wanted'` skill ID instead of an `'offered'` skill ID—were verified by static inspection of `20261028220400_create_exchange_requests.sql` and were not all individually executed in the manual SQL Editor session.

### 3.5 Request Acceptance, Repeated Acceptance, Decline, and Cancellation (`DB-05`, `DB-06`)
- **Manually Observed PASS (SQL Editor):**
  - **Acceptance:** Receiver calling `public.accept_exchange_request(request_id)` transitioned the `pending` request to `accepted` and atomically created one `scheduled` session row in `public.exchange_sessions`.
  - **Unauthorised Acceptance Rejected (`42501`):** Requester attempting to call `public.accept_exchange_request(request_id)` was rejected with `not_permitted: only the receiver can accept a request` (SQLSTATE `42501`).
  - **Repeated Acceptance Rejected (`P0001`):** Calling `public.accept_exchange_request(request_id)` again on an already-accepted request was rejected (`invalid_state: only a pending request can be accepted`, SQLSTATE `P0001`).
  - **Decline & Unauthorised Decline Rejected (`42501`):** Receiver calling `public.decline_exchange_request(request_id)` on a `pending` request transitioned it to `declined`, while a requester attempting to decline was rejected with `not_permitted: only the receiver can decline a request` (SQLSTATE `42501`).
  - **Cancellation & Unauthorised Pending Cancellation Rejected (`42501`):** Authorised calls to `public.cancel_exchange_request(request_id)` transitioned the request to `cancelled` (and cancelled any linked `scheduled` session), while a receiver attempting to cancel a `pending` request was rejected with `not_permitted: only the requester can cancel a pending request (the receiver can decline)` (SQLSTATE `42501`).
- **Static Verification / Outstanding Tests:**
  - Non-participant (`P0002`) calls on request RPCs, acceptance rejection when a referenced skill was deactivated after request creation (`skill_inactive`) or when `proposed_datetime` has passed (`proposed_time_passed`), and transitions out of terminal states (`declined`, `cancelled`, `completed`) are verified statically in `20261028220700_private_workflow_functions.sql` and queued for automated regression tests.

### 3.6 Session Creation, Two-Participant Confirmation, Repeated Confirmation, and Unauthorised Confirmation (`DB-07`, `DB-08`, `DB-09`)
- **Manually Observed PASS (SQL Editor):**
  - **Session Creation & First Confirmation:** Accepting a request created one `scheduled` session. When the first participant called `public.confirm_exchange_session(session_id)`, only their confirmation timestamp was recorded (`requester_confirmed_at` or `receiver_confirmed_at`), while `exchange_sessions.completion_status` remained `'scheduled'` and `exchange_requests.status` remained `'accepted'`.
  - **Repeated Confirmation Before & After Completion (Idempotency):** Repeating `public.confirm_exchange_session(session_id)` as the first participant while `'scheduled'`, and repeating `public.confirm_exchange_session(session_id)` by both participants after the session was `'completed'`, returned the session row without error, left both confirmation timestamps (`requester_confirmed_at`, `receiver_confirmed_at`) and `updated_at` unchanged, and kept both the session and parent request in `'completed'` status.
  - **Second Participant Confirmation (Bilateral Completion):** When the second participant called `public.confirm_exchange_session(session_id)`, the second confirmation timestamp and `completed_at` were set, `exchange_sessions.completion_status` became `'completed'`, and `exchange_requests.status` became `'completed'`.
  - **Unauthorised Confirmation:** Calling `public.confirm_exchange_session(session_id)` as a non-participant was rejected with `session_not_found` (`P0002`).
- **Static Verification / Outstanding Tests:**
  - Attempting to confirm a `'cancelled'` session (`invalid_state`, `P0001`) and direct `UPDATE` attempts on `exchange_sessions.notes` on active vs. cancelled sessions (`exchange_sessions_update_notes_participants`) were verified statically in migrations 5 and 7.

### 3.7 Review Workflow Tests (`3.3M-7A` to `3.3M-7E` — `DB-10` to `DB-14`)
All five planned manual review workflow tests (`3.3M-7A` through `3.3M-7E`) were executed in the Supabase SQL Editor and observed as **PASS**:

- **`3.3M-7A` — Review Creation After Completion (User A Reviewing User B):**
  - **Manually Observed Result:** **PASS**. After bilateral session confirmation (`completion_status = 'completed'`), User A (`requester`) called `public.create_review(session_id, rating, comment)` and successfully created a review row where `reviewer_user_id = User A` and `reviewee_user_id = User B` (derived automatically by `private.create_review`).
  - **Untested Reverse Direction (Not Individually Demonstrated):** The reverse review direction—**User B (`receiver`) submitting a review for User A (`requester`) on the same completed session**—was **not** individually executed in the manual SQL Editor run. Static inspection of `private.create_review()` (lines 341–353 of `20261028220700_private_workflow_functions.sql`) and `UNIQUE (session_id, reviewer_user_id)` confirms the schema supports both participants reviewing each other once per session, and this reverse direction is queued for automated regression testing.
- **`3.3M-7B` — Review Rejection Before Completion:**
  - **Manually Observed Result:** **PASS**. Calling `public.create_review` before both participants confirmed completion (while the session was still `'scheduled'`) was rejected with `session_not_completed: reviews are only allowed after both participants confirm` (`P0001`).
- **`3.3M-7C` — Duplicate Review Prevention:**
  - **Manually Observed Result:** **PASS**. Calling `public.create_review` a second time as the same reviewer (User A) for the same completed session was rejected with `review_already_exists: you have already reviewed this session` (`23505`).
- **`3.3M-7D` — Invalid Ratings (`0`, `6`, and `NULL`) Rejected:**
  - **Manually Observed Result:** **PASS**. Calling `public.create_review` with `p_rating = 0`, `p_rating = 6`, and `p_rating = NULL` was rejected in all three cases with `invalid_rating: rating must be between 1 and 5` (`22023`).
- **`3.3M-7E` — Non-Participant Review Prevention:**
  - **Manually Observed Result:** **PASS**. Calling `public.create_review` as an authenticated third user (not the requester or receiver of the session) was rejected with `session_not_found` (`P0002`).

---

## 4. Test Coverage Matrix (`DB-01` to `DB-14`)

The matrix below preserves the 14 database test groups (`DB-01` to `DB-14`) and distinguishes between scenarios manually observed as **PASS** in the SQL Editor / CLI / Dashboard, **Static SQL** verification of database rules, and **Outstanding Tests** (including pending live HTTP tests).

| Test ID | Workflow / Integrity Group | PRD Ref | Manually Observed PASS (CLI / SQL Editor / Screenshot) | Static Verification / Outstanding Tests | Coverage Status |
|---|---|---|---|---|---|
| **DB-01** | RLS, least-privilege grants, and schema exposure | FR-15, §7, §8 | Migration 8 `DO` self-check passed during Supabase CLI migration push; subsequent SQL Editor catalog queries verified RLS/grants/policies; Dashboard screenshot verified `public` & `graphql_public` exposed and `private` absent | **Outstanding HTTP Test:** Live PostgREST HTTP boundary checks with real JWTs and `sb_publishable_...` key | **PASS (CLI, SQL Catalog & Dashboard); Live HTTP Pending** |
| **DB-02** | Profile creation and owner-only updates | FR-01, FR-02, §7 | Owner profile update succeeded; cross-user profile update blocked by `profiles_update_own` | **Static SQL:** `handle_new_user()` metadata fallback edge cases (`'New member'`) and `valid_interests()` array bounds (>10 tags / >40 chars) | **PASS (Core Observed; Bounds Static SQL)** |
| **DB-03** | Skills insertion, ownership, and historical protection | FR-03, FR-15, §7 | Self skill insert succeeded; cross-user skill insert and cross-user skill update blocked by RLS | **Static SQL:** `guard_skill_identity()`, `skills_unique_active_per_owner` duplicate check, and `protect_referenced_skill()` (`skill_in_use` on referenced skill edit) | **PASS (Ownership Observed; Triggers Static SQL)** |
| **DB-04** | Exchange request creation and requester protection | FR-06, FR-15, §4.2, §7 | Valid `pending` request creation succeeded; impersonating another `requester_user_id` blocked by RLS | **Static SQL:** Individual negative insert triggers/constraints: self-request, past `proposed_datetime`, inactive skill, or `'wanted'` skill used as offered/wanted | **PASS (Core & Impersonation Observed; Negative Permutations Static SQL)** |
| **DB-05** | Request acceptance and repeated acceptance prevention | FR-07, §4.2, §4.3 | Receiver `accept_exchange_request` succeeded (status -> `accepted`, session created); unauthorised requester acceptance rejected (`42501`); repeated acceptance on same request rejected (`P0001`) | **Static SQL / Outstanding:** Non-participant attempting `accept` (`P0002`); acceptance when a skill was deactivated after request creation (`skill_inactive`) or past proposed time (`proposed_time_passed`) | **PASS (Accept, Unauthorised & Repeat Observed; Edge Guards Static SQL)** |
| **DB-06** | Request decline and cancellation rules | FR-07, §4.2, §4.3 | Receiver `decline_exchange_request` (`pending` -> `declined`), authorised `cancel_exchange_request` (`cancelled` + linked session `cancelled`), and unauthorised decline/cancel attempts rejected (`42501`) | **Static SQL / Outstanding:** Non-participant `decline`/`cancel` (`P0002`), and transitions out of terminal states (`declined`/`cancelled`/`completed` -> `P0001`) | **PASS (Decline, Cancel & Unauthorised Role Observed; Terminal/Non-Participant Static SQL)** |
| **DB-07** | Session creation and two-participant confirmation | FR-08, §4.2, §4.3 | 1:1 `scheduled` session created on accept; 1st confirmation kept request `accepted` & session `scheduled`; 2nd confirmation set both to `completed` | **Static SQL:** Constraint `exchange_sessions_completion_requires_both` against direct superuser/malformed writes; `notes` edit policies | **PASS (Manually Observed)** |
| **DB-08** | Repeated session confirmation idempotency | FR-08, §4.3 | Repeating `confirm_exchange_session` both while `scheduled` and by both users after `completed` returned the row without error, left confirmation and `updated_at` timestamps unchanged, and kept both session and request `completed` | **Static SQL / Outstanding:** Confirmation attempt on a `cancelled` session rejected (`invalid_state`, `P0001`) | **PASS (Scheduled & Post-Complete Observed; Cancelled Session Static SQL)** |
| **DB-09** | Unauthorised session confirmation prevention | FR-08, FR-15, §8 | Non-participant calling `confirm_exchange_session` rejected with `session_not_found` (`P0002`) | **Static SQL:** Unauthenticated (`auth.uid() IS NULL`) call rejected with `not_authenticated` (`42501`) | **PASS (Manually Observed)** |
| **DB-10** | Review rejection before session completion (`3.3M-7B`) | FR-09, §4.2, §4.3 | **Test `3.3M-7B` PASS:** Calling `create_review` before bilateral completion rejected with `session_not_completed` (`P0001`) | **Static SQL:** Calling `create_review` on a `'cancelled'` session rejected with `session_not_completed` (`P0001`) | **PASS (Manually Observed)** |
| **DB-11** | Review creation after completion (`3.3M-7A`) | FR-09, §4.2, §7 | **Test `3.3M-7A` PASS:** User A (`requester`) successfully created review for User B (`receiver`) after completion | **Static SQL / Outstanding:** Reverse direction (User B `receiver` reviewing User A `requester` on the same session); comment >500 chars (`22023`) | **PASS (User A -> B Observed; User B -> A Static SQL Only)** |
| **DB-12** | Duplicate review prevention (`3.3M-7C`) | FR-09, §7 | **Test `3.3M-7C` PASS:** Second review by User A on the same session rejected with `review_already_exists` (`23505`) | **Static SQL:** Direct table insert backstop `UNIQUE (session_id, reviewer_user_id)` | **PASS (Manually Observed)** |
| **DB-13** | Invalid review ratings (`0`, `6`, `NULL`) rejected (`3.3M-7D`) | FR-09, §7 | **Test `3.3M-7D` PASS:** Ratings `0`, `6`, and `NULL` each rejected with `invalid_rating` (`22023`) | **Static SQL:** Table-level `CHECK (rating BETWEEN 1 AND 5)` and `NOT NULL` backstops | **PASS (Manually Observed)** |
| **DB-14** | Non-participant review prevention (`3.3M-7E`) | FR-09, FR-15, §8 | **Test `3.3M-7E` PASS:** Non-participant calling `create_review` rejected with `session_not_found` (`P0002`) | **Static SQL:** Trigger `private.validate_review_insert()` backstop (`42501`) and self-review check `reviewer_user_id <> reviewee_user_id` | **PASS (Manually Observed)** |

---

## 5. Testing Limitations

While the SQL Editor workflow tests and static inspection provide strong confidence in the PostgreSQL schema, constraints, triggers, and PL/pgSQL functions, the following limitations apply to the testing completed so far:

1. **Simulated JWT Identities via SQL Editor:**
   - Caller identities were simulated inside the Supabase SQL Editor using session configuration settings (`set_config('request.jwt.claims', ...)` / `set_config('request.jwt.claim.sub', ...)` and `SET LOCAL ROLE authenticated`) rather than real signed JWTs issued by Supabase Auth (`GoTrue`).
2. **Transactional `ROLLBACK` Execution:**
   - Manual tests were executed inside explicit transactions ending with `ROLLBACK` to keep the development database clean. While `ROLLBACK` accurately tests immediate constraints, triggers, RLS policies, and PL/pgSQL logic, it does not verify post-commit persistence across separate sessions.
3. **No End-to-End Real JWT / PostgREST / FastAPI Verification Yet:**
   - Although the Supabase Dashboard screenshot confirmed that only `public` and `graphql_public` are exposed (`private` is absent), live HTTP verification across `React -> FastAPI (with user Bearer token) -> Supabase PostgREST / RPC` has not yet been executed.
4. **Incomplete Concurrency Testing:**
   - Although the workflow functions use explicit row locking (`FOR UPDATE` on requests/sessions and ordered `FOR SHARE` / `FOR NO KEY UPDATE` locks on skills), the single-session SQL Editor runs statements sequentially. Multi-connection race conditions (e.g., simultaneous `accept` + `cancel` or simultaneous confirmations) were not stress-tested across parallel connections.
5. **Possible Early Session Completion Before Scheduled Time:**
   - In `private.confirm_exchange_session(p_session_id uuid)`, the database checks that the request is `'accepted'` and the session is `'scheduled'`, but does **not** enforce `now() >= v_session.scheduled_datetime`. This allowed the manual tests to confirm and complete a session immediately after acceptance, before its future `scheduled_datetime`.
6. **Subset of Branches Individually Executed:**
   - As detailed in Section 4, core positive and negative paths (including `3.3M-7A` to `3.3M-7E`) were manually executed, while several secondary permutations (such as User B reviewing User A in the reverse direction, or editing a skill after it is referenced in a request) rely on static SQL verification until automated regression tests are run.

---

## 6. Remaining Risks & Open Decisions

### 6.1 Unresolved Product & Technical Decision: Early Session Confirmation Policy
- **Current Behaviour:** `private.confirm_exchange_session(p_session_id uuid)` allows participants to confirm and complete an `'accepted'` / `'scheduled'` session even when `now() < scheduled_datetime`.
- **Why FastAPI-Only Enforcement Would Be Insufficient:**
  - As documented in Section 2.2, `public.confirm_exchange_session(uuid)` is granted `EXECUTE` to `authenticated` in the `public` schema, which is exposed via the Supabase Data API.
  - If early session confirmation were blocked only in FastAPI, any authenticated user could bypass FastAPI and call `/rest/v1/rpc/confirm_exchange_session` directly against Supabase using the public `sb_publishable_...` key and their own JWT.
- **Decision Required & Recommended Path:**
  1. **Option A (Allow Early Confirmation):** Keep the current behaviour if members are permitted to hold and confirm their session earlier than the originally proposed timestamp without cancelling and re-creating the request.
  2. **Option B (Prohibit Early Confirmation):** If sessions must not be confirmed before `scheduled_datetime`, **enforce `now() >= v_session.scheduled_datetime` inside `private.confirm_exchange_session()` via a new forward migration** (`supabase/migrations/2026...`), optionally mirrored by a pre-check in FastAPI for clear user messaging. *(Not implemented yet — awaiting product owner decision.)*

### 6.2 Historical Skill Protection UX Mapping
- Once a skill is referenced by any exchange request, `private.protect_referenced_skill()` raises SQLSTATE `P0001` (`skill_in_use`) if the owner attempts to edit `skill_name`, `category`, `proficiency_level`, or `description`. FastAPI must catch this error and return a clear `409 Conflict` / `400 Bad Request` response guiding the member to deactivate the skill (`is_active = false`) and create a new listing.

### 6.3 Database Error Code Mapping in FastAPI
- The workflow functions and triggers raise specific PostgreSQL SQLSTATE codes (`42501` insufficient privilege, `P0002` resource not found / hidden from non-participant, `P0001` business state/rule violation, `22023` invalid parameter value, `23505` unique constraint violation). FastAPI's repository/service layers must translate these codes into appropriate HTTP status codes (`401`, `403`, `404`, `409`, `422`) rather than surfacing generic `500` errors.

---

## 7. Two-Layer Automated Regression Testing Plan

To close the gap between manual SQL Editor testing, static SQL verification, and end-to-end API behaviour, automated regression testing is structured into two complementary layers. *(The initial GitHub Actions workflow and 17-assertion pgTAP smoke test have been created but have not yet been executed. The remaining automated regression test suites are planned for subsequent implementation.)*

### Layer 1: Database-Level `pgTAP` Tests (`supabase/tests/`)
Executed directly against PostgreSQL using the Supabase CLI (`supabase test db`), running inside rolled-back test transactions to verify every database rule and branch—including scenarios not individually demonstrated in the manual SQL Editor run:

1. **`supabase/tests/01_rls_and_permissions.test.sql`:**
   - Assert table/column privileges for `anon` and `authenticated`, RLS policy enforcement on all 5 tables, and non-executability of `private` trigger helpers.
2. **`supabase/tests/02_profiles_and_skills.test.sql`:**
   - Assert `on_auth_user_created` profile creation with valid and fallback `'New member'` display names, `valid_interests()` boundary checks, `skills_unique_active_per_owner` index (including replacement after deactivation), `guard_skill_identity()`, and `protect_referenced_skill()` (`skill_in_use` when editing a referenced skill vs. allowing deactivation).
3. **`supabase/tests/03_requests_and_sessions.test.sql`:**
   - Assert all negative request creation checks (self-request, past date, wrong owner, `'wanted'` skill type, inactive skill).
   - Assert all role and state permutations for `accept_exchange_request`, `decline_exchange_request`, `cancel_exchange_request` (both `pending` and `accepted`), and `confirm_exchange_session` (1st confirmation, idempotent repeat confirmation, 2nd confirmation completing both rows, and non-participant/cancelled-session rejection).
4. **`supabase/tests/04_reviews.test.sql`:**
   - Assert all five review workflow cases (`3.3M-7A` to `3.3M-7E`) **plus** the reverse review direction (**User B reviewing User A on the same completed session** so that 2 valid reviews exist for the session) and comment-length boundary checks (>500 chars).

### Layer 2: Backend API `pytest` Tests (`backend/tests/`)
Executed against the FastAPI application using `pytest`, verifying real JWT authentication, user-scoped Supabase client forwarding, service/repository layering, and HTTP error translation:

1. **`backend/tests/test_auth_and_rls_api.py`:**
   - Verify missing/invalid JWTs return `401 Unauthorized`; verify user-scoped JWT forwarding preserves RLS across `/profile/me`, `/skills`, `/exchange-requests`, and `/exchange-sessions`; confirm `private` schema endpoints are unreachable over HTTP.
2. **`backend/tests/test_profiles_and_skills_api.py`:**
   - Verify `GET/PATCH /profile/me` and supported `GET`, `POST`, and `PATCH` skill operations; verify skill soft-deactivation using `is_active = false` via `PATCH`; verify that an unsupported `DELETE` endpoint is not exposed and that members cannot directly delete skills through the database; and verify appropriate `409 Conflict` / `400 Bad Request` handling when attempting to edit a skill already referenced by an exchange request (`skill_in_use`).
3. **`backend/tests/test_exchange_workflow_api.py`:**
   - Verify end-to-end HTTP lifecycle (`POST /exchange-requests`, `/accept`, `/decline`, `/cancel`, `/exchange-sessions/{id}/confirm`, `/exchange-sessions/{id}/reviews` for both participants) and verify SQLSTATE-to-HTTP mapping (`P0002` -> `404`, `42501` -> `403`, `P0001` -> `400`/`409`, `23505` -> `409`, `22023` -> `422`).
4. **`backend/tests/test_dashboard_summary_api.py`:**
   - Verify `GET /dashboard/summary` computes accurate offered/wanted skill counts, request counts, completed session counts, and average review ratings across both review directions.

---

## 8. Readiness Criteria for FastAPI Development

Before and during the transition into Phase 3 FastAPI backend implementation, the following readiness criteria apply:

- [x] **Schema & Migrations Authored:** All eight SQL migrations (`20261028220100` to `20261028220800`) are complete and version-controlled in `supabase/migrations/`.
- [x] **Permission Self-Check & Catalog Queries Passed:** The built-in permission self-check in `20261028220800_public_wrappers_and_permissions.sql` ran without error during Supabase CLI migration application, and subsequent SQL Editor catalog queries verified RLS, grants, and policies.
- [x] **Supabase Dashboard Schema Exposure Checked (Screenshot):** User-provided Supabase Dashboard screenshot confirmed *Exposed schemas* lists only `public` and `graphql_public`, with `private` absent.
- [x] **Core Workflow Logic Verified in SQL Editor:** Core paths for RLS, profile ownership, skill ownership, request lifecycle (`accept`, repeated `accept`, `decline`, `cancel`), bilateral/idempotent session confirmation, and review checks (`3.3M-7A` to `3.3M-7E`) have been manually verified as passing in the Supabase SQL Editor.
- [ ] **Early Session Confirmation Decision Finalised:** Decide whether confirming a session before `scheduled_datetime` is allowed or should be blocked in `private.confirm_exchange_session()` via a new migration (Section 6.1).
- [ ] **Backend Environment Configuration Approved:** Prepare `backend/.env` (git-ignored, with explicit user approval) using `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` (`sb_publishable_...`), forwarding the caller's Bearer JWT on every user request.
- [ ] **Live HTTP / JWT Verification & Layered FastAPI Structure:** Implement `routes -> services -> repositories` in `backend/` with centralized PostgreSQL SQLSTATE error translation, and verify live HTTP requests with real Supabase Auth JWTs.
