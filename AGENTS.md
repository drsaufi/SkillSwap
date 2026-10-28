# AGENTS.md — SkillSwap AI Development Instructions

These rules apply to every task in this repository. If a rule conflicts with a user request, say so and ask before proceeding.

## 1. Project requirements

- `SkillSwap_PRD_v1.0.md` is the primary source of truth. `docs/decisions.md` records approved technical decisions.
- Stay within the approved scope: nine pages, five tables, the approved API contracts and the AI Skill Match Assistant.
- Do not add features, pages, tables or endpoints that are not in the PRD. The PRD's excluded features (payments, video, messaging, native apps, gamification, custom AI training, admin console) stay out.
- Do not add a dependency unless it is needed for the current task. Name it, say why, and get approval first.
- If the PRD is unclear or seems wrong, ask. Do not decide silently.

## 2. Beginner-friendly development

- The user is a beginner. Before acting, explain in plain language what you will do and why.
- Define technical terms briefly the first time they appear.
- Work in small steps. Prefer several small, reviewable changes over one large one.
- Prefer simple, readable code over clever code. Add short comments where the reason is not obvious.

## 3. Development workflow

1. **Plan:** for any substantial change, state the plan and the files involved, then wait for approval.
2. **Scope:** change only the files the current task needs. Do not touch unrelated files, the PRD or `.gitignore` without permission.
3. **Verify:** after implementing, run the relevant checks (tests, type-check, lint, build).
4. **Report:** state what changed, what was tested and the result, and any remaining issues or assumptions.
5. **Honesty:** never claim something works unless you verified it. If you could not test it, say so.
6. Keep `docs/decisions.md` in step with approved technical decisions, but only edit it when asked or approved.

## 4. Architecture

- **Frontend:** React + TypeScript with Vite, and Tailwind CSS v4 via the `@tailwindcss/vite` plugin. Do not add legacy `tailwind.config.js` or `postcss.config.js` files. The frontend lives in `frontend/`.
- **Backend:** Python + FastAPI in `backend/`.
- **Data and auth:** Supabase PostgreSQL and Supabase Auth. Use the publishable key (`sb_publishable_...`), not the legacy `anon` key.
- **Request path:** React → FastAPI (with the user's token) → Supabase. React may talk directly to Supabase Auth only for registration, login, logout, session restoration and token refreshing. All SkillSwap business data operations (profiles, skills, requests, sessions, reviews, dashboard, AI) go through FastAPI, which uses authenticated user-scoped database access so RLS stays in force. In the frontend, all network calls live in `services/`.
- **AI:** the LLM API is called only from FastAPI, never from React.
- **Backend layering:** routes handle HTTP only; services hold business rules (status transitions, confirmations, reviews); repositories hold all database queries. Do not mix these layers.
- **Files:** migrations go in `supabase/migrations/`, fictional seed data in `supabase/seed/`, tests in `backend/tests/` and `frontend/tests/`, documentation in `docs/`.

## 5. Security

- Never hardcode, print, log or expose credentials, API keys or tokens. Use environment variables only.
- Real local `.env` files may be created during development only after the user's explicit approval. They must always stay out of Git, GitHub, screenshots and logs. Only `.env.example` files containing placeholders may be committed.
- Server-only secrets (LLM key, any elevated Supabase key) never go in React, `VITE_` variables or GitHub. Do not request real keys in chat.
- Use Supabase Row Level Security on all application tables. Also check authorisation in the backend. An elevated key must never replace authorisation checks.
- Validate all input on the frontend and the backend. Verify the user's identity and ownership or participation on every protected endpoint, including when IDs in URLs or payloads are changed.
- Never trust AI output. Validate every AI-suggested member, skill ID and explanation against actual database records, and discard anything inconsistent. Send the model only minimal, allowlisted, non-sensitive data. Never send passwords or email addresses.
- If the AI is unavailable, the rest of the app must keep working.
- Use only fictional data in samples, seeds and tests.

## 6. Approval and safety

- Do not change approved requirements or decisions on your own. Propose the change and wait.
- Ask for explicit approval before any of the following:
  - destructive operations (deleting files or data, force operations, overwriting existing work)
  - database schema changes, migrations, or running any SQL
  - deployment or changes to hosting
  - anything involving credentials or environment settings
  - connecting to or changing Supabase or GitHub
- Do not create Git commits or push to GitHub automatically. Suggest a commit message instead, and only commit when the user asks.
- Do not install packages or run setup commands without saying what they do first.

