"""Offline unit tests for skill and member schemas, services, and repositories."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.core.errors import AppError, DatabaseOperationError
from app.repositories import profile_repo, skill_repo
from app.schemas.member import MemberDetailResponse
from app.schemas.skill import (
    SkillCreate,
    SkillListResponse,
    SkillResponse,
    SkillUpdate,
)
from app.services import member_service, skill_service

TEST_USER_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-4222-8222-222222222222")
SKILL_ID = UUID("33333333-3333-4333-8333-333333333333")
NOW = datetime.now(timezone.utc)

SAMPLE_SKILL_ROW: dict[str, Any] = {
    "id": str(SKILL_ID),
    "owner_user_id": str(TEST_USER_ID),
    "skill_name": "Python Programming",
    "category": "Technology",
    "proficiency_level": "advanced",
    "skill_type": "offered",
    "description": "Backend API development with FastAPI and AsyncIO.",
    "is_active": True,
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}

SAMPLE_PROFILE_ROW: dict[str, Any] = {
    "user_id": str(TEST_USER_ID),
    "display_name": "Nadia Karim",
    "bio": "Software engineer",
    "interests": ["Python", "SQL"],
    "learning_preferences": "Hands-on pair sessions",
    "availability": "Weekdays after 18:00 UTC",
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Ensure no real DNS or network connections can occur."""
    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError("real network access is blocked in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


# ==============================================================================
# Skill Schema Validation Tests
# ==============================================================================


def test_skill_response_validates_complete_record() -> None:
    skill = SkillResponse.model_validate(SAMPLE_SKILL_ROW)
    assert skill.id == SKILL_ID
    assert skill.owner_user_id == TEST_USER_ID
    assert skill.skill_name == "Python Programming"
    assert skill.is_active is True


def test_skill_response_is_immutable() -> None:
    skill = SkillResponse.model_validate(SAMPLE_SKILL_ROW)
    with pytest.raises(ValidationError):
        skill.skill_name = "New Name"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("Go", "Go"),
        ("  FastAPI Backend  ", "FastAPI Backend"),
        ("A" * 80, "A" * 80),
        ("   " + "B" * 80 + "   ", "B" * 80),
    ],
)
def test_skill_create_accepts_valid_name(raw_name: str, expected: str) -> None:
    created = SkillCreate(
        skill_name=raw_name,
        category="Technology",
        proficiency_level="intermediate",
        skill_type="offered",
    )
    assert created.skill_name == expected


@pytest.mark.parametrize(
    "invalid_name",
    [
        "A",  # too short (< 2)
        "   A   ",  # too short after trimming (< 2)
        "",  # empty
        "     ",  # whitespace only
        "N" * 81,  # too long (> 80)
        "  " + "N" * 81 + "  ",  # too long after trimming
    ],
)
def test_skill_create_rejects_invalid_name(invalid_name: str) -> None:
    with pytest.raises(ValidationError, match="skill_name must be between 2 and 80"):
        SkillCreate(
            skill_name=invalid_name,
            category="Technology",
            proficiency_level="intermediate",
            skill_type="offered",
        )


@pytest.mark.parametrize(
    "category",
    [
        "Technology",
        "Design",
        "Business",
        "Languages",
        "Music",
        "Arts and Crafts",
        "Health and Fitness",
        "Cooking",
        "Academics",
        "Other",
    ],
)
def test_skill_create_accepts_all_approved_categories(category: str) -> None:
    created = SkillCreate(
        skill_name="Test Skill",
        category=category,  # type: ignore[arg-type]
        proficiency_level="beginner",
        skill_type="offered",
    )
    assert created.category == category


def test_skill_create_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError):
        SkillCreate(
            skill_name="Test Skill",
            category="InvalidCategory",  # type: ignore[arg-type]
            proficiency_level="beginner",
            skill_type="offered",
        )


@pytest.mark.parametrize(
    "level",
    ["beginner", "intermediate", "advanced", "expert"],
)
def test_skill_create_accepts_all_approved_proficiency_levels(level: str) -> None:
    created = SkillCreate(
        skill_name="Test Skill",
        category="Technology",
        proficiency_level=level,  # type: ignore[arg-type]
        skill_type="offered",
    )
    assert created.proficiency_level == level


def test_skill_create_rejects_invalid_proficiency_level() -> None:
    with pytest.raises(ValidationError):
        SkillCreate(
            skill_name="Test Skill",
            category="Technology",
            proficiency_level="master",  # type: ignore[arg-type]
            skill_type="offered",
        )


@pytest.mark.parametrize("skill_type", ["offered", "wanted"])
def test_skill_create_accepts_approved_types(skill_type: str) -> None:
    created = SkillCreate(
        skill_name="Test Skill",
        category="Technology",
        proficiency_level="beginner",
        skill_type=skill_type,  # type: ignore[arg-type]
    )
    assert created.skill_type == skill_type


def test_skill_create_rejects_invalid_type() -> None:
    with pytest.raises(ValidationError):
        SkillCreate(
            skill_name="Test Skill",
            category="Technology",
            proficiency_level="beginner",
            skill_type="exchange",  # type: ignore[arg-type]
        )


def test_skill_create_accepts_valid_description() -> None:
    desc = "D" * 500
    created = SkillCreate(
        skill_name="Test Skill",
        category="Technology",
        proficiency_level="beginner",
        skill_type="offered",
        description=desc,
    )
    assert created.description == desc


def test_skill_create_rejects_excessive_description() -> None:
    with pytest.raises(ValidationError, match="description cannot exceed 500"):
        SkillCreate(
            skill_name="Test Skill",
            category="Technology",
            proficiency_level="beginner",
            skill_type="offered",
            description="D" * 501,
        )


@pytest.mark.parametrize(
    "field_name",
    ["skill_name", "category", "proficiency_level", "skill_type", "description"],
)
def test_skill_create_rejects_explicit_null(field_name: str) -> None:
    valid_data = {
        "skill_name": "Test Skill",
        "category": "Technology",
        "proficiency_level": "beginner",
        "skill_type": "offered",
        "description": "desc",
    }
    valid_data[field_name] = None  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        SkillCreate.model_validate(valid_data)


@pytest.mark.parametrize(
    "forbidden_field",
    ["id", "owner_user_id", "is_active", "created_at", "updated_at", "unknown_key"],
)
def test_skill_create_rejects_forbidden_fields(forbidden_field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SkillCreate.model_validate({
            "skill_name": "Test Skill",
            "category": "Technology",
            "proficiency_level": "beginner",
            "skill_type": "offered",
            forbidden_field: "value",
        })


# ==============================================================================
# SkillUpdate Validation Tests
# ==============================================================================


def test_skill_update_accepts_partial_fields() -> None:
    update = SkillUpdate(skill_name="Updated Name", proficiency_level="expert")
    assert update.skill_name == "Updated Name"
    assert update.proficiency_level == "expert"
    assert update.model_dump(exclude_unset=True) == {
        "skill_name": "Updated Name",
        "proficiency_level": "expert",
    }


@pytest.mark.parametrize(
    "forbidden_field",
    ["id", "owner_user_id", "skill_type", "is_active", "created_at", "updated_at"],
)
def test_skill_update_rejects_immutable_and_forbidden_fields(forbidden_field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SkillUpdate.model_validate({forbidden_field: "value"})


# ==============================================================================
# MemberDetailResponse Validation Tests
# ==============================================================================


def test_member_detail_response_validation() -> None:
    member = MemberDetailResponse(
        user_id=TEST_USER_ID,
        display_name="Nadia Karim",
        bio="Software engineer",
        interests=["Python", "SQL"],
        learning_preferences="Hands-on pair sessions",
        availability="Weekdays after 18:00 UTC",
        created_at=NOW,
        updated_at=NOW,
        skills=[SkillResponse.model_validate(SAMPLE_SKILL_ROW)],
    )
    assert member.user_id == TEST_USER_ID
    assert len(member.skills) == 1
    assert member.skills[0].id == SKILL_ID


# ==============================================================================
# Service & Repository Unit Tests
# ==============================================================================


class FakeUserScopedClient:
    pass


def test_list_skills_calls_repo_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        skill_repo,
        "select_skills",
        lambda db, **kwargs: ([SAMPLE_SKILL_ROW], 1),
    )
    res = skill_service.list_skills(FakeUserScopedClient())  # type: ignore[arg-type]
    assert isinstance(res, SkillListResponse)
    assert res.total == 1
    assert len(res.items) == 1
    assert res.items[0].skill_name == "Python Programming"


def test_create_skill_injects_owner_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_data: dict[str, Any] = {}

    def fake_insert(db: Any, data: dict[str, Any]) -> dict[str, Any]:
        nonlocal captured_data
        captured_data = data
        res = dict(SAMPLE_SKILL_ROW)
        res.update(data)
        return res

    monkeypatch.setattr(skill_repo, "insert_skill", fake_insert)

    payload = SkillCreate(
        skill_name="New Skill",
        category="Design",
        proficiency_level="intermediate",
        skill_type="wanted",
    )
    res = skill_service.create_skill(FakeUserScopedClient(), TEST_USER_ID, payload)  # type: ignore[arg-type]
    assert captured_data["owner_user_id"] == str(TEST_USER_ID)
    assert captured_data["skill_name"] == "New Skill"
    assert res.owner_user_id == TEST_USER_ID


def test_update_skill_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_repo, "select_skill_by_id", lambda db, sid: None)
    with pytest.raises(AppError) as exc_info:
        skill_service.update_skill(
            FakeUserScopedClient(), TEST_USER_ID, SKILL_ID, SkillUpdate(skill_name="Updated")  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "skill_not_found"


def test_update_skill_unauthorized_user_raises_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_repo, "select_skill_by_id", lambda db, sid: SAMPLE_SKILL_ROW)
    with pytest.raises(AppError) as exc_info:
        skill_service.update_skill(
            FakeUserScopedClient(), OTHER_USER_ID, SKILL_ID, SkillUpdate(skill_name="Updated")  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "not_permitted"


def test_update_skill_empty_update_returns_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    update_called = False

    def fake_update(db: Any, sid: Any, updates: Any) -> Any:
        nonlocal update_called
        update_called = True
        return SAMPLE_SKILL_ROW

    monkeypatch.setattr(skill_repo, "select_skill_by_id", lambda db, sid: SAMPLE_SKILL_ROW)
    monkeypatch.setattr(skill_repo, "update_skill", fake_update)

    res = skill_service.update_skill(
        FakeUserScopedClient(), TEST_USER_ID, SKILL_ID, SkillUpdate()  # type: ignore[arg-type]
    )
    assert not update_called
    assert res.id == SKILL_ID


def test_deactivate_skill_idempotent_if_already_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    inactive_row = dict(SAMPLE_SKILL_ROW, is_active=False)
    update_called = False

    def fake_update(db: Any, sid: Any, updates: Any) -> Any:
        nonlocal update_called
        update_called = True
        return inactive_row

    monkeypatch.setattr(skill_repo, "select_skill_by_id", lambda db, sid: inactive_row)
    monkeypatch.setattr(skill_repo, "update_skill", fake_update)

    res = skill_service.deactivate_skill(FakeUserScopedClient(), TEST_USER_ID, SKILL_ID)  # type: ignore[arg-type]
    assert not update_called
    assert res.is_active is False


def test_deactivate_skill_sets_is_active_false(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_updates: dict[str, Any] = {}

    def fake_update(db: Any, sid: Any, updates: Any) -> Any:
        nonlocal captured_updates
        captured_updates = updates
        res = dict(SAMPLE_SKILL_ROW)
        res.update(updates)
        return res

    monkeypatch.setattr(skill_repo, "select_skill_by_id", lambda db, sid: SAMPLE_SKILL_ROW)
    monkeypatch.setattr(skill_repo, "update_skill", fake_update)

    res = skill_service.deactivate_skill(FakeUserScopedClient(), TEST_USER_ID, SKILL_ID)  # type: ignore[arg-type]
    assert captured_updates == {"is_active": False}
    assert res.is_active is False


def test_get_member_detail_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: None)
    with pytest.raises(AppError) as exc_info:
        member_service.get_member_detail(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "member_not_found"


def test_get_member_detail_returns_profile_and_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: SAMPLE_PROFILE_ROW)
    monkeypatch.setattr(skill_repo, "select_skills", lambda db, **kwargs: ([SAMPLE_SKILL_ROW], 1))

    res = member_service.get_member_detail(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert res.user_id == TEST_USER_ID
    assert res.display_name == "Nadia Karim"
    assert len(res.skills) == 1
    assert res.skills[0].skill_name == "Python Programming"


def test_repo_catches_api_error_on_insert(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingQueryBuilder:
        def insert(self, *args: Any) -> FailingQueryBuilder:
            return self

        def select(self, *args: Any) -> FailingQueryBuilder:
            return self

        def single(self) -> FailingQueryBuilder:
            return self

        def execute(self) -> Any:
            raise APIError({"code": "23505", "message": "duplicate key violates unique constraint", "details": None, "hint": None})

    class FailingClient:
        def table(self, table_name: str) -> FailingQueryBuilder:
            return FailingQueryBuilder()

    with pytest.raises(DatabaseOperationError) as exc_info:
        skill_repo.insert_skill(FailingClient(), {"skill_name": "Test"})  # type: ignore[arg-type]
    assert exc_info.value.sqlstate == "23505"


def test_skill_update_rejects_explicit_null_category() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SkillUpdate.model_validate({"category": None})
    assert "category cannot be null" in str(exc_info.value)


def test_skill_update_rejects_explicit_null_proficiency_level() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SkillUpdate.model_validate({"proficiency_level": None})
    assert "proficiency_level cannot be null" in str(exc_info.value)


def test_skill_update_accepts_valid_category_and_proficiency() -> None:
    u1 = SkillUpdate.model_validate({"category": "Technology"})
    assert u1.category == "Technology"
    u2 = SkillUpdate.model_validate({"proficiency_level": "expert"})
    assert u2.proficiency_level == "expert"


def test_skill_update_permits_omitted_fields() -> None:
    u = SkillUpdate.model_validate({})
    assert u.model_dump(exclude_unset=True) == {}


def test_get_member_detail_with_zero_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: SAMPLE_PROFILE_ROW)
    monkeypatch.setattr(skill_repo, "select_skills", lambda db, **kwargs: ([], 0))

    res = member_service.get_member_detail(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert res.user_id == TEST_USER_ID
    assert res.skills == []


def test_get_member_detail_with_105_skills_paginates_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: SAMPLE_PROFILE_ROW)

    skills_105 = [
        dict(
            SAMPLE_SKILL_ROW,
            id=str(uuid4()),
            skill_name=f"Skill {i}",
            created_at=f"2026-01-01T{i%24:02d}:00:00Z",
        )
        for i in range(105)
    ]

    def fake_select(db: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 100)
        return (skills_105[offset : offset + limit], 105)

    monkeypatch.setattr(skill_repo, "select_skills", fake_select)

    res = member_service.get_member_detail(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert len(res.skills) == 105
    assert res.skills[0].skill_name == "Skill 0"
    assert res.skills[104].skill_name == "Skill 104"


def test_get_member_detail_empty_page_breaks_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: SAMPLE_PROFILE_ROW)
    # Total claims 50, but page returns empty
    monkeypatch.setattr(skill_repo, "select_skills", lambda db, **kwargs: ([], 50))

    res = member_service.get_member_detail(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert res.skills == []
