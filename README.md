# SkillSwap

**AI-powered peer-to-peer skill exchange platform.**

SkillSwap lets people teach skills they know and learn skills they want. Members discover compatible users, send exchange requests, schedule sessions, confirm completion and review each other. An AI Skill Match Assistant improves discovery using real member and skill data.

The approved requirements are in [SkillSwap_PRD_v1.0.md](SkillSwap_PRD_v1.0.md).

## Development status

| Phase | Status |
|---|---|
| Phase 1 — PRD | Completed |
| Phase 2 — Environment and setup | **In progress** (project structure prepared; frontend not yet scaffolded) |
| Phase 3–8 | Not started |

No application features have been implemented yet.

## Architecture

```text
Browser (React) ──► FastAPI (validates user token, business rules, AI calls) ──► Supabase PostgreSQL
      │                                                                              ▲
      └──────────── Supabase Auth (register / login only) ───────────────────────────┘
```

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript (Vite), Tailwind CSS v4 |
| Backend | Python + FastAPI |
| Database | Supabase PostgreSQL with Row Level Security |
| Authentication | Supabase Auth |
| AI | LLM API, called only from FastAPI |
| Versioning | Git + GitHub |
| Deployment | Vercel (frontend) + a suitable FastAPI host |

## Repository layout

```text
SkillSwap/
├── README.md
├── SkillSwap_PRD_v1.0.md
├── backend/      # FastAPI application (to be built)
├── frontend/     # React + Vite app (to be created with the official Vite tool)
├── supabase/     # SQL migrations and fictional seed data
└── docs/         # decisions, frontend structure, other documentation
```

See [docs/decisions.md](docs/decisions.md) for technical decisions and [docs/frontend-structure.md](docs/frontend-structure.md) for the planned frontend layout.

## Configuration and secrets

- Environment templates (`.env.example`) contain placeholder names only.
- Copy a template to `.env` locally and fill in your own values. Real `.env` files are git-ignored and must never be committed.
- Only the **publishable** Supabase key may be used in the frontend. Server-only keys (LLM key, any elevated Supabase key) never go in React or GitHub.

## Setup

Detailed installation steps will be added as each phase is completed.

