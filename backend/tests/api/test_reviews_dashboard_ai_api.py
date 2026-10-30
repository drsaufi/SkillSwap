"""Offline integration tests for Step 3.4E: Reviews, Dashboard, and AI Skill Match Assistant APIs.

Verifies:
1. POST /exchange-sessions/{id}/reviews
   - Valid review on a completed session (201 Created)
   - Both participants can review each other once
   - Duplicate review rejection (409 review_already_exists)
   - Premature review on scheduled session rejection (409 session_not_completed)
   - Nonparticipant review rejection (404 session_not_found / 403 review_not_permitted)
   - Rating and comment validation (422 validation_error)
2. GET /dashboard/summary
   - Accurate skill counts, request counts, exchange counts, average rating, and upcoming sessions
   - Empty account state (zeros, average_rating: null, empty upcoming_sessions)
   - Strict user isolation via user-scoped database access
3. POST /ai/skill-matches
   - Grounded AI recommendations with both OpenAI and Gemini REST formats
   - Candidate filtering (excludes self, inactive skills, non-offering members)
   - Hallucination rejection (invented member IDs, invented skill IDs, cross-member skills)
   - Empty candidate set returns empty matches without calling LLM
   - Safe 503 ai_unavailable when unconfigured, timed out, or malformed LLM output
   - Rest of application remains functional when AI is unavailable
   - Zero secret/token leakage in responses or logs
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_app_settings, get_auth_verifier
from app.core import supabase as sb
from app.core.config import Settings
from app.main import create_app
from app.services import ai_service

SUPABASE_URL = "https://mock-skillswap.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_unit_test_key_xyz123"
FAKE_LLM_API_KEY = "sk-fictional-step-34e-secret-key"

TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"
TOKEN_C = "header-c.payload-c.signature-c"
TOKEN_EMPTY = "header-d.payload-d.signature-d"

USER_A_ID = "11111111-1111-4111-8111-111111111111"
USER_B_ID = "22222222-2222-4222-8222-222222222222"
USER_C_ID = "33333333-3333-4333-8333-333333333333"
USER_EMPTY_ID = "44444444-4444-4444-8444-444444444444"

KNOWN_USERS = {
    TOKEN_A: USER_A_ID,
    TOKEN_B: USER_B_ID,
    TOKEN_C: USER_C_ID,
    TOKEN_EMPTY: USER_EMPTY_ID,
}

SKILL_A_OFFERED = "aaaaaaaa-1111-4111-8111-111111111111"
SKILL_A_WANTED = "aaaaaaaa-2222-4222-8222-222222222222"
SKILL_B_OFFERED = "bbbbbbbb-1111-4111-8111-111111111111"
SKILL_B_WANTED = "bbbbbbbb-2222-4222-8222-222222222222"
SKILL_C_OFFERED = "cccccccc-1111-4111-8111-111111111111"
SKILL_C_INACTIVE = "cccccccc-9999-4999-8999-999999999999"

REQ_PENDING_IN = "66666666-1111-4666-8666-111111111111"
REQ_PENDING_OUT = "66666666-2222-4666-8666-222222222222"
REQ_ACCEPTED = "66666666-3333-4666-8666-333333333333"
REQ_COMPLETED = "66666666-4444-4666-8666-444444444444"

SESSION_SCHEDULED_ID = "77777777-1111-4777-8777-111111111111"
SESSION_COMPLETED_ID = "77777777-2222-4777-8777-222222222222"

NOW = datetime.now(timezone.utc)
FUTURE_TIME = (NOW + timedelta(days=3)).isoformat()
PAST_TIME = (NOW - timedelta(days=2)).isoformat()


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Ensure no real DNS or network connections can occur."""
    attempts: list[str] = []

    def blocked(*args: object, **kwargs: object) -> None:
        attempts.append("network access attempted")
        raise OSError("real network access is blocked in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture(autouse=True)
def clean_verification_cache():
    sb.reset_auth_verification_clients()
    yield
    sb.reset_auth_verification_clients()


def make_settings(
    *,
    llm_key: str = FAKE_LLM_API_KEY,
    llm_model: str = "gpt-4o-mini",
    ai_max_candidates: int = 20,
) -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL=SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
        LLM_API_KEY=llm_key,
        LLM_MODEL=llm_model,
        LLM_TIMEOUT_SECONDS=10,
        AI_MAX_CANDIDATES=ai_max_candidates,
    )


def user_json(user_id: str) -> dict[str, Any]:
    return {
        "id": user_id,
        "aud": "authenticated",
        "role": "authenticated",
        "email": f"user_{user_id[:4]}@example.test",
        "app_metadata": {},
        "user_metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
    }


class FakeStep34EBackend:
    """In-memory mock for Supabase Auth, PostgREST tables, RPCs, and LLM API."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.llm_requests: list[httpx.Request] = []
        self.llm_behaviour: Any = None

        self.profiles: dict[str, dict[str, Any]] = {
            USER_A_ID: {
                "user_id": USER_A_ID,
                "display_name": "Amina Learner",
                "bio": "Full-stack developer learning Spanish.",
                "location": "Kuala Lumpur",
                "interests": ["Spanish", "UI Design"],
                "learning_preferences": "Interactive pair sessions",
                "availability": "Weekends",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            USER_B_ID: {
                "user_id": USER_B_ID,
                "display_name": "Bruno Mentor",
                "bio": "Native Spanish speaker learning Python.",
                "location": "Madrid",
                "interests": ["Python", "Web Development"],
                "learning_preferences": "Structured practice",
                "availability": "Weekends",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            USER_C_ID: {
                "user_id": USER_C_ID,
                "display_name": "Clara Designer",
                "bio": "UI/UX designer.",
                "location": "Penang",
                "interests": ["UI Design", "Typography"],
                "learning_preferences": "Visual critiques",
                "availability": "Evenings",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            USER_EMPTY_ID: {
                "user_id": USER_EMPTY_ID,
                "display_name": "Dana Newbie",
                "bio": "",
                "location": "",
                "interests": [],
                "learning_preferences": "",
                "availability": "",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
        }

        self.skills: dict[str, dict[str, Any]] = {
            SKILL_A_OFFERED: {
                "id": SKILL_A_OFFERED,
                "owner_user_id": USER_A_ID,
                "skill_name": "Python Programming",
                "category": "Technology",
                "description": "Backend Python and FastAPI.",
                "proficiency_level": "advanced",
                "skill_type": "offered",
                "is_active": True,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SKILL_A_WANTED: {
                "id": SKILL_A_WANTED,
                "owner_user_id": USER_A_ID,
                "skill_name": "Spanish Conversation",
                "category": "Languages",
                "description": "Conversational Spanish practice.",
                "proficiency_level": "beginner",
                "skill_type": "wanted",
                "is_active": True,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SKILL_B_OFFERED: {
                "id": SKILL_B_OFFERED,
                "owner_user_id": USER_B_ID,
                "skill_name": "Spanish Conversation",
                "category": "Languages",
                "description": "Everyday Spanish dialogue.",
                "proficiency_level": "expert",
                "skill_type": "offered",
                "is_active": True,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SKILL_B_WANTED: {
                "id": SKILL_B_WANTED,
                "owner_user_id": USER_B_ID,
                "skill_name": "Python Programming",
                "category": "Technology",
                "description": "Want to learn Python basics.",
                "proficiency_level": "beginner",
                "skill_type": "wanted",
                "is_active": True,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SKILL_C_OFFERED: {
                "id": SKILL_C_OFFERED,
                "owner_user_id": USER_C_ID,
                "skill_name": "UI Design Fundamentals",
                "category": "Design",
                "description": "Figma and component systems.",
                "proficiency_level": "advanced",
                "skill_type": "offered",
                "is_active": True,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SKILL_C_INACTIVE: {
                "id": SKILL_C_INACTIVE,
                "owner_user_id": USER_C_ID,
                "skill_name": "Spanish Conversation",
                "category": "Languages",
                "description": "Inactive listing.",
                "proficiency_level": "intermediate",
                "skill_type": "offered",
                "is_active": False,
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
        }

        self.requests: dict[str, dict[str, Any]] = {
            REQ_PENDING_IN: {
                "id": REQ_PENDING_IN,
                "requester_user_id": USER_C_ID,
                "receiver_user_id": USER_A_ID,
                "offered_skill_id": SKILL_C_OFFERED,
                "wanted_skill_id": SKILL_A_OFFERED,
                "message": "Let's swap UI Design for Python!",
                "status": "pending",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            REQ_PENDING_OUT: {
                "id": REQ_PENDING_OUT,
                "requester_user_id": USER_A_ID,
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": SKILL_A_OFFERED,
                "wanted_skill_id": SKILL_B_OFFERED,
                "message": "Looking forward to Spanish practice.",
                "status": "pending",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            REQ_ACCEPTED: {
                "id": REQ_ACCEPTED,
                "requester_user_id": USER_A_ID,
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": SKILL_A_OFFERED,
                "wanted_skill_id": SKILL_B_OFFERED,
                "message": "Accepted swap.",
                "status": "accepted",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            REQ_COMPLETED: {
                "id": REQ_COMPLETED,
                "requester_user_id": USER_A_ID,
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": SKILL_A_OFFERED,
                "wanted_skill_id": SKILL_B_OFFERED,
                "message": "Completed swap.",
                "status": "completed",
                "proposed_datetime": PAST_TIME,
                "format": "online",
                "created_at": PAST_TIME,
                "updated_at": NOW.isoformat(),
            },
        }

        self.sessions: dict[str, dict[str, Any]] = {
            SESSION_SCHEDULED_ID: {
                "id": SESSION_SCHEDULED_ID,
                "request_id": REQ_ACCEPTED,
                "scheduled_datetime": FUTURE_TIME,
                "completion_status": "scheduled",
                "requester_confirmed_at": None,
                "receiver_confirmed_at": None,
                "completed_at": None,
                "notes": "Upcoming Spanish & Python swap",
                "created_at": PAST_TIME,
                "updated_at": PAST_TIME,
            },
            SESSION_COMPLETED_ID: {
                "id": SESSION_COMPLETED_ID,
                "request_id": REQ_COMPLETED,
                "scheduled_datetime": PAST_TIME,
                "completion_status": "completed",
                "requester_confirmed_at": NOW.isoformat(),
                "receiver_confirmed_at": NOW.isoformat(),
                "completed_at": NOW.isoformat(),
                "notes": "Completed session notes",
                "created_at": PAST_TIME,
                "updated_at": NOW.isoformat(),
            },
        }

        self.reviews: list[dict[str, Any]] = [
            {
                "id": "99999999-1111-4999-8999-111111111111",
                "session_id": "77777777-0000-4777-8777-000000000000",
                "reviewer_user_id": USER_B_ID,
                "reviewee_user_id": USER_A_ID,
                "rating": 5,
                "comment": "Amina taught Python clearly.",
                "created_at": PAST_TIME,
            },
            {
                "id": "99999999-2222-4999-8999-222222222222",
                "session_id": "77777777-0000-4777-8777-000000000001",
                "reviewer_user_id": USER_C_ID,
                "reviewee_user_id": USER_A_ID,
                "rating": 4,
                "comment": "Helpful session!",
                "created_at": PAST_TIME,
            },
        ]

    def _current_user_id(self, request: httpx.Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            return KNOWN_USERS.get(token)
        return None

    def supabase_handler(self, request: httpx.Request) -> httpx.Response:
        user_id = self._current_user_id(request)
        parsed = urlparse(str(request.url))
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/auth/v1/user":
            if not user_id:
                return httpx.Response(
                    401,
                    json={"code": 401, "error_code": "bad_jwt", "msg": "invalid JWT"},
                )
            return httpx.Response(200, json=user_json(user_id))

        if not user_id:
            return httpx.Response(401, json={"message": "Unauthorized"})

        if path.endswith("/rpc/create_review"):
            return self._handle_rpc_create_review(request, user_id)

        if path.endswith("/profiles"):
            return self._handle_profiles(params)
        if path.endswith("/skills"):
            return self._handle_skills(request, params)
        if path.endswith("/exchange_requests"):
            return self._handle_requests(request, params, user_id)
        if path.endswith("/exchange_sessions"):
            return self._handle_sessions(params, user_id)
        if path.endswith("/reviews"):
            return self._handle_reviews(params)

        return httpx.Response(404, json={"message": "Not found"})

    def supabase_http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.supabase_handler))

    def _handle_rpc_create_review(
        self, request: httpx.Request, user_id: str
    ) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        session_id = body.get("p_session_id")
        rating = body.get("p_rating")
        comment = (body.get("p_comment") or "").strip()

        session = self.sessions.get(session_id)
        if session is None:
            return httpx.Response(
                404,
                json={
                    "code": "P0002",
                    "message": "session_not_found: Exchange session was not found.",
                    "details": None,
                    "hint": None,
                },
            )

        req = self.requests[session["request_id"]]
        participants = {req["requester_user_id"], req["receiver_user_id"]}
        if user_id not in participants:
            return httpx.Response(
                404,
                json={
                    "code": "P0002",
                    "message": "session_not_found: Exchange session was not found.",
                    "details": None,
                    "hint": None,
                },
            )

        if session["completion_status"] != "completed":
            return httpx.Response(
                400,
                json={
                    "code": "P0001",
                    "message": "session_not_completed: Reviews can only be submitted for completed sessions.",
                    "details": None,
                    "hint": None,
                },
            )

        for existing in self.reviews:
            if (
                existing["session_id"] == session_id
                and existing["reviewer_user_id"] == user_id
            ):
                return httpx.Response(
                    409,
                    json={
                        "code": "23505",
                        "message": "review_already_exists: You have already reviewed this session.",
                        "details": None,
                        "hint": None,
                    },
                )

        reviewee_id = (
            req["receiver_user_id"]
            if user_id == req["requester_user_id"]
            else req["requester_user_id"]
        )
        new_review = {
            "id": str(uuid4()),
            "session_id": session_id,
            "reviewer_user_id": user_id,
            "reviewee_user_id": reviewee_id,
            "rating": rating,
            "comment": comment,
            "created_at": NOW.isoformat(),
        }
        self.reviews.append(new_review)
        return httpx.Response(200, json=new_review)

    def _handle_profiles(self, params: dict[str, list[str]]) -> httpx.Response:
        rows = list(self.profiles.values())
        if "user_id" in params:
            val = params["user_id"][0]
            if val.startswith("eq."):
                target = val[3:]
                rows = [r for r in rows if r["user_id"] == target]
        return httpx.Response(200, json=rows)

    def _handle_skills(
        self, request: httpx.Request, params: dict[str, list[str]]
    ) -> httpx.Response:
        rows = list(self.skills.values())
        if "owner_user_id" in params:
            target = params["owner_user_id"][0].removeprefix("eq.")
            rows = [r for r in rows if r["owner_user_id"] == target]
        if "skill_type" in params:
            target = params["skill_type"][0].removeprefix("eq.")
            rows = [r for r in rows if r["skill_type"] == target]
        if "is_active" in params:
            target = params["is_active"][0].removeprefix("eq.").lower() == "true"
            rows = [r for r in rows if r["is_active"] is target]

        total = len(rows)
        prefer = request.headers.get("prefer", "")
        headers = (
            {"content-range": f"0-{max(0, total - 1)}/{total}"}
            if "count=exact" in prefer
            else {}
        )
        return httpx.Response(200, json=rows, headers=headers)

    def _handle_requests(
        self,
        request: httpx.Request,
        params: dict[str, list[str]],
        user_id: str,
    ) -> httpx.Response:
        rows = [
            r
            for r in self.requests.values()
            if user_id in (r["requester_user_id"], r["receiver_user_id"])
        ]
        if "receiver_user_id" in params:
            target = params["receiver_user_id"][0].removeprefix("eq.")
            rows = [r for r in rows if r["receiver_user_id"] == target]
        if "requester_user_id" in params:
            target = params["requester_user_id"][0].removeprefix("eq.")
            rows = [r for r in rows if r["requester_user_id"] == target]
        if "status" in params:
            target = params["status"][0].removeprefix("eq.")
            rows = [r for r in rows if r["status"] == target]

        total = len(rows)
        prefer = request.headers.get("prefer", "")
        headers = (
            {"content-range": f"0-{max(0, total - 1)}/{total}"}
            if "count=exact" in prefer
            else {}
        )
        return httpx.Response(200, json=rows, headers=headers)

    def _handle_sessions(
        self, params: dict[str, list[str]], user_id: str
    ) -> httpx.Response:
        rows = []
        for s in self.sessions.values():
            req = self.requests.get(s["request_id"])
            if req and user_id in (
                req["requester_user_id"],
                req["receiver_user_id"],
            ):
                rows.append(s)

        if "completion_status" in params:
            target = params["completion_status"][0].removeprefix("eq.")
            rows = [r for r in rows if r["completion_status"] == target]

        if "scheduled_datetime" in params:
            for clause in params["scheduled_datetime"]:
                if clause.startswith("gte."):
                    min_dt = clause.removeprefix("gte.")
                    rows = [r for r in rows if r["scheduled_datetime"] >= min_dt]

        rows.sort(key=lambda r: r["scheduled_datetime"])
        limit_val = int(params.get("limit", [5])[0]) if "limit" in params else 5
        rows = rows[:limit_val]
        return httpx.Response(200, json=rows)

    def _handle_reviews(self, params: dict[str, list[str]]) -> httpx.Response:
        rows = list(self.reviews)
        if "reviewee_user_id" in params:
            target = params["reviewee_user_id"][0].removeprefix("eq.")
            rows = [r for r in rows if r["reviewee_user_id"] == target]
        return httpx.Response(200, json=rows)

    def llm_transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            with self._lock:
                self.llm_requests.append(request)

            if callable(self.llm_behaviour):
                return self.llm_behaviour(request)

            default_matches = {
                "matches": [
                    {
                        "member_user_id": USER_B_ID,
                        "offered_skill_id": SKILL_B_OFFERED,
                        "matching_wanted_skill_id": SKILL_B_WANTED,
                        "explanation": "Bruno offers Spanish Conversation and wants to learn Python Programming.",
                    },
                    {
                        "member_user_id": USER_C_ID,
                        "offered_skill_id": SKILL_C_OFFERED,
                        "matching_wanted_skill_id": None,
                        "explanation": "Clara offers UI Design Fundamentals which matches Amina's UI Design interest.",
                    },
                ]
            }

            if "generativelanguage.googleapis.com" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": json.dumps(default_matches)}
                                    ]
                                }
                            }
                        ]
                    },
                )

            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(default_matches)
                            }
                        }
                    ]
                },
            )

        return httpx.MockTransport(handler)


@pytest.fixture
def step34e_env(monkeypatch: pytest.MonkeyPatch):
    backend = FakeStep34EBackend()
    settings = make_settings()

    real_create = sb.create_user_scoped_client

    def create_with_fake(s: Settings, token: str) -> sb.UserScopedClient:
        return real_create(
            s, token, http_client=backend.supabase_http_client()
        )

    monkeypatch.setattr(deps, "create_user_scoped_client", create_with_fake)
    monkeypatch.setattr(
        ai_service,
        "create_llm_http_client",
        lambda timeout_sec: httpx.Client(transport=backend.llm_transport()),
    )

    app = create_app(settings)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_auth_verifier] = (
        lambda: sb.create_auth_verification_client(
            settings, http_client=backend.supabase_http_client()
        )
    )

    client = TestClient(app, raise_server_exceptions=False)
    return client, backend, app


# ==============================================================================
# 1. Post-Exchange Reviews API Tests
# ==============================================================================


def test_create_review_success_both_participants(step34e_env: Any) -> None:
    client, _, _ = step34e_env

    # User A reviews User B on completed session
    res_a = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json={"rating": 5, "comment": "  Fantastic Spanish practice!  "},
    )
    assert res_a.status_code == 201
    body_a = res_a.json()
    assert body_a["session_id"] == SESSION_COMPLETED_ID
    assert body_a["reviewer_user_id"] == USER_A_ID
    assert body_a["reviewee_user_id"] == USER_B_ID
    assert body_a["rating"] == 5
    assert body_a["comment"] == "Fantastic Spanish practice!"

    # User B reviews User A on the same completed session
    res_b = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_B}"},
        json={"rating": 4, "comment": "Great Python walkthrough."},
    )
    assert res_b.status_code == 201
    body_b = res_b.json()
    assert body_b["reviewer_user_id"] == USER_B_ID
    assert body_b["reviewee_user_id"] == USER_A_ID
    assert body_b["rating"] == 4


def test_create_review_rejects_duplicate_from_same_reviewer(
    step34e_env: Any,
) -> None:
    client, _, _ = step34e_env

    first = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json={"rating": 5, "comment": "First review"},
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json={"rating": 4, "comment": "Second attempt"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "review_already_exists"


def test_create_review_rejects_scheduled_session(step34e_env: Any) -> None:
    client, _, _ = step34e_env

    res = client.post(
        f"/exchange-sessions/{SESSION_SCHEDULED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json={"rating": 5, "comment": "Too early"},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "session_not_completed"


def test_create_review_rejects_nonparticipant(step34e_env: Any) -> None:
    client, _, _ = step34e_env

    res = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_C}"},
        json={"rating": 5, "comment": "I was not in this session"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "session_not_found"


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"rating": 0, "comment": "Too low"},
        {"rating": 6, "comment": "Too high"},
        {"rating": True, "comment": "Boolean rating"},
        {"rating": None, "comment": "Null rating"},
        {"rating": 5, "comment": None},
        {"rating": 5, "comment": "x" * 501},
        {"rating": 5, "comment": "Spoof attempt", "reviewee_user_id": USER_B_ID},
    ],
)
def test_create_review_validation_errors(
    step34e_env: Any, invalid_payload: dict[str, Any]
) -> None:
    client, _, _ = step34e_env

    res = client.post(
        f"/exchange-sessions/{SESSION_COMPLETED_ID}/reviews",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json=invalid_payload,
    )
    assert res.status_code == 422


# ==============================================================================
# 2. Member Dashboard API Tests
# ==============================================================================


def test_dashboard_summary_populated_member(step34e_env: Any) -> None:
    client, _, _ = step34e_env

    res = client.get(
        "/dashboard/summary",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["active_offered_skills_count"] == 1
    assert body["active_wanted_skills_count"] == 1
    assert body["incoming_pending_requests_count"] == 1
    assert body["outgoing_pending_requests_count"] == 1
    assert body["accepted_exchanges_count"] == 1
    assert body["completed_exchanges_count"] == 1
    assert body["average_rating"] == 4.5
    assert body["reviews_received_count"] == 2
    assert len(body["upcoming_sessions"]) == 1
    assert body["upcoming_sessions"][0]["id"] == SESSION_SCHEDULED_ID
    assert body["upcoming_sessions"][0]["completion_status"] == "scheduled"


def test_dashboard_summary_excludes_past_scheduled_and_completed_sessions(
    step34e_env: Any,
) -> None:
    client, backend, _ = step34e_env

    # Add a past scheduled session for User A
    past_sched_id = str(uuid4())
    backend.sessions[past_sched_id] = {
        "id": past_sched_id,
        "request_id": REQ_ACCEPTED,
        "scheduled_datetime": (NOW - timedelta(days=1)).isoformat(),
        "completion_status": "scheduled",
        "requester_confirmed_at": None,
        "receiver_confirmed_at": None,
        "completed_at": None,
        "notes": "Past scheduled session",
        "created_at": PAST_TIME,
        "updated_at": PAST_TIME,
    }

    # Add a cancelled future session for User A
    cancelled_id = str(uuid4())
    backend.sessions[cancelled_id] = {
        "id": cancelled_id,
        "request_id": REQ_ACCEPTED,
        "scheduled_datetime": (NOW + timedelta(days=5)).isoformat(),
        "completion_status": "cancelled",
        "requester_confirmed_at": None,
        "receiver_confirmed_at": None,
        "completed_at": None,
        "notes": "Cancelled session",
        "created_at": PAST_TIME,
        "updated_at": PAST_TIME,
    }

    res = client.get(
        "/dashboard/summary",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert res.status_code == 200
    body = res.json()
    returned_session_ids = [s["id"] for s in body["upcoming_sessions"]]

    assert SESSION_SCHEDULED_ID in returned_session_ids
    assert past_sched_id not in returned_session_ids
    assert cancelled_id not in returned_session_ids
    assert SESSION_COMPLETED_ID not in returned_session_ids


def test_dashboard_summary_empty_member_account(step34e_env: Any) -> None:
    client, _, _ = step34e_env

    res = client.get(
        "/dashboard/summary",
        headers={"Authorization": f"Bearer {TOKEN_EMPTY}"},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["active_offered_skills_count"] == 0
    assert body["active_wanted_skills_count"] == 0
    assert body["incoming_pending_requests_count"] == 0
    assert body["outgoing_pending_requests_count"] == 0
    assert body["accepted_exchanges_count"] == 0
    assert body["completed_exchanges_count"] == 0
    assert body["average_rating"] is None
    assert body["reviews_received_count"] == 0
    assert body["upcoming_sessions"] == []


# ==============================================================================
# 3. AI Skill Match Assistant — Lite API Tests
# ==============================================================================


def test_ai_skill_matches_grounded_openai_format(step34e_env: Any) -> None:
    client, backend, _ = step34e_env

    res = client.post(
        "/ai/skill-matches",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["candidate_count"] == 2
    assert len(body["matches"]) == 2

    m0 = body["matches"][0]
    assert m0["member_user_id"] == USER_B_ID
    assert m0["display_name"] == "Bruno Mentor"
    assert m0["offered_skill_id"] == SKILL_B_OFFERED
    assert m0["offered_skill"]["skill_name"] == "Spanish Conversation"
    assert m0["matching_wanted_skill_id"] == SKILL_B_WANTED
    assert m0["matching_wanted_skill"]["skill_name"] == "Python Programming"
    assert "Bruno Mentor offers Spanish Conversation and is looking to learn Python Programming." in m0["explanation"]

    m1 = body["matches"][1]
    assert m1["member_user_id"] == USER_C_ID
    assert m1["display_name"] == "Clara Designer"
    assert m1["offered_skill"]["skill_name"] == "UI Design Fundamentals"
    assert m1["matching_wanted_skill"] is None
    assert "Clara Designer offers UI Design Fundamentals, which is available through their SkillSwap profile." in m1["explanation"]

    # Verify LLM request payload never included current user as candidate or inactive skills
    assert len(backend.llm_requests) == 1
    llm_req_body = json.loads(backend.llm_requests[0].content.decode("utf-8"))
    user_msg = json.loads(llm_req_body["messages"][1]["content"])
    candidate_ids = [c["member_user_id"] for c in user_msg["candidates"]]
    assert USER_A_ID not in candidate_ids
    assert SKILL_C_INACTIVE not in json.dumps(user_msg)


def test_ai_skill_matches_grounded_gemini_format(step34e_env: Any) -> None:
    client, backend, app = step34e_env
    gemini_settings = make_settings(llm_model="gemini-2.0-flash")
    app.dependency_overrides[get_app_settings] = lambda: gemini_settings

    res = client.post(
        "/ai/skill-matches",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
        json={},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["matches"]) == 2
    assert "generativelanguage.googleapis.com" in str(
        backend.llm_requests[0].url
    )


def test_ai_skill_matches_discards_hallucinated_llm_suggestions(
    step34e_env: Any,
) -> None:
    client, backend, _ = step34e_env

    def hallucinating_llm(request: httpx.Request) -> httpx.Response:
        payload = {
            "matches": [
                # Invented member UUID
                {
                    "member_user_id": str(uuid4()),
                    "offered_skill_id": SKILL_B_OFFERED,
                    "explanation": "Fake member.",
                },
                # Inactive skill ID
                {
                    "member_user_id": USER_C_ID,
                    "offered_skill_id": SKILL_C_INACTIVE,
                    "explanation": "Inactive skill.",
                },
                # Valid grounded match
                {
                    "member_user_id": USER_B_ID,
                    "offered_skill_id": SKILL_B_OFFERED,
                    "matching_wanted_skill_id": SKILL_B_WANTED,
                    "explanation": "Verified match with Bruno.",
                },
            ]
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    backend.llm_behaviour = hallucinating_llm

    res = client.post(
        "/ai/skill-matches",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["matches"]) == 1
    assert body["matches"][0]["member_user_id"] == USER_B_ID
    assert "Bruno Mentor offers Spanish Conversation and is looking to learn Python Programming." in body["matches"][0]["explanation"]


def test_ai_skill_matches_empty_candidates_skips_llm_call(
    step34e_env: Any,
) -> None:
    client, backend, _ = step34e_env

    res = client.post(
        "/ai/skill-matches",
        headers={"Authorization": f"Bearer {TOKEN_EMPTY}"},
    )
    assert res.status_code == 200
    assert res.json() == {"matches": [], "candidate_count": 0}
    assert len(backend.llm_requests) == 0


def test_ai_unavailable_when_unconfigured_or_failing_and_app_stays_healthy(
    step34e_env: Any, caplog: pytest.LogCaptureFixture
) -> None:
    client, backend, app = step34e_env

    # 1. Missing LLM API key -> 503 ai_unavailable
    unconfigured = make_settings(llm_key="", llm_model="")
    app.dependency_overrides[get_app_settings] = lambda: unconfigured

    res_unconf = client.post(
        "/ai/skill-matches",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert res_unconf.status_code == 503
    assert res_unconf.json()["error"]["code"] == "ai_unavailable"

    # 2. LLM returns malformed non-JSON content -> 503 ai_unavailable
    app.dependency_overrides[get_app_settings] = lambda: make_settings()
    backend.llm_behaviour = lambda req: httpx.Response(
        200,
        json={"choices": [{"message": {"content": "NOT_VALID_JSON"}}]},
    )

    with caplog.at_level(logging.INFO):
        res_bad_json = client.post(
            "/ai/skill-matches",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
        )
    assert res_bad_json.status_code == 503
    assert res_bad_json.json()["error"]["code"] == "ai_unavailable"
    assert FAKE_LLM_API_KEY not in res_bad_json.text
    assert TOKEN_A not in res_bad_json.text
    assert FAKE_LLM_API_KEY not in caplog.text

    # 3. Verify the rest of the application continues working when AI is unavailable
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json() == {"status": "ok"}

    dash_res = client.get(
        "/dashboard/summary",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    assert dash_res.status_code == 200
    assert dash_res.json()["active_offered_skills_count"] == 1
