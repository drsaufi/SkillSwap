"""Profile API routes for the authenticated member."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserDb
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.profile_service import get_my_profile, update_my_profile

router = APIRouter(prefix="/profile", tags=["profiles"])


@router.get("/me", response_model=ProfileResponse)
def get_own_profile(
    current_user: CurrentUser,
    db: UserDb,
) -> ProfileResponse:
    """Retrieve the profile of the currently authenticated member."""
    return get_my_profile(db, current_user.user_id)


@router.patch("/me", response_model=ProfileResponse)
def update_own_profile(
    payload: ProfileUpdate,
    current_user: CurrentUser,
    db: UserDb,
) -> ProfileResponse:
    """Partially update the profile of the currently authenticated member."""
    return update_my_profile(db, current_user.user_id, payload)
