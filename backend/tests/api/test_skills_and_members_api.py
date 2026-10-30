"""Offline API integration tests for /skills and /members endpoints.

All tests run against real FastAPI routing, dependencies, services, repositories
and PostgREST query building via an offline MockTransport.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

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

TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"

KNOWN_USERS = {
    TOKEN_A: USER_A_ID,
    TOKEN_B: USER_B_ID,
}

EXPIRED_TOKEN = "header-x.payload-expired.signature-x"
REVOKED_TOKEN = "header-y.payload-revoked.signature-y"

NOW = datetime.now(timezone.utc).isoformat()

SKILL_1_ID = "11111111-0000-4000-8000-000000000001"
SKILL_2_ID = "22222222-0000-4000-8000-000000000002"
SKILL_3_ID = "33333333-0000-4000-8000-000000000003"
SKILL_INACTIVE_ID = "44444444-0000-4000-8000-000000000004"


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


class FakeSupabaseSkillsAndMembers:
    """Mock backend storing profiles and skills and recording all outgoing requests."""

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
                "bio": "Software engineer",
                "interests": ["Python", "SQL"],
                "learning_preferences": "Pairing",
                "availability": "Evenings",
                "created_at": NOW,
                "updated_at": NOW,
            },
            USER_B_ID: {
                "user_id": USER_B_ID,
                "display_name": "Tariq Mansoor",
                "bio": "Data engineer",
                "interests": ["PostgreSQL"],
                "learning_preferences": "Async",
                "availability": "Weekends",
                "created_at": NOW,
                "updated_at": NOW,
            },
        }

        self.skills: dict[str, dict[str, Any]] = {
            SKILL_1_ID: {
                "id": SKILL_1_ID,
                "owner_user_id": USER_A_ID,
                "skill_name": "Python Programming",
                "category": "Technology",
                "proficiency_level": "advanced",
                "skill_type": "offered",
                "description": "Backend API development.",
                "is_active": True,
                "created_at": "2026-01-01T10:00:00Z",
                "updated_at": "2026-01-01T10:00:00Z",
            },
            SKILL_2_ID: {
                "id": SKILL_2_ID,
                "owner_user_id": USER_A_ID,
                "skill_name": "UI Design",
                "category": "Design",
                "proficiency_level": "intermediate",
                "skill_type": "wanted",
                "description": "Figma design systems.",
                "is_active": True,
                "created_at": "2026-01-02T10:00:00Z",
                "updated_at": "2026-01-02T10:00:00Z",
            },
            SKILL_3_ID: {
                "id": SKILL_3_ID,
                "owner_user_id": USER_B_ID,
                "skill_name": "PostgreSQL Optimization",
                "category": "Technology",
                "proficiency_level": "expert",
                "skill_type": "offered",
                "description": "Query performance and schema design.",
                "is_active": True,
                "created_at": "2026-01-03T10:00:00Z",
                "updated_at": "2026-01-03T10:00:00Z",
            },
            SKILL_INACTIVE_ID: {
                "id": SKILL_INACTIVE_ID,
                "owner_user_id": USER_A_ID,
                "skill_name": "Legacy C++",
                "category": "Technology",
                "proficiency_level": "intermediate",
                "skill_type": "offered",
                "description": "Old skill listing.",
                "is_active": False,
                "created_at": "2026-01-01T08:00:00Z",
                "updated_at": "2026-01-01T08:00:00Z",
            },
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path

        # 1. Auth requests
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

        # 2. Profiles table
        if path.startswith("/rest/v1/profiles"):
            with self._lock:
                self.rest_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            parsed = urlparse(str(url))
            qp = parse_qs(parsed.query)
            target_uid = None
            for f in qp.get("user_id", []):
                if f.startswith("eq."):
                    target_uid = f.removeprefix("eq.")

            if request.method == "GET":
                if target_uid and target_uid in self.profiles:
                    return httpx.Response(200, json=[self.profiles[target_uid]])
                return httpx.Response(200, json=[])

        # 3. Skills table
        if path.startswith("/rest/v1/skills"):
            with self._lock:
                self.rest_calls.append(request)
            if self.db_behaviour is not None:
                return self.db_behaviour(request)

            parsed = urlparse(str(url))
            qp = parse_qs(parsed.query)

            # Check single id filter (e.g. id=eq.<id>)
            target_id = None
            for f in qp.get("id", []):
                if f.startswith("eq."):
                    target_id = f.removeprefix("eq.")

            if request.method == "GET":
                if target_id:
                    if target_id in self.skills:
                        return httpx.Response(200, json=[self.skills[target_id]])
                    return httpx.Response(200, json=[])

                # Filtering / search query
                results = list(self.skills.values())

                if "is_active" in qp:
                    val = qp["is_active"][0].removeprefix("eq.").lower() == "true"
                    results = [r for r in results if r["is_active"] == val]

                if "category" in qp:
                    val = qp["category"][0].removeprefix("eq.")
                    results = [r for r in results if r["category"] == val]

                if "proficiency_level" in qp:
                    val = qp["proficiency_level"][0].removeprefix("eq.")
                    results = [r for r in results if r["proficiency_level"] == val]

                if "skill_type" in qp:
                    val = qp["skill_type"][0].removeprefix("eq.")
                    results = [r for r in results if r["skill_type"] == val]

                if "owner_user_id" in qp:
                    val = qp["owner_user_id"][0].removeprefix("eq.")
                    results = [r for r in results if r["owner_user_id"] == val]

                if "skill_name" in qp:
                    pattern = qp["skill_name"][0].removeprefix("ilike.")
                    search_str = pattern.strip("%").lower()
                    results = [r for r in results if search_str in r["skill_name"].lower()]

                # Sort by created_at desc
                results.sort(key=lambda r: r["created_at"], reverse=True)
                total = len(results)

                # Pagination offset / limit
                offset = int(qp.get("offset", [0])[0])
                limit = int(qp.get("limit", [20])[0])
                paged = results[offset : offset + limit]

                # PostgREST sends Content-Range or returns headers
                return httpx.Response(
                    200,
                    json=paged,
                    headers={"Content-Range": f"{offset}-{offset + len(paged)}/{total}"},
                )

            if request.method == "POST":
                body = json.loads(request.content)
                new_id = str(uuid4())
                new_record = {
                    "id": new_id,
                    "owner_user_id": body.get("owner_user_id", USER_A_ID),
                    "skill_name": body["skill_name"],
                    "category": body["category"],
                    "proficiency_level": body["proficiency_level"],
                    "skill_type": body["skill_type"],
                    "description": body.get("description", ""),
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.skills[new_id] = new_record
                return httpx.Response(201, json=new_record)

            if request.method == "PATCH":
                if not target_id or target_id not in self.skills:
                    return httpx.Response(200, json=[])
                body = json.loads(request.content)
                record = self.skills[target_id]
                for k, v in body.items():
                    record[k] = v
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                return httpx.Response(200, json=[record])

        return httpx.Response(404, json={"msg": "not found"})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def build_test_client(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabaseSkillsAndMembers
) -> TestClient:
    active = fake_settings()
    app = create_app(Settings(_env_file=None))
    real_create = sb.create_user_scoped_client

    def create_with_fake(settings: Settings, token: str) -> sb.UserScopedClient:
        return real_create(settings, token, http_client=fake.http_client())

    monkeypatch.setattr(deps, "create_user_scoped_client", create_with_fake)
    app.dependency_overrides[get_app_settings] = lambda: active
    app.dependency_overrides[get_auth_verifier] = lambda: sb.create_auth_verification_client(
        active, http_client=fake.http_client()
    )

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_db() -> FakeSupabaseSkillsAndMembers:
    return FakeSupabaseSkillsAndMembers()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, fake_db: FakeSupabaseSkillsAndMembers
) -> TestClient:
    return build_test_client(monkeypatch, fake_db)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# GET /skills Tests
# ==============================================================================


def test_get_skills_default_discovery(client: TestClient) -> None:
    response = client.get("/skills", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 3  # Active skills only by default
    assert all(item["is_active"] is True for item in data["items"])


def test_get_skills_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/skills")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_get_skills_filter_by_category(client: TestClient) -> None:
    response = client.get("/skills?category=Technology", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert all(item["category"] == "Technology" for item in data["items"])
    assert data["total"] == 2


def test_get_skills_filter_by_type(client: TestClient) -> None:
    response = client.get("/skills?skill_type=wanted", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["skill_name"] == "UI Design"


def test_get_skills_filter_by_proficiency_level(client: TestClient) -> None:
    response = client.get("/skills?proficiency_level=expert", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["skill_name"] == "PostgreSQL Optimization"


def test_get_skills_filter_by_owner_user_id(client: TestClient) -> None:
    response = client.get(f"/skills?owner_user_id={USER_B_ID}", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["owner_user_id"] == USER_B_ID


def test_get_skills_search_name(client: TestClient) -> None:
    response = client.get("/skills?search=python", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["skill_name"] == "Python Programming"


def test_get_skills_pagination_and_empty_results(client: TestClient) -> None:
    response = client.get("/skills?limit=1&offset=10", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["limit"] == 1
    assert data["offset"] == 10


# ==============================================================================
# POST /skills Tests
# ==============================================================================


def test_create_skill_success(client: TestClient, fake_db: FakeSupabaseSkillsAndMembers) -> None:
    payload = {
        "skill_name": "Docker & Kubernetes",
        "category": "Technology",
        "proficiency_level": "intermediate",
        "skill_type": "offered",
        "description": "Container orchestration fundamentals.",
    }
    response = client.post("/skills", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["skill_name"] == "Docker & Kubernetes"
    assert data["owner_user_id"] == USER_A_ID
    assert data["is_active"] is True
    assert "id" in data

    # Verify outgoing PostgREST call
    (req,) = [r for r in fake_db.rest_calls if r.method == "POST"]
    sent = json.loads(req.content)
    assert sent["owner_user_id"] == USER_A_ID
    assert req.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert req.headers["apikey"] == PUBLISHABLE_KEY


@pytest.mark.parametrize(
    ("bad_payload", "error_field"),
    [
        (
            {"skill_name": "A", "category": "Technology", "proficiency_level": "beginner", "skill_type": "offered"},
            "skill_name",
        ),
        (
            {"skill_name": "Valid Name", "category": "FakeCategory", "proficiency_level": "beginner", "skill_type": "offered"},
            "category",
        ),
        (
            {"skill_name": "Valid Name", "category": "Technology", "proficiency_level": "master", "skill_type": "offered"},
            "proficiency_level",
        ),
        (
            {"skill_name": "Valid Name", "category": "Technology", "proficiency_level": "beginner", "skill_type": "both"},
            "skill_type",
        ),
        (
            {"skill_name": "Valid Name", "category": "Technology", "proficiency_level": "beginner", "skill_type": "offered", "description": "X" * 501},
            "description",
        ),
        (
            {"skill_name": None, "category": "Technology", "proficiency_level": "beginner", "skill_type": "offered"},
            "skill_name",
        ),
        (
            {"skill_name": "Valid Name", "category": "Technology", "proficiency_level": "beginner", "skill_type": "offered", "owner_user_id": USER_B_ID},
            "owner_user_id",
        ),
    ],
)
def test_create_skill_validation_failures(client: TestClient, bad_payload: dict[str, Any], error_field: str) -> None:
    response = client.post("/skills", headers=bearer(TOKEN_A), json=bad_payload)
    assert response.status_code == 422


def test_create_skill_duplicate_active_conflict_maps_to_409(
    client: TestClient, fake_db: FakeSupabaseSkillsAndMembers
) -> None:
    fake_db.db_behaviour = lambda r: httpx.Response(
        400,
        json={
            "code": "23505",
            "message": 'duplicate key value violates unique constraint "skills_unique_active_per_owner"',
            "details": None,
            "hint": None,
        },
    )
    payload = {
        "skill_name": "Python Programming",
        "category": "Technology",
        "proficiency_level": "advanced",
        "skill_type": "offered",
    }
    response = client.post("/skills", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "duplicate_active_skill"


# ==============================================================================
# PATCH /skills/{id} Tests
# ==============================================================================


def test_patch_skill_success(client: TestClient, fake_db: FakeSupabaseSkillsAndMembers) -> None:
    payload = {
        "skill_name": "Python 3 & FastAPI",
        "proficiency_level": "expert",
    }
    response = client.patch(f"/skills/{SKILL_1_ID}", headers=bearer(TOKEN_A), json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["skill_name"] == "Python 3 & FastAPI"
    assert data["proficiency_level"] == "expert"
    assert data["category"] == "Technology"  # preserved


def test_patch_skill_empty_update_returns_existing_without_db_update(client: TestClient) -> None:
    response = client.patch(f"/skills/{SKILL_1_ID}", headers=bearer(TOKEN_A), json={})
    assert response.status_code == 200
    assert response.json()["skill_name"] == "Python Programming"


def test_patch_skill_unauthorized_user_returns_403(client: TestClient) -> None:
    # User B attempts to edit User A's skill
    response = client.patch(
        f"/skills/{SKILL_1_ID}",
        headers=bearer(TOKEN_B),
        json={"skill_name": "Hacked Name"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_permitted"


def test_patch_skill_not_found_returns_404(client: TestClient) -> None:
    non_existent = str(uuid4())
    response = client.patch(
        f"/skills/{non_existent}",
        headers=bearer(TOKEN_A),
        json={"skill_name": "Nonexistent"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "skill_not_found"


def test_patch_skill_immutable_fields_rejected_with_422(client: TestClient) -> None:
    for field in ("id", "owner_user_id", "skill_type", "is_active", "created_at"):
        response = client.patch(
            f"/skills/{SKILL_1_ID}",
            headers=bearer(TOKEN_A),
            json={field: "value"},
        )
        assert response.status_code == 422


def test_patch_skill_rejects_null_category_and_proficiency_level(
    client: TestClient, fake_db: FakeSupabaseSkillsAndMembers
) -> None:
    initial_patch_calls = [r for r in fake_db.rest_calls if r.method == "PATCH"]

    # Explicit null category
    res1 = client.patch(
        f"/skills/{SKILL_1_ID}",
        headers=bearer(TOKEN_A),
        json={"category": None},
    )
    assert res1.status_code == 422
    assert "category" in res1.text

    # Explicit null proficiency_level
    res2 = client.patch(
        f"/skills/{SKILL_1_ID}",
        headers=bearer(TOKEN_A),
        json={"proficiency_level": None},
    )
    assert res2.status_code == 422
    assert "proficiency_level" in res2.text

    # Proves no database UPDATE operation was issued for invalid requests
    patch_calls_after = [r for r in fake_db.rest_calls if r.method == "PATCH"]
    assert len(patch_calls_after) == len(initial_patch_calls)

    # Valid values succeed
    res3 = client.patch(
        f"/skills/{SKILL_1_ID}",
        headers=bearer(TOKEN_A),
        json={"category": "Technology", "proficiency_level": "beginner"},
    )
    assert res3.status_code == 200
    assert res3.json()["proficiency_level"] == "beginner"


def test_patch_skill_referenced_in_request_conflict_maps_to_409(
    client: TestClient, fake_db: FakeSupabaseSkillsAndMembers
) -> None:
    # First request fetches skill (GET); second request updates skill (PATCH) which fails
    def behaviour(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(
                400,
                json={
                    "code": "P0001",
                    "message": "skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead",
                    "details": None,
                    "hint": None,
                },
            )
        return httpx.Response(200, json=[fake_db.skills[SKILL_1_ID]])

    fake_db.db_behaviour = behaviour

    response = client.patch(
        f"/skills/{SKILL_1_ID}",
        headers=bearer(TOKEN_A),
        json={"skill_name": "Renamed Skill"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "skill_in_use"


# ==============================================================================
# DELETE /skills/{id} Tests
# ==============================================================================


def test_deactivate_skill_success(client: TestClient, fake_db: FakeSupabaseSkillsAndMembers) -> None:
    response = client.delete(f"/skills/{SKILL_1_ID}", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == SKILL_1_ID
    assert data["is_active"] is False

    # Proves skill was soft-deactivated, not deleted
    assert fake_db.skills[SKILL_1_ID]["is_active"] is False


def test_deactivate_already_inactive_skill_is_idempotent(client: TestClient) -> None:
    response = client.delete(f"/skills/{SKILL_INACTIVE_ID}", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_deactivate_skill_unauthorized_user_returns_403(client: TestClient) -> None:
    response = client.delete(f"/skills/{SKILL_1_ID}", headers=bearer(TOKEN_B))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_permitted"


def test_deactivate_skill_not_found_returns_404(client: TestClient) -> None:
    non_existent = str(uuid4())
    response = client.delete(f"/skills/{non_existent}", headers=bearer(TOKEN_A))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "skill_not_found"


# ==============================================================================
# GET /members/{id} Tests
# ==============================================================================


def test_get_member_detail_success(client: TestClient) -> None:
    response = client.get(f"/members/{USER_A_ID}", headers=bearer(TOKEN_B))
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == USER_A_ID
    assert data["display_name"] == "Nadia Karim"
    assert "email" not in data
    assert "skills" in data
    assert len(data["skills"]) == 2  # Active skills only (SKILL_1 and SKILL_2)
    skill_names = {s["skill_name"] for s in data["skills"]}
    assert "Python Programming" in skill_names
    assert "UI Design" in skill_names
    assert "Legacy C++" not in skill_names  # Inactive skill omitted


def test_get_member_detail_with_zero_skills(
    client: TestClient, fake_db: FakeSupabaseSkillsAndMembers
) -> None:
    # Remove User B's skills from mock db
    del fake_db.skills[SKILL_3_ID]

    response = client.get(f"/members/{USER_B_ID}", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == USER_B_ID
    assert data["skills"] == []


def test_get_member_detail_with_more_than_100_skills_paginates_all(
    client: TestClient, fake_db: FakeSupabaseSkillsAndMembers
) -> None:
    # Seed 105 active skills for USER_B_ID in fake_db
    for i in range(105):
        s_id = str(uuid4())
        fake_db.skills[s_id] = {
            "id": s_id,
            "owner_user_id": USER_B_ID,
            "skill_name": f"Bulk Skill {i:03d}",
            "category": "Technology",
            "proficiency_level": "intermediate",
            "skill_type": "offered",
            "description": f"Bulk skill listing #{i}",
            "is_active": True,
            "created_at": f"2026-01-01T{i%24:02d}:00:00Z",
            "updated_at": f"2026-01-01T{i%24:02d}:00:00Z",
        }

    response = client.get(f"/members/{USER_B_ID}", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == USER_B_ID
    # USER_B previously had SKILL_3_ID (1) + 105 newly seeded skills = 106 total active skills
    assert len(data["skills"]) == 106
    names = {s["skill_name"] for s in data["skills"]}
    assert "Bulk Skill 000" in names
    assert "Bulk Skill 104" in names
    assert "PostgreSQL Optimization" in names


def test_get_member_detail_not_found_returns_404(client: TestClient) -> None:
    non_existent = str(uuid4())
    response = client.get(f"/members/{non_existent}", headers=bearer(TOKEN_A))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "member_not_found"


# ==============================================================================
# Security & Health Tests
# ==============================================================================


def test_tokens_and_secrets_never_leak(
    client: TestClient,
    fake_db: FakeSupabaseSkillsAndMembers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    client.get("/skills", headers=bearer(TOKEN_A))
    client.post(
        "/skills",
        headers=bearer(TOKEN_A),
        json={"skill_name": "Test", "category": "Technology", "proficiency_level": "beginner", "skill_type": "offered"},
    )
    client.get(f"/members/{USER_A_ID}", headers=bearer(TOKEN_A))

    assert TOKEN_A not in caplog.text
    assert PUBLISHABLE_KEY not in caplog.text


def test_health_remains_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
