"""Business service for member directory and member details."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.core.supabase import UserScopedClient
from app.repositories import profile_repo, skill_repo
from app.schemas.member import MemberDetailResponse
from app.schemas.skill import SkillResponse

MEMBER_SKILLS_PAGE_SIZE = 100


def member_not_found_error() -> AppError:
    """Return safe HTTP 404 error when member does not exist."""
    return AppError(
        status_code=404,
        error_code="member_not_found",
        message="Member not found.",
    )


def get_member_detail(
    db: UserScopedClient, member_id: UUID
) -> MemberDetailResponse:
    """Fetch member public profile and all active skills with pagination."""
    profile_row = profile_repo.select_by_user_id(db, member_id)
    if profile_row is None:
        raise member_not_found_error()

    all_skill_rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        page_rows, total = skill_repo.select_skills(
            db,
            owner_user_id=member_id,
            is_active=True,
            limit=MEMBER_SKILLS_PAGE_SIZE,
            offset=offset,
        )
        if not page_rows:
            break

        all_skill_rows.extend(page_rows)
        offset += len(page_rows)

        if len(all_skill_rows) >= total or len(page_rows) < MEMBER_SKILLS_PAGE_SIZE:
            break

    active_skills = [SkillResponse.model_validate(r) for r in all_skill_rows]

    return MemberDetailResponse(
        user_id=profile_row["user_id"],
        display_name=profile_row["display_name"],
        bio=profile_row.get("bio", ""),
        interests=profile_row.get("interests", []),
        learning_preferences=profile_row.get("learning_preferences", ""),
        availability=profile_row.get("availability", ""),
        created_at=profile_row["created_at"],
        updated_at=profile_row["updated_at"],
        skills=active_skills,
    )
