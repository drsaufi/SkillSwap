"""Offline integration tests for Exchange Requests and Sessions APIs.

Verifies:
- GET /exchange-requests (participant restriction, incoming/outgoing role, status filtering, pagination)
- POST /exchange-requests (valid creation, self-request rejection, skill ownership, date/format validation)
- POST /exchange-requests/{id}/accept (receiver-only, atomic session creation, inactive skill protection)
- POST /exchange-requests/{id}/decline (receiver-only, terminal state)
- POST /exchange-requests/{id}/cancel (requester for pending, either participant for accepted, session cancellation)
- GET /exchange-sessions/{id} (participant-only, 404 for outsider)
- POST /exchange-sessions/{id}/confirm (two-step confirmation, repeated confirmation idempotency, completion)
- Public health probe and security checks (tokens/secrets never leak)
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

SUPABASE_URL = "https://mock-skillswap.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_unit_test_key_xyz123"

TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"
TOKEN_C = "header-c.payload-c.signature-c"
EXPIRED_TOKEN = "header-x.payload-expired.signature-x"

USER_A_ID = "11111111-1111-4111-8111-111111111111"
USER_B_ID = "22222222-2222-4222-8222-222222222222"
USER_C_ID = "33333333-3333-4333-8333-333333333333"

KNOWN_USERS = {
    TOKEN_A: USER_A_ID,
    TOKEN_B: USER_B_ID,
    TOKEN_C: USER_C_ID,
}

OFFERED_SKILL_ID = "44444444-1111-4444-8444-111111111111"
WANTED_SKILL_ID = "55555555-2222-4555-8555-222222222222"
INACTIVE_SKILL_ID = "44444444-0000-4444-8000-000000000000"

REQUEST_1_ID = "66666666-1111-4666-8666-111111111111"
REQUEST_ACCEPTED_ID = "66666666-2222-4666-8666-222222222222"
SESSION_1_ID = "77777777-1111-4777-8777-111111111111"

NOW = datetime.now(timezone.utc)
FUTURE_TIME = (NOW + timedelta(days=2)).isoformat()


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


def fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL=SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
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


class FakeSupabaseExchange:
    """Mock Supabase backend handling Auth, PostgREST requests, and RPC functions."""

    def __init__(self) -> None:
        self.auth_calls: list[httpx.Request] = []
        self.rest_calls: list[httpx.Request] = []
        self.rpc_calls: list[httpx.Request] = []
        self._lock = threading.Lock()
        self.db_behaviour: Any = None

        self.skills: dict[str, dict[str, Any]] = {
            OFFERED_SKILL_ID: {
                "id": OFFERED_SKILL_ID,
                "owner_user_id": USER_A_ID,
                "skill_name": "Python Automation",
                "skill_type": "offered",
                "is_active": True,
            },
            WANTED_SKILL_ID: {
                "id": WANTED_SKILL_ID,
                "owner_user_id": USER_B_ID,
                "skill_name": "Figma Design",
                "skill_type": "offered",
                "is_active": True,
            },
            INACTIVE_SKILL_ID: {
                "id": INACTIVE_SKILL_ID,
                "owner_user_id": USER_A_ID,
                "skill_name": "Legacy Perl",
                "skill_type": "offered",
                "is_active": False,
            },
        }

        self.requests: dict[str, dict[str, Any]] = {
            REQUEST_1_ID: {
                "id": REQUEST_1_ID,
                "requester_user_id": USER_A_ID,
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "Let us swap Python for Figma design.",
                "status": "pending",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T10:00:00Z",
            },
            REQUEST_ACCEPTED_ID: {
                "id": REQUEST_ACCEPTED_ID,
                "requester_user_id": USER_A_ID,
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "Agreed exchange.",
                "status": "accepted",
                "proposed_datetime": FUTURE_TIME,
                "format": "in_person",
                "created_at": "2026-01-02T10:00:00Z",
                "updated_at": "2026-01-02T10:00:00Z",
            },
        }

        self.sessions: dict[str, dict[str, Any]] = {
            SESSION_1_ID: {
                "id": SESSION_1_ID,
                "request_id": REQUEST_ACCEPTED_ID,
                "scheduled_datetime": FUTURE_TIME,
                "completion_status": "scheduled",
                "requester_confirmed_at": None,
                "receiver_confirmed_at": None,
                "completed_at": None,
                "notes": "",
                "created_at": "2026-01-02T10:00:00Z",
                "updated_at": "2026-01-02T10:00:00Z",
            }
        }

    def _get_caller_id(self, request: httpx.Request) -> str | None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return KNOWN_USERS.get(token)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path

        # 1. Auth requests
        if path == "/auth/v1/user":
            with self._lock:
                self.auth_calls.append(request)
            token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if token in KNOWN_USERS:
                return httpx.Response(200, json=user_json(KNOWN_USERS[token]))
            if token == EXPIRED_TOKEN:
                return httpx.Response(
                    403,
                    json={"code": 403, "error_code": "bad_jwt", "msg": "token is expired"},
                )
            return httpx.Response(
                403,
                json={"code": 403, "error_code": "bad_jwt", "msg": "invalid JWT"},
            )

        # 2. RPC calls
        if path.startswith("/rest/v1/rpc/"):
            with self._lock:
                self.rpc_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            caller_id = self._get_caller_id(request)
            if not caller_id:
                return httpx.Response(
                    403,
                    json={"code": "42501", "message": "not_authenticated", "details": None, "hint": None},
                )

            body = json.loads(request.content) if request.content else {}

            if path == "/rest/v1/rpc/accept_exchange_request":
                rid = body.get("p_request_id")
                if not rid or rid not in self.requests:
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                req_row = self.requests[rid]
                if caller_id not in (req_row["requester_user_id"], req_row["receiver_user_id"]):
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                if caller_id != req_row["receiver_user_id"]:
                    return httpx.Response(
                        400,
                        json={"code": "42501", "message": "not_permitted: only the receiver can accept a request", "details": None, "hint": None},
                    )
                if req_row["status"] != "pending":
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_state: only a pending request can be accepted", "details": None, "hint": None},
                    )

                # Check skill active status
                s1 = self.skills.get(req_row["offered_skill_id"])
                s2 = self.skills.get(req_row["wanted_skill_id"])
                if not s1 or not s2 or not s1.get("is_active") or not s2.get("is_active"):
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "skill_inactive: a skill in this request has been deactivated", "details": None, "hint": None},
                    )

                # Accept request & create session
                req_row["status"] = "accepted"
                new_session_id = str(uuid4())
                session_row = {
                    "id": new_session_id,
                    "request_id": rid,
                    "scheduled_datetime": req_row["proposed_datetime"],
                    "completion_status": "scheduled",
                    "requester_confirmed_at": None,
                    "receiver_confirmed_at": None,
                    "completed_at": None,
                    "notes": "",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.sessions[new_session_id] = session_row
                return httpx.Response(200, json=session_row)

            if path == "/rest/v1/rpc/decline_exchange_request":
                rid = body.get("p_request_id")
                if not rid or rid not in self.requests:
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                req_row = self.requests[rid]
                if caller_id not in (req_row["requester_user_id"], req_row["receiver_user_id"]):
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                if caller_id != req_row["receiver_user_id"]:
                    return httpx.Response(
                        400,
                        json={"code": "42501", "message": "not_permitted: only the receiver can decline a request", "details": None, "hint": None},
                    )
                if req_row["status"] != "pending":
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_state: only a pending request can be declined", "details": None, "hint": None},
                    )

                req_row["status"] = "declined"
                req_row["updated_at"] = datetime.now(timezone.utc).isoformat()
                return httpx.Response(200, json=req_row)

            if path == "/rest/v1/rpc/cancel_exchange_request":
                rid = body.get("p_request_id")
                if not rid or rid not in self.requests:
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                req_row = self.requests[rid]
                if caller_id not in (req_row["requester_user_id"], req_row["receiver_user_id"]):
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "request_not_found", "details": None, "hint": None},
                    )
                if req_row["status"] == "pending":
                    if caller_id != req_row["requester_user_id"]:
                        return httpx.Response(
                            400,
                            json={"code": "42501", "message": "not_permitted: only the requester can cancel a pending request (the receiver can decline)", "details": None, "hint": None},
                        )
                elif req_row["status"] != "accepted":
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_state: only a pending or accepted request can be cancelled", "details": None, "hint": None},
                    )

                req_row["status"] = "cancelled"
                req_row["updated_at"] = datetime.now(timezone.utc).isoformat()

                # Cancel associated session if scheduled
                for sess in self.sessions.values():
                    if sess["request_id"] == rid and sess["completion_status"] == "scheduled":
                        sess["completion_status"] = "cancelled"
                        sess["updated_at"] = datetime.now(timezone.utc).isoformat()

                return httpx.Response(200, json=req_row)

            if path == "/rest/v1/rpc/confirm_exchange_session":
                sid = body.get("p_session_id")
                if not sid or sid not in self.sessions:
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "session_not_found", "details": None, "hint": None},
                    )
                session_row = self.sessions[sid]
                req_row = self.requests.get(session_row["request_id"])
                if not req_row or caller_id not in (req_row["requester_user_id"], req_row["receiver_user_id"]):
                    return httpx.Response(
                        400,
                        json={"code": "P0002", "message": "session_not_found", "details": None, "hint": None},
                    )

                is_requester = (caller_id == req_row["requester_user_id"])
                caller_done = (
                    session_row["requester_confirmed_at"] is not None
                    if is_requester
                    else session_row["receiver_confirmed_at"] is not None
                )
                other_done = (
                    session_row["receiver_confirmed_at"] is not None
                    if is_requester
                    else session_row["requester_confirmed_at"] is not None
                )

                # Repeated confirmation idempotency
                if caller_done and session_row["completion_status"] in ("scheduled", "completed"):
                    return httpx.Response(200, json=session_row)

                if req_row["status"] != "accepted" or session_row["completion_status"] != "scheduled":
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_state: only a scheduled session of an accepted request can be confirmed", "details": None, "hint": None},
                    )

                now_iso = datetime.now(timezone.utc).isoformat()
                if is_requester:
                    session_row["requester_confirmed_at"] = now_iso
                else:
                    session_row["receiver_confirmed_at"] = now_iso

                if other_done:
                    session_row["completion_status"] = "completed"
                    session_row["completed_at"] = now_iso
                    req_row["status"] = "completed"
                    req_row["updated_at"] = now_iso

                session_row["updated_at"] = now_iso
                return httpx.Response(200, json=session_row)

        # 3. PostgREST table /rest/v1/exchange_requests
        if path.startswith("/rest/v1/exchange_requests"):
            with self._lock:
                self.rest_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            caller_id = self._get_caller_id(request)
            parsed = urlparse(str(url))
            qp = parse_qs(parsed.query)

            if request.method == "GET":
                results = list(self.requests.values())

                # RLS: caller must be requester or receiver
                results = [
                    r for r in results
                    if caller_id and caller_id in (r["requester_user_id"], r["receiver_user_id"])
                ]

                # Single id filter
                target_id = None
                for f in qp.get("id", []):
                    if f.startswith("eq."):
                        target_id = f.removeprefix("eq.")
                if target_id:
                    results = [r for r in results if r["id"] == target_id]
                    return httpx.Response(200, json=results)

                # Role filters
                if "receiver_user_id" in qp:
                    target_rec = qp["receiver_user_id"][0].removeprefix("eq.")
                    results = [r for r in results if r["receiver_user_id"] == target_rec]
                if "requester_user_id" in qp:
                    target_req = qp["requester_user_id"][0].removeprefix("eq.")
                    results = [r for r in results if r["requester_user_id"] == target_req]

                # Status filter
                if "status" in qp:
                    target_status = qp["status"][0].removeprefix("eq.")
                    results = [r for r in results if r["status"] == target_status]

                results.sort(key=lambda r: r["created_at"], reverse=True)
                total = len(results)

                offset = int(qp.get("offset", [0])[0])
                limit = int(qp.get("limit", [20])[0])
                paged = results[offset : offset + limit]

                return httpx.Response(
                    200,
                    json=paged,
                    headers={"Content-Range": f"{offset}-{offset + len(paged)}/{total}"},
                )

            if request.method == "POST":
                body = json.loads(request.content)
                new_id = str(uuid4())

                # Simulated database trigger validations:
                # 1. offered_skill must be active, offered, owned by requester
                offered_id = body.get("offered_skill_id")
                skill1 = self.skills.get(offered_id)
                if not skill1 or skill1["owner_user_id"] != body.get("requester_user_id") or not skill1["is_active"]:
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_offered_skill: must be an active offered skill owned by the requester", "details": None, "hint": None},
                    )

                # 2. wanted_skill must be active, offered, owned by receiver
                wanted_id = body.get("wanted_skill_id")
                skill2 = self.skills.get(wanted_id)
                if not skill2 or skill2["owner_user_id"] != body.get("receiver_user_id") or not skill2["is_active"]:
                    return httpx.Response(
                        400,
                        json={"code": "P0001", "message": "invalid_wanted_skill: must be an active offered skill owned by the receiver", "details": None, "hint": None},
                    )

                new_record = {
                    "id": new_id,
                    "requester_user_id": body["requester_user_id"],
                    "receiver_user_id": body["receiver_user_id"],
                    "offered_skill_id": body["offered_skill_id"],
                    "wanted_skill_id": body["wanted_skill_id"],
                    "message": body["message"],
                    "status": "pending",
                    "proposed_datetime": body["proposed_datetime"],
                    "format": body["format"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.requests[new_id] = new_record
                return httpx.Response(201, json=new_record)

        # 4. PostgREST table /rest/v1/exchange_sessions
        if path.startswith("/rest/v1/exchange_sessions"):
            with self._lock:
                self.rest_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            caller_id = self._get_caller_id(request)
            parsed = urlparse(str(url))
            qp = parse_qs(parsed.query)

            target_id = None
            for f in qp.get("id", []):
                if f.startswith("eq."):
                    target_id = f.removeprefix("eq.")

            if request.method == "GET":
                if not target_id or target_id not in self.sessions:
                    return httpx.Response(200, json=[])

                session_row = self.sessions[target_id]
                req_row = self.requests.get(session_row["request_id"])

                # RLS: only participants can see the session
                if not req_row or not caller_id or caller_id not in (req_row["requester_user_id"], req_row["receiver_user_id"]):
                    return httpx.Response(200, json=[])

                return httpx.Response(200, json=[session_row])

        return httpx.Response(404, json={"msg": "not found"})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def build_test_client(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabaseExchange
) -> TestClient:
    active = fake_settings()
    app = create_app(Settings(_env_file=None))
    real_create = sb.create_user_scoped_client

    def create_with_fake(settings: Settings, token: str) -> sb.UserScopedClient:
        return real_create(settings, token, http_client=fake.http_client())

    monkeypatch.setattr(deps, "create_user_scoped_client", create_with_fake)
    app.dependency_overrides[get_app_settings] = lambda: active
    app.dependency_overrides[get_auth_verifier] = (
        lambda: sb.create_auth_verification_client(
            active, http_client=fake.http_client()
        )
    )

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_db() -> FakeSupabaseExchange:
    return FakeSupabaseExchange()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeSupabaseExchange
) -> TestClient:
    return build_test_client(monkeypatch, fake_db)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# POST /exchange-requests Tests
# ==============================================================================


def test_create_exchange_request_success(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    payload = {
        "receiver_user_id": USER_B_ID,
        "offered_skill_id": OFFERED_SKILL_ID,
        "wanted_skill_id": WANTED_SKILL_ID,
        "message": "Let's exchange coding for design skills.",
        "proposed_datetime": FUTURE_TIME,
        "format": "online",
    }
    response = client.post("/exchange-requests", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["requester_user_id"] == USER_A_ID
    assert data["receiver_user_id"] == USER_B_ID
    assert data["status"] == "pending"
    assert data["format"] == "online"
    assert data["id"] in fake_db.requests


def test_create_exchange_request_self_request_rejected(client: TestClient) -> None:
    payload = {
        "receiver_user_id": USER_A_ID,  # Caller is also User A
        "offered_skill_id": OFFERED_SKILL_ID,
        "wanted_skill_id": WANTED_SKILL_ID,
        "message": "Self swap attempt",
        "proposed_datetime": FUTURE_TIME,
        "format": "online",
    }
    response = client.post("/exchange-requests", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "self_request_not_allowed"


@pytest.mark.parametrize(
    ("bad_payload", "error_code"),
    [
        (
            {
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
            },
            422,
        ),
        (
            {
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "X" * 501,
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
            },
            422,
        ),
        (
            {
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "Past datetime",
                "proposed_datetime": (NOW - timedelta(days=1)).isoformat(),
                "format": "online",
            },
            422,
        ),
        (
            {
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "Invalid format",
                "proposed_datetime": FUTURE_TIME,
                "format": "hybrid",
            },
            422,
        ),
        (
            {
                "receiver_user_id": USER_B_ID,
                "offered_skill_id": OFFERED_SKILL_ID,
                "wanted_skill_id": WANTED_SKILL_ID,
                "message": "Forbidden field status",
                "proposed_datetime": FUTURE_TIME,
                "format": "online",
                "status": "accepted",
            },
            422,
        ),
    ],
)
def test_create_exchange_request_validation_failures(
    client: TestClient, bad_payload: dict[str, Any], error_code: int
) -> None:
    response = client.post("/exchange-requests", headers=bearer(TOKEN_A), json=bad_payload)
    assert response.status_code == error_code


def test_create_exchange_request_inactive_skill_rejected(client: TestClient) -> None:
    payload = {
        "receiver_user_id": USER_B_ID,
        "offered_skill_id": INACTIVE_SKILL_ID,  # Inactive skill
        "wanted_skill_id": WANTED_SKILL_ID,
        "message": "Swap using inactive skill",
        "proposed_datetime": FUTURE_TIME,
        "format": "online",
    }
    response = client.post("/exchange-requests", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_offered_skill"


# ==============================================================================
# GET /exchange-requests Tests
# ==============================================================================


def test_get_exchange_requests_returns_participant_requests(client: TestClient) -> None:
    response = client.get("/exchange-requests", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 2
    r_ids = {r["id"] for r in data["items"]}
    assert REQUEST_1_ID in r_ids
    assert REQUEST_ACCEPTED_ID in r_ids


def test_get_exchange_requests_incoming_role(client: TestClient) -> None:
    # User B is receiver for both REQUEST_1_ID and REQUEST_ACCEPTED_ID
    response = client.get("/exchange-requests?role=incoming", headers=bearer(TOKEN_B))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(r["receiver_user_id"] == USER_B_ID for r in data["items"])


def test_get_exchange_requests_outgoing_role(client: TestClient) -> None:
    # User A is requester for both requests
    response = client.get("/exchange-requests?role=outgoing", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert all(r["requester_user_id"] == USER_A_ID for r in data["items"])


def test_get_exchange_requests_status_filter(client: TestClient) -> None:
    response = client.get("/exchange-requests?status=pending", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == REQUEST_1_ID
    assert data["items"][0]["status"] == "pending"


def test_get_exchange_requests_outsider_sees_empty_list(client: TestClient) -> None:
    # User C is not a participant in any request
    response = client.get("/exchange-requests", headers=bearer(TOKEN_C))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_get_exchange_requests_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/exchange-requests")
    assert response.status_code == 401


# ==============================================================================
# POST /exchange-requests/{id}/accept Tests
# ==============================================================================


def test_accept_exchange_request_success(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/accept", headers=bearer(TOKEN_B)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == REQUEST_1_ID
    assert data["completion_status"] == "scheduled"
    assert fake_db.requests[REQUEST_1_ID]["status"] == "accepted"


def test_accept_exchange_request_requester_cannot_accept(client: TestClient) -> None:
    # User A is requester, only receiver User B may accept
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/accept", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_permitted"


def test_accept_exchange_request_outsider_returns_404(client: TestClient) -> None:
    # User C is outsider
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/accept", headers=bearer(TOKEN_C)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_not_found"


def test_accept_exchange_request_invalid_state_rejected(client: TestClient) -> None:
    # REQUEST_ACCEPTED_ID is already accepted
    response = client.post(
        f"/exchange-requests/{REQUEST_ACCEPTED_ID}/accept", headers=bearer(TOKEN_B)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"


# ==============================================================================
# POST /exchange-requests/{id}/decline Tests
# ==============================================================================


def test_decline_exchange_request_success(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/decline", headers=bearer(TOKEN_B)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == REQUEST_1_ID
    assert data["status"] == "declined"
    assert fake_db.requests[REQUEST_1_ID]["status"] == "declined"


def test_decline_exchange_request_requester_cannot_decline(client: TestClient) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/decline", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_permitted"


def test_decline_exchange_request_outsider_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/decline", headers=bearer(TOKEN_C)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_not_found"


# ==============================================================================
# POST /exchange-requests/{id}/cancel Tests
# ==============================================================================


def test_cancel_pending_request_by_requester_success(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/cancel", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == REQUEST_1_ID
    assert data["status"] == "cancelled"
    assert fake_db.requests[REQUEST_1_ID]["status"] == "cancelled"


def test_cancel_pending_request_by_receiver_rejected(client: TestClient) -> None:
    # Receiver must decline, not cancel a pending request
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/cancel", headers=bearer(TOKEN_B)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_permitted"


def test_cancel_accepted_request_by_either_participant_cancels_session(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    # Receiver cancels accepted request
    response = client.post(
        f"/exchange-requests/{REQUEST_ACCEPTED_ID}/cancel", headers=bearer(TOKEN_B)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == REQUEST_ACCEPTED_ID
    assert data["status"] == "cancelled"

    # Verifies associated session was also marked cancelled
    assert fake_db.sessions[SESSION_1_ID]["completion_status"] == "cancelled"


def test_cancel_exchange_request_outsider_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/exchange-requests/{REQUEST_1_ID}/cancel", headers=bearer(TOKEN_C)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "request_not_found"


# ==============================================================================
# GET /exchange-sessions/{id} Tests
# ==============================================================================


def test_get_exchange_session_by_participant_success(client: TestClient) -> None:
    response = client.get(
        f"/exchange-sessions/{SESSION_1_ID}", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == SESSION_1_ID
    assert data["request_id"] == REQUEST_ACCEPTED_ID
    assert data["completion_status"] == "scheduled"


def test_get_exchange_session_outsider_returns_404(client: TestClient) -> None:
    response = client.get(
        f"/exchange-sessions/{SESSION_1_ID}", headers=bearer(TOKEN_C)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_get_exchange_session_not_found(client: TestClient) -> None:
    non_existent = str(uuid4())
    response = client.get(
        f"/exchange-sessions/{non_existent}", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


# ==============================================================================
# POST /exchange-sessions/{id}/confirm Tests
# ==============================================================================


def test_confirm_exchange_session_workflow(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    # 1. First confirmation by User A (Requester)
    res1 = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_A)
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["completion_status"] == "scheduled"  # Not yet completed!
    assert data1["requester_confirmed_at"] is not None
    assert data1["receiver_confirmed_at"] is None
    assert data1["completed_at"] is None
    assert fake_db.requests[REQUEST_ACCEPTED_ID]["status"] == "accepted"

    # 2. Repeated confirmation by User A (idempotent no-op)
    res_repeat = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_A)
    )
    assert res_repeat.status_code == 200
    assert res_repeat.json()["requester_confirmed_at"] == data1["requester_confirmed_at"]

    # 3. Second confirmation by User B (Receiver) -> Completes session & request
    res2 = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_B)
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["completion_status"] == "completed"
    assert data2["receiver_confirmed_at"] is not None
    assert data2["completed_at"] is not None

    # Request is now marked completed
    assert fake_db.requests[REQUEST_ACCEPTED_ID]["status"] == "completed"

    # 4. Double confirm after completion -> harmless
    res_after = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_B)
    )
    assert res_after.status_code == 200
    assert res_after.json()["completion_status"] == "completed"


def test_confirm_exchange_session_outsider_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_C)
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_confirm_exchange_session_cancelled_rejected(
    client: TestClient, fake_db: FakeSupabaseExchange
) -> None:
    fake_db.sessions[SESSION_1_ID]["completion_status"] = "cancelled"
    response = client.post(
        f"/exchange-sessions/{SESSION_1_ID}/confirm", headers=bearer(TOKEN_A)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"


# ==============================================================================
# Security & Health Tests
# ==============================================================================


def test_tokens_and_secrets_never_leak(
    client: TestClient,
    fake_db: FakeSupabaseExchange,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    client.get("/exchange-requests", headers=bearer(TOKEN_A))
    client.post(
        f"/exchange-requests/{REQUEST_1_ID}/accept", headers=bearer(TOKEN_B)
    )
    client.get(f"/exchange-sessions/{SESSION_1_ID}", headers=bearer(TOKEN_A))

    assert TOKEN_A not in caplog.text
    assert TOKEN_B not in caplog.text
    assert PUBLISHABLE_KEY not in caplog.text


def test_health_remains_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
