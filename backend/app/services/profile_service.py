"""Profile service containing business rules for member profile management."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import AppError
from app.core.supabase import UserScopedClient
from app.repositories import profile_repo
from app.schemas.profile import ProfileResponse, ProfileUpdate


def profile_not_found_error() -> AppError:
    """Return safe HTTP 404 error when profile does not exist."""
    return AppError(
        status_code=404,
        error_code="profile_not_found",
        message="Profile not found.",
    )


def get_my_profile(db: UserScopedClient, user_id: UUID) -> ProfileResponse:
    """Fetch the authenticated user's profile."""
    row = profile_repo.select_by_user_id(db, user_id)
    if row is None:
        raise profile_not_found_error()
    return ProfileResponse.model_validate(row)


def update_my_profile(
    db: UserScopedClient, user_id: UUID, payload: ProfileUpdate
) -> ProfileResponse:
    """Update allowlisted fields on the authenticated user's profile."""
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        # Empty PATCH is a no-op: return current profile without issuing UPDATE.
        return get_my_profile(db, user_id)

    row = profile_repo.update_by_user_id(db, user_id, update_data)
    if row is None:
        raise profile_not_found_error()
    return ProfileResponse.model_validate(row)
