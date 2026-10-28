# Database Migrations

Version-controlled SQL files that create and change the database: the five tables (`profiles`, `skills`, `exchange_requests`, `exchange_sessions`, `reviews`), constraints, indexes and RLS policies (PRD section 7–8).

## Rules

- One change per file, named with an ordered prefix, e.g. `0001_create_profiles.sql`.
- Never edit a migration after it has been applied; add a new one instead.
- Do not put secrets or real user data in migrations.

No migrations exist yet.

