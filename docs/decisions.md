# Technical Decisions

A short log of approved technical decisions. Product behaviour is defined in [SkillSwap_PRD_v1.0.md](../SkillSwap_PRD_v1.0.md); this file records implementation choices only.

| # | Decision | Date |
|---|---|---|
| 1 | **Monorepo** containing `frontend/`, `backend/`, `supabase/` and `docs/`. | 2026-10-28 |
| 2 | **React + TypeScript**, built with **Vite**. | 2026-10-28 |
| 3 | **Python + FastAPI** for the backend. | 2026-10-28 |
| 4 | **Supabase PostgreSQL** for data and **Supabase Auth** for identity. | 2026-10-28 |
| 5 | **Tailwind CSS v4** using the official Vite integration, not legacy `tailwind.config.js` / `postcss.config.js` assumptions. Theme colours are defined in CSS. | 2026-10-28 |
| 6 | Use the newer Supabase **publishable key** (`sb_publishable_...`), not the legacy `anon` key. | 2026-10-28 |
| 7 | **No `.github/` directory** for now (revisit if needed). | 2026-10-28 |

## Conventions agreed with the architecture

- Request path: React → FastAPI (with user token) → Supabase. React talks to Supabase directly only for registration and login.
- AI calls originate only from FastAPI; the LLM key lives only in backend environment variables.
- Backend layering: routes → services (business rules) → repositories (database access).
- Database access should preserve RLS (user-scoped). An elevated Supabase key must not replace authorisation checks.
- Migrations live in `supabase/migrations/`; seed data (fictional only) in `supabase/seed/`.
- Environment templates are `.env.example` files with placeholders only.

## Open items (from PRD section 14.2, to decide during implementation)

- Exact SQL column types, text limits, indexes and policies.
- Timezone handling for proposed session times.
- Review visibility rules and session-notes privacy.
- API route naming and error codes.
- LLM provider/model, ranking parameters and AI response schema.

