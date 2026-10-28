# Database Migrations

Version-controlled SQL files that create and change the database: the five tables (`profiles`, `skills`, `exchange_requests`, `exchange_sessions`, `reviews`), constraints, indexes and RLS policies (PRD section 7–8).

## Rules

- One change per file, named `YYYYMMDDHHMMSS_description.sql` (the Supabase CLI format). Files run in timestamp order.
- Never edit a migration after it has been applied; add a new one instead.
- Do not put secrets or real user data in migrations.

## Migration order (Step 3.2 — written, NOT yet applied)

Apply in this exact order. Each file contains its own RLS and GRANT/REVOKE statements.

| # | File | Purpose |
|---|---|---|
| 1 | `20261028220100_foundation.sql` | `private` schema, locked-down function defaults, `set_updated_at()` |
| 2 | `20261028220200_create_profiles.sql` | `profiles`, sign-up trigger, backfill, RLS |
| 3 | `20261028220300_create_skills.sql` | `skills`, checks, indexes, RLS |
| 4 | `20261028220400_create_exchange_requests.sql` | `exchange_requests`, status rules, skill checks, historical skill protection |
| 5 | `20261028220500_create_exchange_sessions.sql` | `exchange_sessions`, two-party confirmation columns, RLS |
| 6 | `20261028220600_create_reviews.sql` | `reviews`, duplicate/eligibility protection, RLS |
| 7 | `20261028220700_private_workflow_functions.sql` | Privileged accept / decline / cancel / confirm / review functions |
| 8 | `20261028220800_public_wrappers_and_permissions.sql` | Public wrappers, final grants, read-only permission self-check |

## Default function permissions (foundation migration)

PostgreSQL lets `PUBLIC` (everyone) execute every new function by default. That is a *global* default, and `ALTER DEFAULT PRIVILEGES IN SCHEMA ...` cannot remove it — it can only add to it. The foundation migration therefore:

- revokes the PUBLIC default **globally** (no `IN SCHEMA`) for functions created from now on by the migration role (`postgres`), in any schema of this database;
- removes Supabase's per-schema default grants to `anon` / `authenticated` in `public` (and, harmlessly, `private`);
- leaves `service_role` untouched (unused by this project).

Implications: it only affects *future* functions by that role (existing functions are unchanged), and any such function — including one created in the dashboard or by a future extension install — needs an explicit `GRANT EXECUTE` before anyone but its owner can call it. Every function in these migrations also has its own explicit `REVOKE` and, where intended, `GRANT`, so their permissions do not depend on the defaults. The self-check verifies the global default was changed. To undo it: `ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC;`.

## What the built-in self-check does (and does not do)

The last migration ends with a read-only check of access rights: RLS enabled on all five tables; no table-level or column-level access for `anon`; members can write only the approved columns (checked column by column with `has_column_privilege()`); no policy for `anon`/`PUBLIC` or allowing DELETE; the five workflow functions executable by members only; trigger and helper functions in `private` not executable by members; every `private` function has a fixed `search_path`; the global PUBLIC function default has been revoked.

Limits:

- **A failed self-check rolls back only that last migration.** Earlier migrations are already committed and are **not** undone. Fix forward with a new migration (or, on a disposable development project and only with explicit approval, reset it).
- It checks *who may do what* when it runs. It does **not** test what RLS conditions allow, how triggers behave, or whether function logic is right. Use the checklist below.
- It does not re-run when later migrations change permissions.
- It cannot see Supabase platform settings (for example which schemas the API exposes).

## Known limitation

Account deletion is not part of the MVP. Deleting a user who has requests, sessions or reviews fails by design (foreign keys use `ON DELETE RESTRICT` on history).

## Verification checklist (complete before relying on the database)

Use a development project and fictional accounts only. Tick each item when done.

**1. Syntax and execution**
- [ ] All eight migrations run in order with no SQL or PL/pgSQL errors, including the final self-check.
- [ ] Re-running the migration list does not reapply anything (history is tracked).
- [ ] The global default is revoked: create a throwaway function as `postgres` and confirm `PUBLIC`, `anon` and `authenticated` cannot execute it (drop it afterwards, with approval).

**2. API exposure**
- [ ] The `private` schema is **not** in Supabase's *Exposed schemas* (Settings → API).
- [ ] Calling a `private` function through the API fails; the five `public` workflow functions work for a signed-in user and fail with no token.
- [ ] Requests with only the publishable key (no user token) cannot read any application table.

**3. RLS and column permissions (two authenticated accounts, A and B)**
- [ ] A can read all profiles and skills, but only their own requests and sessions.
- [ ] A cannot update B's profile or skills, or insert a skill with B's `owner_user_id`.
- [ ] A cannot update protected columns (e.g. `skills.skill_type`, `exchange_requests.status`, session confirmation fields) or delete any row.

**4. Request ownership and status transitions**
- [ ] A request with a skill belonging to the wrong member, a `wanted` skill, an inactive skill, a past date, or a self-request is rejected.
- [ ] Only the receiver can accept or decline; only the requester can cancel a pending request; either can cancel an accepted one.
- [ ] Declined, cancelled and completed requests cannot change again.
- [ ] Accepting fails if either skill has been deactivated.

**5. Repeated confirmation and cancellation**
- [ ] One confirmation does not complete the request; the second does.
- [ ] Confirming again leaves the confirmation timestamp and the session's `updated_at` unchanged.
- [ ] Cancelling an accepted request also cancels its session; a cancelled session cannot be confirmed.

**6. Reviews**
- [ ] A review before completion, by a non-participant, or with a rating outside 1–5 is rejected.
- [ ] A second review by the same person for the same session is rejected.
- [ ] The reviewee is always the other participant; reviews cannot be edited or deleted.

**7. Historical skill protection**
- [ ] After a request references a skill, changing its name, category, level or description is rejected.
- [ ] Deactivating it still works, and a replacement listing can be created.

**8. Migration-history tracking (Supabase CLI)**
- [ ] The CLI's migration list shows all eight local migrations matching the remote history.
- [ ] No migration file was edited after being applied.
