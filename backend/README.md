# SkillSwap Backend

Python + FastAPI service. **No code yet**; this folder currently holds only the environment template and this plan.

## Responsibilities

REST APIs, input validation, authorisation, request/session status rules, and AI integration (PRD sections 2, 8, 9).

## Planned layout (created as features are built)

```text
backend/
├── .env.example
├── requirements.txt        # Python dependencies
├── pytest.ini
├── app/
│   ├── main.py             # app creation, CORS, router registration
│   ├── core/               # settings (env), JWT verification, error handling
│   ├── api/
│   │   ├── deps.py         # current-user dependency
│   │   └── routes/         # one file per API group
│   ├── schemas/            # Pydantic request/response models
│   ├── services/           # business rules (status transitions, confirmations, reviews)
│   ├── repositories/       # all Supabase queries (user-scoped, RLS preserved)
│   └── ai/                 # candidate selection, LLM client, output validation
└── tests/
    ├── unit/
    └── api/
```

## Local setup

Use a Python virtual environment (`.venv/`, git-ignored). Steps will be documented in Phase 2.

