"""Offline unit tests for reviews, dashboard, and AI skill matching schemas, repositories, and services."""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError, DatabaseOperationError, translate_db_error
from app.repositories import dashboard_repo, profile_repo, review_repo, skill_repo
from app.schemas.ai import (
    AiSkillMatchRequest,
)
from app.schemas.dashboard import DashboardSummaryResponse
from app.schemas.review import ReviewCreate, ReviewResponse
from app.services import ai_service, dashboard_service, review_service

USER_A_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_B_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_C_ID = UUID("33333333-3333-4333-8333-333333333333")
USER_D_ID = UUID("44444444-4444-4444-8444-444444444444")

SESSION_ID = UUID("77777777-7777-4777-8777-777777777777")
REQUEST_ID = UUID("66666666-6666-4666-8666-666666666666")
REVIEW_ID = UUID("88888888-8888-4888-8888-888888888888")

SKILL_A_OFFERED_ID = UUID("aaaaaaaa-1111-4111-8111-111111111111")
SKILL_A_WANTED_ID = UUID("aaaaaaaa-2222-4222-8222-222222222222")
SKILL_B_OFFERED_ID = UUID("bbbbbbbb-1111-4111-8111-111111111111")
SKILL_B_WANTED_ID = UUID("bbbbbbbb-2222-4222-8222-222222222222")
SKILL_C_OFFERED_ID = UUID("cccccccc-1111-4111-8111-111111111111")

NOW = datetime.now(timezone.utc)
FUTURE_TIME = NOW + timedelta(days=2)

SAMPLE_REVIEW_ROW: dict[str, Any] = {
    "id": str(REVIEW_ID),
    "session_id": str(SESSION_ID),
    "reviewer_user_id": str(USER_A_ID),
    "reviewee_user_id": str(USER_B_ID),
    "rating": 5,
    "comment": "Great peer learning session!",
    "created_at": NOW.isoformat(),
}

SAMPLE_SESSION_ROW: dict[str, Any] = {
    "id": str(SESSION_ID),
    "request_id": str(REQUEST_ID),
    "scheduled_datetime": FUTURE_TIME.isoformat(),
    "completion_status": "scheduled",
    "requester_confirmed_at": None,
    "receiver_confirmed_at": None,
    "completed_at": None,
    "notes": "Prepare Python exercises.",
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Ensure no real DNS or network connections can occur."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError("real network access is blocked in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "gethostbyname", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


class FakeUserScopedClient:
    """Mock UserScopedClient for unit tests."""


# ==============================================================================
# 1. Review Schema & Service Unit Tests
# ==============================================================================


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_review_create_valid_ratings(rating: int) -> None:
    payload = ReviewCreate(rating=rating, comment="  Helpful mentor!  ")
    assert payload.rating == rating
    assert payload.comment == "Helpful mentor!"


def test_review_create_default_comment_and_rejects_null_comment() -> None:
    p1 = ReviewCreate(rating=4)
    assert p1.comment == ""

    with pytest.raises(ValidationError):
        ReviewCreate(rating=4, comment=None)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_rating", [0, -1, 6, 100, True, False, None, "5"])
def test_review_create_rejects_invalid_rating(bad_rating: Any) -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(rating=bad_rating)


def test_review_create_rejects_comment_over_500_chars() -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(rating=5, comment="x" * 501)


def test_review_create_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ReviewCreate(rating=5, comment="Nice", reviewer_user_id=str(USER_A_ID))  # type: ignore[call-arg]


def test_review_service_create_review_success(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeUserScopedClient()
    captured: dict[str, Any] = {}

    def fake_rpc(
        client: Any, *, session_id: UUID, rating: int, comment: str
    ) -> dict[str, Any]:
        captured["session_id"] = session_id
        captured["rating"] = rating
        captured["comment"] = comment
        return dict(SAMPLE_REVIEW_ROW, rating=rating, comment=comment)

    monkeypatch.setattr(review_repo, "rpc_create_review", fake_rpc)

    payload = ReviewCreate(rating=5, comment="  Excellent explanation!  ")
    result = review_service.create_review(
        db, USER_A_ID, SESSION_ID, payload  # type: ignore[arg-type]
    )

    assert isinstance(result, ReviewResponse)
    assert result.id == REVIEW_ID
    assert result.session_id == SESSION_ID
    assert result.reviewer_user_id == USER_A_ID
    assert result.reviewee_user_id == USER_B_ID
    assert result.rating == 5
    assert result.comment == "Excellent explanation!"
    assert captured == {
        "session_id": SESSION_ID,
        "rating": 5,
        "comment": "Excellent explanation!",
    }


def test_review_repo_raises_when_rpc_returns_empty_list() -> None:
    with pytest.raises(DatabaseOperationError) as exc_info:
        review_repo._extract_single_record([])
    assert "Empty response" in exc_info.value.raw_message


@pytest.mark.parametrize(
    ("code", "message", "expected_status", "expected_error_code"),
    [
        ("23505", "review_already_exists: duplicate", 409, "review_already_exists"),
        ("P0001", "session_not_completed: still scheduled", 409, "session_not_completed"),
        ("42501", "review_not_permitted: not a participant", 403, "review_not_permitted"),
        ("P0002", "session_not_found: missing", 404, "session_not_found"),
    ],
)
def test_review_repo_maps_postgrest_errors(
    code: str,
    message: str,
    expected_status: int,
    expected_error_code: str,
) -> None:
    class FailingRpcClient:
        def rpc(self, fn_name: str, params: dict[str, Any]) -> Any:
            class Runner:
                def execute(self) -> Any:
                    raise APIError({"code": code, "message": message})

            return Runner()

    with pytest.raises(DatabaseOperationError) as exc_info:
        review_repo.rpc_create_review(
            FailingRpcClient(),  # type: ignore[arg-type]
            session_id=SESSION_ID,
            rating=5,
            comment="Great",
        )
    mapped = translate_db_error(
        exc_info.value.sqlstate, exc_info.value.raw_message
    )
    assert mapped.status_code == expected_status
    assert mapped.error_code == expected_error_code


# ==============================================================================
# 2. Dashboard Service Unit Tests
# ==============================================================================


def test_dashboard_service_populated_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeUserScopedClient()

    monkeypatch.setattr(
        dashboard_repo,
        "count_active_skills_by_type",
        lambda client, user_id, skill_type: 3 if skill_type == "offered" else 2,
    )
    monkeypatch.setattr(
        dashboard_repo,
        "count_pending_requests_by_role",
        lambda client, user_id, role: 4 if role == "incoming" else 1,
    )
    monkeypatch.setattr(
        dashboard_repo,
        "count_exchanges_by_status",
        lambda client, user_id, status: 2 if status == "accepted" else 5,
    )
    monkeypatch.setattr(
        dashboard_repo,
        "select_received_review_ratings",
        lambda client, user_id: [5, 4, 4],
    )
    monkeypatch.setattr(
        dashboard_repo,
        "select_upcoming_sessions",
        lambda client, limit=5: [SAMPLE_SESSION_ROW],
    )

    summary = dashboard_service.get_dashboard_summary(db, USER_A_ID)  # type: ignore[arg-type]

    assert isinstance(summary, DashboardSummaryResponse)
    assert summary.active_offered_skills_count == 3
    assert summary.active_wanted_skills_count == 2
    assert summary.incoming_pending_requests_count == 4
    assert summary.outgoing_pending_requests_count == 1
    assert summary.accepted_exchanges_count == 2
    assert summary.completed_exchanges_count == 5
    assert summary.average_rating == 4.33
    assert summary.reviews_received_count == 3
    assert len(summary.upcoming_sessions) == 1
    assert summary.upcoming_sessions[0].id == SESSION_ID


def test_dashboard_service_empty_account_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeUserScopedClient()

    monkeypatch.setattr(
        dashboard_repo, "count_active_skills_by_type", lambda *a, **kw: 0
    )
    monkeypatch.setattr(
        dashboard_repo, "count_pending_requests_by_role", lambda *a, **kw: 0
    )
    monkeypatch.setattr(
        dashboard_repo, "count_exchanges_by_status", lambda *a, **kw: 0
    )
    monkeypatch.setattr(
        dashboard_repo, "select_received_review_ratings", lambda *a, **kw: []
    )
    monkeypatch.setattr(
        dashboard_repo, "select_upcoming_sessions", lambda *a, **kw: []
    )

    summary = dashboard_service.get_dashboard_summary(db, USER_A_ID)  # type: ignore[arg-type]

    assert summary.active_offered_skills_count == 0
    assert summary.active_wanted_skills_count == 0
    assert summary.incoming_pending_requests_count == 0
    assert summary.outgoing_pending_requests_count == 0
    assert summary.accepted_exchanges_count == 0
    assert summary.completed_exchanges_count == 0
    assert summary.average_rating is None
    assert summary.reviews_received_count == 0
    assert summary.upcoming_sessions == []


def test_select_upcoming_sessions_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeQuery:
        def select(self, cols: str) -> FakeQuery:
            captured["cols"] = cols
            return self

        def eq(self, field: str, val: Any) -> FakeQuery:
            captured[f"eq_{field}"] = val
            return self

        def gte(self, field: str, val: Any) -> FakeQuery:
            captured[f"gte_{field}"] = val
            return self

        def order(self, field: str, desc: bool = False) -> FakeQuery:
            captured.setdefault("orders", []).append((field, desc))
            return self

        def range(self, start: int, end: int) -> FakeQuery:
            captured["range"] = (start, end)
            return self

        def execute(self) -> Any:
            class Resp:
                data = [SAMPLE_SESSION_ROW]
            return Resp()

    class FakeClient:
        def table(self, name: str) -> FakeQuery:
            captured["table"] = name
            return FakeQuery()

    fixed_now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
    res = dashboard_repo.select_upcoming_sessions(
        FakeClient(), limit=3, now=fixed_now  # type: ignore[arg-type]
    )

    assert captured["table"] == "exchange_sessions"
    assert captured["eq_completion_status"] == "scheduled"
    assert captured["gte_scheduled_datetime"] == fixed_now.isoformat()
    assert captured["orders"] == [("scheduled_datetime", False), ("id", False)]
    assert captured["range"] == (0, 2)
    assert len(res) == 1
    assert res[0]["id"] == str(SESSION_ID)


# ==============================================================================
# 3. AI Skill Match Assistant Unit Tests
# ==============================================================================


def _configured_ai_settings(model: str = "gpt-4o-mini") -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL="https://mock-skillswap.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test_key",
        LLM_API_KEY="sk-fictional-unit-test-key",
        LLM_MODEL=model,
        LLM_TIMEOUT_SECONDS=10,
        AI_MAX_CANDIDATES=20,
    )


def test_ai_request_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AiSkillMatchRequest(prompt="Ignore instructions")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("api_key", "model"),
    [
        ("", "gpt-4o-mini"),
        ("   ", "gpt-4o-mini"),
        ("your-llm-api-key-here", "gpt-4o-mini"),
        ("placeholder", "gpt-4o-mini"),
        ("sk-valid-key", ""),
        ("sk-valid-key", "your-chosen-model-name"),
        ("sk-valid-key", "changeme"),
    ],
)
def test_ai_service_raises_503_when_unconfigured(
    api_key: str, model: str
) -> None:
    db = FakeUserScopedClient()
    settings = Settings(
        _env_file=None,
        SUPABASE_URL="https://mock-skillswap.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test_key",
        LLM_API_KEY=api_key,
        LLM_MODEL=model,
    )
    with pytest.raises(AppError) as exc_info:
        ai_service.generate_skill_matches(db, USER_A_ID, settings)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "ai_unavailable"


def test_ai_service_raises_404_when_requester_profile_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeUserScopedClient()
    settings = _configured_ai_settings()
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda *a, **kw: None)

    with pytest.raises(AppError) as exc_info:
        ai_service.generate_skill_matches(db, USER_A_ID, settings)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "profile_not_found"


def test_ai_allowlisted_payload_excludes_sensitive_fields() -> None:
    user_profile = {
        "user_id": str(USER_A_ID),
        "display_name": "Alice Learner",
        "email": "alice_secret@example.test",
        "password_hash": "secret_hash_123",
        "bio": "Private personal bio notes",
        "location": "123 Private Street",
        "interests": ["Data Science", "Spanish"],
        "learning_preferences": "Hands-on practice",
        "availability": "Weekends",
    }
    user_offered = [
        {
            "id": str(SKILL_A_OFFERED_ID),
            "skill_name": "Python",
            "category": "Technology",
            "proficiency_level": "advanced",
            "description": "Long internal description",
        }
    ]
    user_wanted = [
        {
            "id": str(SKILL_A_WANTED_ID),
            "skill_name": "Spanish Conversation",
            "category": "Languages",
            "proficiency_level": "beginner",
        }
    ]
    candidates = [
        {
            "user_id": USER_B_ID,
            "display_name": "Carlos Mentor",
            "interests": ["Technology"],
            "learning_preferences": "Pair sessions",
            "availability": "Weekends",
            "offered_skills": [
                {
                    "id": str(SKILL_B_OFFERED_ID),
                    "skill_name": "Spanish Conversation",
                    "category": "Languages",
                    "proficiency_level": "expert",
                }
            ],
            "wanted_skills": [
                {
                    "id": str(SKILL_B_WANTED_ID),
                    "skill_name": "Python",
                    "category": "Technology",
                    "proficiency_level": "beginner",
                }
            ],
        }
    ]

    payload = ai_service._build_allowlisted_llm_payload(
        user_profile=user_profile,
        user_offered=user_offered,
        user_wanted=user_wanted,
        candidates=candidates,
    )
    serialized = json.dumps(payload)

    assert "alice_secret@example.test" not in serialized
    assert "secret_hash_123" not in serialized
    assert "123 Private Street" not in serialized
    assert "Private personal bio notes" not in serialized
    assert set(payload["requester"].keys()) == {
        "interests",
        "learning_preferences",
        "availability",
        "offered_skills",
        "wanted_skills",
    }
    assert set(payload["candidates"][0].keys()) == {
        "member_user_id",
        "display_name",
        "interests",
        "learning_preferences",
        "availability",
        "offered_skills",
        "wanted_skills",
    }


def test_ai_grounding_validation_discards_hallucinations_and_caps_at_three() -> None:
    uid_1 = UUID("22222222-1111-4111-8111-111111111111")
    uid_2 = UUID("22222222-2222-4222-8222-222222222222")
    uid_3 = UUID("22222222-3333-4333-8333-333333333333")
    uid_4 = UUID("22222222-4444-4444-8444-444444444444")

    sk_1 = UUID("bbbbbbbb-1111-4111-8111-111111111111")
    sk_1_want = UUID("bbbbbbbb-1111-4222-8222-222222222222")
    sk_2 = UUID("bbbbbbbb-2222-4111-8111-111111111111")
    sk_3 = UUID("bbbbbbbb-3333-4111-8111-111111111111")
    sk_4 = UUID("bbbbbbbb-4444-4111-8111-111111111111")

    def make_candidate(
        uid: UUID, name: str, off_id: UUID, want_id: UUID | None = None
    ) -> dict[str, Any]:
        off = {
            "id": str(off_id),
            "skill_name": f"Skill {name}",
            "category": "Technology",
            "proficiency_level": "advanced",
            "skill_type": "offered",
        }
        wanted_by_id = {}
        if want_id is not None:
            wanted_by_id[want_id] = {
                "id": str(want_id),
                "skill_name": "Wanted Python",
                "category": "Technology",
                "proficiency_level": "beginner",
                "skill_type": "wanted",
            }
        return {
            "user_id": uid,
            "display_name": name,
            "offered_by_id": {off_id: off},
            "wanted_by_id": wanted_by_id,
        }

    candidates_by_id = {
        uid_1: make_candidate(uid_1, "Bob", sk_1, sk_1_want),
        uid_2: make_candidate(uid_2, "Carol", sk_2),
        uid_3: make_candidate(uid_3, "Dave", sk_3),
        uid_4: make_candidate(uid_4, "Eve", sk_4),
    }

    raw_matches: list[Any] = [
        # 1. Hallucinated member UUID -> discarded
        {
            "member_user_id": str(uuid4()),
            "offered_skill_id": str(sk_1),
            "explanation": "Invented user",
        },
        # 2. Mismatched echoed display_name -> discarded
        {
            "member_user_id": str(uid_1),
            "display_name": "Wrong Name",
            "offered_skill_id": str(sk_1),
            "explanation": "Name mismatch",
        },
        # 3. Skill belongs to Carol (sk_2), not Bob (uid_1) -> discarded
        {
            "member_user_id": str(uid_1),
            "offered_skill_id": str(sk_2),
            "explanation": "Cross-member skill",
        },
        # 4. Invalid matching_wanted_skill_id -> discarded
        {
            "member_user_id": str(uid_1),
            "offered_skill_id": str(sk_1),
            "matching_wanted_skill_id": str(uuid4()),
            "explanation": "Fake wanted skill",
        },
        # 5. Empty explanation -> discarded
        {
            "member_user_id": str(uid_1),
            "offered_skill_id": str(sk_1),
            "explanation": "   ",
        },
        # 6. Valid match 1 (Bob)
        {
            "member_user_id": str(uid_1),
            "offered_skill_id": str(sk_1),
            "matching_wanted_skill_id": str(sk_1_want),
            "explanation": "Bob offers Skill Bob and wants Wanted Python.",
        },
        # 7. Duplicate member Bob -> discarded
        {
            "member_user_id": str(uid_1),
            "offered_skill_id": str(sk_1),
            "explanation": "Duplicate Bob entry.",
        },
        # 8. Valid match 2 (Carol)
        {
            "member_user_id": str(uid_2),
            "offered_skill_id": str(sk_2),
            "matching_wanted_skill_id": None,
            "explanation": "Carol offers Skill Carol.",
        },
        # 9. Valid match 3 (Dave)
        {
            "member_user_id": str(uid_3),
            "offered_skill_id": str(sk_3),
            "explanation": "Dave offers Skill Dave.",
        },
        # 10. Valid match 4 (Eve) -> capped because max is 3
        {
            "member_user_id": str(uid_4),
            "offered_skill_id": str(sk_4),
            "explanation": "Eve offers Skill Eve.",
        },
    ]

    validated = ai_service._validate_and_ground_matches(
        raw_matches, candidates_by_id
    )

    assert len(validated) == 3
    assert [m.member_user_id for m in validated] == [uid_1, uid_2, uid_3]
    assert validated[0].display_name == "Bob"
    assert validated[0].offered_skill.skill_name == "Skill Bob"
    assert validated[0].matching_wanted_skill_id == sk_1_want
    assert validated[0].matching_wanted_skill is not None
    assert validated[0].matching_wanted_skill.skill_name == "Wanted Python"
    # Grounded factual explanation
    assert "Bob offers Skill Bob and is looking to learn Wanted Python." in validated[0].explanation
    assert validated[1].matching_wanted_skill_id is None
    assert validated[1].matching_wanted_skill is None
    assert "Carol offers Skill Carol, which is available through their SkillSwap profile." in validated[1].explanation


def test_ai_candidate_cap_enforced_at_twenty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = FakeUserScopedClient()
    settings = _configured_ai_settings()

    user_uid = USER_A_ID
    candidate_uids = [
        UUID(f"00000000-0000-4000-8000-{i:012d}") for i in range(1, 26)
    ]

    def fake_select_profile(client: Any, uid: UUID) -> dict[str, Any]:
        if uid == user_uid:
            return {
                "user_id": str(user_uid),
                "display_name": "Requester",
                "interests": ["Python"],
                "learning_preferences": "Online",
                "availability": "Weekends",
            }
        return {
            "user_id": str(uid),
            "display_name": f"Candidate {uid.hex[-4:]}",
            "interests": ["Python"],
            "learning_preferences": "Online",
            "availability": "Weekends",
        }

    directory_skills = [
        {
            "id": str(UUID(f"11111111-0000-4000-8000-{i:012d}")),
            "owner_user_id": str(uid),
            "skill_name": "Python",
            "category": "Technology",
            "proficiency_level": "advanced",
            "skill_type": "offered",
            "is_active": True,
        }
        for i, uid in enumerate(candidate_uids, start=1)
    ]

    def fake_select_skills(
        client: Any,
        *,
        owner_user_id: UUID | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        if owner_user_id == user_uid:
            return (
                [
                    {
                        "id": str(SKILL_A_WANTED_ID),
                        "owner_user_id": str(user_uid),
                        "skill_name": "Python",
                        "category": "Technology",
                        "proficiency_level": "beginner",
                        "skill_type": "wanted",
                        "is_active": True,
                    }
                ],
                1,
            )
        return directory_skills, len(directory_skills)

    captured_payload: dict[str, Any] = {}

    def fake_call_llm(
        s: Settings, payload: dict[str, Any]
    ) -> dict[str, Any]:
        captured_payload.update(payload)
        first_cand = payload["candidates"][0]
        return {
            "matches": [
                {
                    "member_user_id": first_cand["member_user_id"],
                    "offered_skill_id": first_cand["offered_skills"][0]["id"],
                    "matching_wanted_skill_id": None,
                    "explanation": "Strong Python match.",
                }
            ]
        }

    monkeypatch.setattr(profile_repo, "select_by_user_id", fake_select_profile)
    monkeypatch.setattr(skill_repo, "select_skills", fake_select_skills)
    monkeypatch.setattr(ai_service, "_call_llm_provider", fake_call_llm)

    res = ai_service.generate_skill_matches(db, user_uid, settings)  # type: ignore[arg-type]

    assert res.candidate_count == 20
    assert len(captured_payload["candidates"]) == 20
    assert len(res.matches) == 1
