"""Skills API routes for skill discovery, creation, editing and deactivation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, UserDb
from app.schemas.skill import (
    SkillCategory,
    SkillCreate,
    SkillListResponse,
    SkillProficiencyLevel,
    SkillResponse,
    SkillType,
    SkillUpdate,
)
from app.services import skill_service

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=SkillListResponse)
def list_skills(
    _current_user: CurrentUser,
    db: UserDb,
    search: str | None = Query(default=None, description="Search by skill name"),
    category: SkillCategory | None = Query(default=None, description="Filter by category"),
    proficiency_level: SkillProficiencyLevel | None = Query(
        default=None, description="Filter by proficiency level"
    ),
    skill_type: SkillType | None = Query(
        default=None, description="Filter by skill type (offered/wanted)"
    ),
    owner_user_id: UUID | None = Query(
        default=None, description="Filter by owner user UUID"
    ),
    is_active: bool = Query(default=True, description="Filter by active status"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> SkillListResponse:
    """Search and filter member skills."""
    return skill_service.list_skills(
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


@router.post("", response_model=SkillResponse, status_code=201)
def create_skill(
    payload: SkillCreate,
    current_user: CurrentUser,
    db: UserDb,
) -> SkillResponse:
    """Create a new offered or wanted skill listing."""
    return skill_service.create_skill(db, current_user.user_id, payload)


@router.patch("/{id}", response_model=SkillResponse)
def update_skill(
    id: UUID,
    payload: SkillUpdate,
    current_user: CurrentUser,
    db: UserDb,
) -> SkillResponse:
    """Update editable details of a skill owned by the caller."""
    return skill_service.update_skill(db, current_user.user_id, id, payload)


@router.delete("/{id}", response_model=SkillResponse)
def deactivate_skill(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> SkillResponse:
    """Soft-deactivate an existing skill owned by the caller."""
    return skill_service.deactivate_skill(db, current_user.user_id, id)
