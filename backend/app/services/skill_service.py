"""Business service for skill listings, search, creation, editing and deactivation."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError
from app.core.supabase import UserScopedClient
from app.repositories import skill_repo
from app.schemas.skill import (
    SkillCreate,
    SkillListResponse,
    SkillResponse,
    SkillUpdate,
)


def skill_not_found_error() -> AppError:
    """Return safe HTTP 404 error when skill does not exist."""
    return AppError(
        status_code=404,
        error_code="skill_not_found",
        message="Skill not found.",
    )


def skill_forbidden_error() -> AppError:
    """Return safe HTTP 403 error when user does not own the skill."""
    return AppError(
        status_code=403,
        error_code="not_permitted",
        message="You are not permitted to modify this skill.",
    )


def list_skills(
    db: UserScopedClient,
    *,
    search: str | None = None,
    category: str | None = None,
    proficiency_level: str | None = None,
    skill_type: str | None = None,
    owner_user_id: UUID | None = None,
    is_active: bool | None = True,
    limit: int = 20,
    offset: int = 0,
) -> SkillListResponse:
    """Query skills with discovery filters and deterministic sorting."""
    rows, total = skill_repo.select_skills(
        db,
        search=search,
        category=category,
        proficiency_level=proficiency_level,
        skill_type=skill_type,
        owner_user_id=owner_user_id,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    items = [SkillResponse.model_validate(r) for r in rows]
    return SkillListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


def create_skill(
    db: UserScopedClient, user_id: UUID, payload: SkillCreate
) -> SkillResponse:
    """Create a new skill owned by the authenticated caller."""
    data = payload.model_dump()
    data["owner_user_id"] = str(user_id)
    row = skill_repo.insert_skill(db, data)
    return SkillResponse.model_validate(row)


def update_skill(
    db: UserScopedClient, user_id: UUID, skill_id: UUID, payload: SkillUpdate
) -> SkillResponse:
    """Update editable fields on an existing skill owned by the caller."""
    existing = skill_repo.select_skill_by_id(db, skill_id)
    if existing is None:
        raise skill_not_found_error()

    if UUID(str(existing["owner_user_id"])) != user_id:
        raise skill_forbidden_error()

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return SkillResponse.model_validate(existing)

    row = skill_repo.update_skill(db, skill_id, updates)
    if row is None:
        raise skill_not_found_error()
    return SkillResponse.model_validate(row)


def deactivate_skill(
    db: UserScopedClient, user_id: UUID, skill_id: UUID
) -> SkillResponse:
    """Soft-deactivate an existing skill owned by the caller (is_active=False)."""
    existing = skill_repo.select_skill_by_id(db, skill_id)
    if existing is None:
        raise skill_not_found_error()

    if UUID(str(existing["owner_user_id"])) != user_id:
        raise skill_forbidden_error()

    if existing.get("is_active") is False:
        # Idempotent soft-deactivation: already inactive
        return SkillResponse.model_validate(existing)

    row = skill_repo.update_skill(db, skill_id, {"is_active": False})
    if row is None:
        raise skill_not_found_error()
    return SkillResponse.model_validate(row)
