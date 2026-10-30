"""Offline API integration tests for /profile/me (GET and PATCH).

These tests run against real FastAPI application routing, dependencies,
services, repositories, and the Supabase SDK against an offline MockTransport.
No real network or Supabase connections are made.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_app_settings, get_auth_verifier
from app.core import supabase as sb
from app.core.config import Settings
from app.main import create_app

SUPABASE_URL = "https://example-project.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_test_key_not_real"

USER_A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
USER_NO_PROFILE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"
TOKEN_NO_PROFILE = "header-c.payload-c.signature-c"

KNOWN_USERS = {
    TOKEN_A: USER_A_ID,
    TOKEN_B: USER_B_ID,
    TOKEN_NO_PROFILE: USER_NO_PROFILE_ID,
}

EXPIRED_TOKEN = "header-x.payload-expired.signature-x"
REVOKED_TOKEN = "header-y.payload-revoked.signature-y"

NOW = datetime.now(timezone.utc).isoformat()


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
        "email": "member@example.test",
        "app_metadata": {},
        "user_metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
    }


class FakeSupabaseWithProfiles:
    """Mock backend storing profiles and recording all outgoing requests."""

    def __init__(self) -> None:
        self.auth_calls: list[httpx.Request] = []
        self.rest_calls: list[httpx.Request] = []
        self.auth_behaviour: Any = None
        self.db_behaviour: Any = None
        self._lock = threading.Lock()
        self.profiles: dict[str, dict[str, Any]] = {
            USER_A_ID: {
                "user_id": USER_A_ID,
                "display_name": "Nadia Karim",
                "bio": "Software engineer interested in design systems.",
                "interests": ["Python", "SQL", "UI Design"],
                "learning_preferences": "Hands-on pair sessions",
                "availability": "Weekdays after 18:00 UTC",
                "created_at": NOW,
                "updated_at": NOW,
            },
            USER_B_ID: {
                "user_id": USER_B_ID,
                "display_name": "Tariq Mansoor",
                "bio": "Data engineer and Python enthusiast.",
                "interests": ["Data Engineering", "PostgreSQL"],
                "learning_preferences": "Async code reviews",
                "availability": "Weekends",
                "created_at": NOW,
                "updated_at": NOW,
            },
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path

        # 1. Auth endpoints
        if path == "/auth/v1/user":
            with self._lock:
                self.auth_calls.append(request)
            if self.auth_behaviour is not None:
                return self.auth_behaviour(request)
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
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

        # 2. PostgREST endpoints
        if path.startswith("/rest/v1/profiles"):
            with self._lock:
                self.rest_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            parsed_url = urlparse(str(url))
            query_params = parse_qs(parsed_url.query)
            user_id_filters = query_params.get("user_id", [])
            target_uid = None
            for f in user_id_filters:
                if f.startswith("eq."):
                    target_uid = f.removeprefix("eq.")

            if request.method == "GET":
                if target_uid and target_uid in self.profiles:
                    return httpx.Response(200, json=[self.profiles[target_uid]])
                return httpx.Response(200, json=[])

            if request.method == "PATCH":
                if not target_uid or target_uid not in self.profiles:
                    return httpx.Response(200, json=[])
                body = json.loads(request.content)
                record = self.profiles[target_uid]
                for k, v in body.items():
                    record[k] = v
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                return httpx.Response(200, json=[record])

        return httpx.Response(404, json={"msg": "not found"})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def build_test_client(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabaseWithProfiles
) -> tuple[TestClient, list[sb.UserScopedClient]]:
    active = fake_settings()
    app = create_app(Settings(_env_file=None))
    created_clients: list[sb.UserScopedClient] = []
    real_create = sb.create_user_scoped_client

    def create_with_fake(settings: Settings, token: str) -> sb.UserScopedClient:
        client = real_create(settings, token, http_client=fake.http_client())
        created_clients.append(client)
        return client

    monkeypatch.setattr(deps, "create_user_scoped_client", create_with_fake)
    app.dependency_overrides[get_app_settings] = lambda: active
    app.dependency_overrides[get_auth_verifier] = lambda: sb.create_auth_verification_client(
        active, http_client=fake.http_client()
    )

    return TestClient(app, raise_server_exceptions=False), created_clients


@pytest.fixture
def fake_db() -> FakeSupabaseWithProfiles:
    return FakeSupabaseWithProfiles()


@pytest.fixture
def test_client(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeSupabaseWithProfiles
) -> TestClient:
    client, _ = build_test_client(monkeypatch, fake_db)
    return client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# GET /profile/me Tests
# ==============================================================================


def test_get_own_profile_success(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    response = test_client.get("/profile/me", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == USER_A_ID
    assert data["display_name"] == "Nadia Karim"
    assert data["bio"] == "Software engineer interested in design systems."
    assert data["interests"] == ["Python", "SQL", "UI Design"]

    # Verify outgoing PostgREST call
    (req,) = fake_db.rest_calls
    assert req.method == "GET"
    assert "user_id=eq." + USER_A_ID in str(req.url)
    assert req.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert req.headers["apikey"] == PUBLISHABLE_KEY


def test_get_own_profile_missing_token_returns_401(test_client: TestClient) -> None:
    response = test_client.get("/profile/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"


def test_get_own_profile_invalid_token_returns_401(test_client: TestClient) -> None:
    response = test_client.get("/profile/me", headers=bearer(REVOKED_TOKEN))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "invalid_token"


def test_get_own_profile_expired_token_returns_401(test_client: TestClient) -> None:
    response = test_client.get("/profile/me", headers=bearer(EXPIRED_TOKEN))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "invalid_token"


def test_get_own_profile_not_found_returns_404(test_client: TestClient) -> None:
    response = test_client.get("/profile/me", headers=bearer(TOKEN_NO_PROFILE))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


def test_user_a_and_user_b_receive_their_own_profiles(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    resp_a = test_client.get("/profile/me", headers=bearer(TOKEN_A))
    assert resp_a.status_code == 200
    assert resp_a.json()["user_id"] == USER_A_ID
    assert resp_a.json()["display_name"] == "Nadia Karim"

    resp_b = test_client.get("/profile/me", headers=bearer(TOKEN_B))
    assert resp_b.status_code == 200
    assert resp_b.json()["user_id"] == USER_B_ID
    assert resp_b.json()["display_name"] == "Tariq Mansoor"


# ==============================================================================
# PATCH /profile/me Tests
# ==============================================================================


def test_patch_own_profile_all_fields_success(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    payload = {
        "display_name": "Nadia K.",
        "bio": "Updated bio describing hands-on projects.",
        "interests": ["Python", "FastAPI", "React", "PostgreSQL"],
        "learning_preferences": "Project-based collaborative pairing",
        "availability": "Weekday evenings UTC",
    }
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Nadia K."
    assert data["bio"] == "Updated bio describing hands-on projects."
    assert data["interests"] == ["Python", "FastAPI", "React", "PostgreSQL"]
    assert data["learning_preferences"] == "Project-based collaborative pairing"
    assert data["availability"] == "Weekday evenings UTC"
    assert data["user_id"] == USER_A_ID

    # Verify outgoing PostgREST call
    (req,) = fake_db.rest_calls
    assert req.method == "PATCH"
    assert "user_id=eq." + USER_A_ID in str(req.url)
    assert req.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert req.headers["apikey"] == PUBLISHABLE_KEY
    assert req.headers["prefer"] == "return=representation"
    sent_json = json.loads(req.content)
    assert sent_json == payload


def test_patch_own_profile_partial_update_preserves_omitted_fields(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    # Update only bio
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"bio": "Focused only on backend architecture."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["bio"] == "Focused only on backend architecture."
    assert data["display_name"] == "Nadia Karim"  # preserved
    assert data["interests"] == ["Python", "SQL", "UI Design"]  # preserved

    # Verify outgoing request sent ONLY the bio key
    (req,) = fake_db.rest_calls
    sent_json = json.loads(req.content)
    assert sent_json == {"bio": "Focused only on backend architecture."}


def test_patch_empty_body_returns_existing_profile_without_db_update(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == USER_A_ID
    assert response.json()["display_name"] == "Nadia Karim"

    # Verify that GET was performed to fetch current profile, and NO PATCH was issued
    for req in fake_db.rest_calls:
        assert req.method == "GET"


def test_patch_profile_not_found_returns_404(test_client: TestClient) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_NO_PROFILE),
        json={"bio": "Trying to update nonexistent profile"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


# ==============================================================================
# Validation Error Tests
# ==============================================================================


@pytest.mark.parametrize(
    "bad_name",
    [
        "A",
        "  A  ",
        "",
        "    ",
        "X" * 61,
    ],
)
def test_patch_invalid_display_name_rejected_with_422(
    test_client: TestClient, bad_name: str
) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"display_name": bad_name},
    )
    assert response.status_code == 422


def test_patch_excessive_bio_rejected_with_422(test_client: TestClient) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"bio": "X" * 501},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "bad_interests",
    [
        [f"Tag {i}" for i in range(11)],  # > 10
        ["Valid", ""],  # empty tag
        ["Valid", "   "],  # whitespace tag
        ["Valid", "T" * 41],  # tag > 40 chars
    ],
)
def test_patch_invalid_interests_rejected_with_422(
    test_client: TestClient, bad_interests: list[str]
) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"interests": bad_interests},
    )
    assert response.status_code == 422


def test_patch_excessive_preferences_and_availability_rejected_with_422(
    test_client: TestClient,
) -> None:
    r1 = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"learning_preferences": "P" * 301},
    )
    assert r1.status_code == 422

    r2 = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"availability": "A" * 301},
    )
    assert r2.status_code == 422


@pytest.mark.parametrize(
    "field",
    ["display_name", "bio", "interests", "learning_preferences", "availability"],
)
def test_patch_explicit_null_rejected_with_422(
    test_client: TestClient, field: str
) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={field: None},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "user_id",
        "created_at",
        "updated_at",
        "email",
        "role",
        "is_admin",
        "unknown_extra_field",
    ],
)
def test_patch_forbidden_fields_rejected_with_422(
    test_client: TestClient, forbidden_field: str
) -> None:
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={forbidden_field: "malicious_or_unknown_value"},
    )
    assert response.status_code == 422


def test_patch_cannot_override_caller_identity_with_body_user_id(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    # Attempt to pass User B's user_id in the body
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"user_id": USER_B_ID, "display_name": "Attacker Name"},
    )
    assert response.status_code == 422

    # Verify User B's profile was never touched
    assert fake_db.profiles[USER_B_ID]["display_name"] == "Tariq Mansoor"


# ==============================================================================
# Database Error Handling & Secrecy Tests
# ==============================================================================


def test_postgrest_check_constraint_failure_maps_to_422_without_leaking_sql(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    # Simulate PostgREST returning a database CHECK constraint violation (23514)
    fake_db.db_behaviour = lambda r: httpx.Response(
        400,
        json={
            "code": "23514",
            "message": 'new row violates check constraint "profiles_display_name_length" on table "profiles"',
            "details": "Failing row contains (sensitive internal sql info)",
            "hint": None,
        },
    )
    response = test_client.patch(
        "/profile/me",
        headers=bearer(TOKEN_A),
        json={"display_name": "Valid Length In Pydantic"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert "profiles_display_name_length" not in response.text
    assert "Failing row contains" not in response.text


def test_postgrest_permission_error_maps_to_403_without_leaking_sql(
    test_client: TestClient, fake_db: FakeSupabaseWithProfiles
) -> None:
    fake_db.db_behaviour = lambda r: httpx.Response(
        403,
        json={
            "code": "42501",
            "message": "permission denied for table profiles",
            "details": None,
            "hint": None,
        },
    )
    response = test_client.get("/profile/me", headers=bearer(TOKEN_A))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert "permission denied for table profiles" not in response.text


def test_tokens_and_secrets_never_appear_in_logs_or_error_responses(
    test_client: TestClient,
    fake_db: FakeSupabaseWithProfiles,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    responses = [
        test_client.get("/profile/me", headers=bearer(TOKEN_A)),
        test_client.patch("/profile/me", headers=bearer(TOKEN_A), json={"bio": "test"}),
        test_client.get("/profile/me", headers=bearer(EXPIRED_TOKEN)),
        test_client.get("/profile/me", headers=bearer(REVOKED_TOKEN)),
    ]

    for resp in responses:
        assert TOKEN_A not in resp.text
        assert PUBLISHABLE_KEY not in resp.text

    assert TOKEN_A not in caplog.text
    assert PUBLISHABLE_KEY not in caplog.text


def test_health_endpoint_remains_public(test_client: TestClient) -> None:
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
