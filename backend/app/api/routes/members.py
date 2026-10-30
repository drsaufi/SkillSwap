"""Members API routes for viewing member directory profiles."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserDb
from app.schemas.member import MemberDetailResponse
from app.services import member_service

router = APIRouter(prefix="/members", tags=["members"])


@router.get("/{id}", response_model=MemberDetailResponse)
def get_member(
    id: UUID,
    _current_user: CurrentUser,
    db: UserDb,
) -> MemberDetailResponse:
    """Retrieve public member details and active offered/wanted skills."""
    return member_service.get_member_detail(db, id)
