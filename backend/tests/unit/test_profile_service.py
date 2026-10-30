"""Offline unit tests for profile schemas, repository, and service."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.core.errors import AppError, DatabaseOperationError
from app.repositories import profile_repo
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services import profile_service

TEST_USER_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime.now(timezone.utc)

SAMPLE_PROFILE_ROW: dict[str, Any] = {
    "user_id": str(TEST_USER_ID),
    "display_name": "Nadia Karim",
    "bio": "Software engineer interested in design systems.",
    "interests": ["Python", "SQL", "UI Design"],
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
# Schema Validation Tests
# ==============================================================================


def test_profile_response_validates_complete_record() -> None:
    profile = ProfileResponse.model_validate(SAMPLE_PROFILE_ROW)
    assert profile.user_id == TEST_USER_ID
    assert profile.display_name == "Nadia Karim"
    assert profile.interests == ["Python", "SQL", "UI Design"]


def test_profile_response_is_immutable() -> None:
    profile = ProfileResponse.model_validate(SAMPLE_PROFILE_ROW)
    with pytest.raises(ValidationError):
        profile.display_name = "New Name"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw_name", "expected"),
    [
        ("NK", "NK"),
        ("  Nadia Karim  ", "Nadia Karim"),
        ("A" * 60, "A" * 60),
        ("   " + "B" * 60 + "   ", "B" * 60),
    ],
)
def test_profile_update_accepts_valid_display_name(raw_name: str, expected: str) -> None:
    update = ProfileUpdate(display_name=raw_name)
    assert update.display_name == expected


@pytest.mark.parametrize(
    "invalid_name",
    [
        "A",  # too short (< 2)
        "   A   ",  # too short after trimming (< 2)
        "",  # empty
        "     ",  # whitespace only
        "N" * 61,  # too long (> 60)
        "  " + "N" * 61 + "  ",  # too long after trimming
    ],
)
def test_profile_update_rejects_invalid_display_name(invalid_name: str) -> None:
    with pytest.raises(ValidationError, match="display_name must be between 2 and 60"):
        ProfileUpdate(display_name=invalid_name)


def test_profile_update_accepts_valid_bio() -> None:
    bio = "B" * 500
    update = ProfileUpdate(bio=bio)
    assert update.bio == bio


def test_profile_update_rejects_excessive_bio() -> None:
    with pytest.raises(ValidationError, match="bio cannot exceed 500"):
        ProfileUpdate(bio="B" * 501)


def test_profile_update_accepts_valid_interests() -> None:
    tags = [f"Tag {i}" for i in range(10)]
    update = ProfileUpdate(interests=tags)
    assert update.interests == tags

    empty_tags = ProfileUpdate(interests=[])
    assert empty_tags.interests == []


def test_profile_update_rejects_more_than_10_interests() -> None:
    with pytest.raises(ValidationError, match="cannot contain more than 10"):
        ProfileUpdate(interests=[f"Tag {i}" for i in range(11)])


@pytest.mark.parametrize(
    "bad_tag",
    [
        "",  # blank
        "   ",  # whitespace
        "T" * 41,  # exceeds 40
        "  " + "T" * 41 + "  ",  # exceeds 40 before trimming
    ],
)
def test_profile_update_rejects_invalid_interest_tags(bad_tag: str) -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate(interests=["Python", bad_tag])


def test_profile_update_accepts_valid_learning_preferences_and_availability() -> None:
    update = ProfileUpdate(
        learning_preferences="L" * 300,
        availability="A" * 300,
    )
    assert update.learning_preferences == "L" * 300
    assert update.availability == "A" * 300


def test_profile_update_rejects_excessive_preferences_and_availability() -> None:
    with pytest.raises(ValidationError, match="learning_preferences cannot exceed 300"):
        ProfileUpdate(learning_preferences="L" * 301)
    with pytest.raises(ValidationError, match="availability cannot exceed 300"):
        ProfileUpdate(availability="A" * 301)


@pytest.mark.parametrize(
    "field_name",
    ["display_name", "bio", "interests", "learning_preferences", "availability"],
)
def test_profile_update_rejects_explicit_null_values(field_name: str) -> None:
    with pytest.raises(ValidationError, match="cannot be null"):
        ProfileUpdate.model_validate({field_name: None})


@pytest.mark.parametrize(
    "forbidden_field",
    ["user_id", "created_at", "updated_at", "email", "role", "unknown_field"],
)
def test_profile_update_rejects_forbidden_fields(forbidden_field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProfileUpdate.model_validate({forbidden_field: "value"})


def test_profile_update_empty_payload() -> None:
    update = ProfileUpdate.model_validate({})
    assert update.model_dump(exclude_unset=True) == {}


# ==============================================================================
# Service & Repository Unit Tests
# ==============================================================================


class FakeUserScopedClient:
    """Mock UserScopedClient for repository tests."""
    pass


def test_get_my_profile_returns_validated_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        profile_repo,
        "select_by_user_id",
        lambda db, uid: SAMPLE_PROFILE_ROW if uid == TEST_USER_ID else None,
    )
    res = profile_service.get_my_profile(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert res.user_id == TEST_USER_ID
    assert res.display_name == "Nadia Karim"


def test_get_my_profile_raises_404_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: None)
    with pytest.raises(AppError) as exc_info:
        profile_service.get_my_profile(FakeUserScopedClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "profile_not_found"


def test_update_my_profile_empty_payload_skips_update(monkeypatch: pytest.MonkeyPatch) -> None:
    update_called = False

    def fake_update(db: Any, uid: Any, updates: Any) -> Any:
        nonlocal update_called
        update_called = True
        return SAMPLE_PROFILE_ROW

    monkeypatch.setattr(profile_repo, "select_by_user_id", lambda db, uid: SAMPLE_PROFILE_ROW)
    monkeypatch.setattr(profile_repo, "update_by_user_id", fake_update)

    res = profile_service.update_my_profile(
        FakeUserScopedClient(), TEST_USER_ID, ProfileUpdate()  # type: ignore[arg-type]
    )
    assert not update_called
    assert res.user_id == TEST_USER_ID


def test_update_my_profile_calls_repo_with_exclude_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_updates: dict[str, Any] = {}

    def fake_update(db: Any, uid: Any, updates: Any) -> Any:
        nonlocal captured_updates
        captured_updates = updates
        updated_row = dict(SAMPLE_PROFILE_ROW)
        updated_row.update(updates)
        return updated_row

    monkeypatch.setattr(profile_repo, "update_by_user_id", fake_update)

    payload = ProfileUpdate(bio="New updated bio")
    res = profile_service.update_my_profile(
        FakeUserScopedClient(), TEST_USER_ID, payload  # type: ignore[arg-type]
    )
    assert captured_updates == {"bio": "New updated bio"}
    assert res.bio == "New updated bio"


def test_update_my_profile_raises_404_when_profile_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(profile_repo, "update_by_user_id", lambda db, uid, updates: None)
    payload = ProfileUpdate(bio="New updated bio")
    with pytest.raises(AppError) as exc_info:
        profile_service.update_my_profile(
            FakeUserScopedClient(), TEST_USER_ID, payload  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "profile_not_found"


def test_repo_catches_and_translates_postgrest_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingQueryBuilder:
        def select(self, *args: Any) -> FailingQueryBuilder:
            return self

        def eq(self, *args: Any) -> FailingQueryBuilder:
            return self

        def maybe_single(self) -> FailingQueryBuilder:
            return self

        def execute(self) -> Any:
            raise APIError({"code": "23514", "message": "check constraint failed", "details": None})

    class FailingClient:
        def table(self, table_name: str) -> FailingQueryBuilder:
            return FailingQueryBuilder()

    with pytest.raises(DatabaseOperationError) as exc_info:
        profile_repo.select_by_user_id(FailingClient(), TEST_USER_ID)  # type: ignore[arg-type]
    assert exc_info.value.sqlstate == "23514"
