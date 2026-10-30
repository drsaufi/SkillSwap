"""Business logic service for session reviews."""

from __future__ import annotations

from uuid import UUID

from app.core.supabase import UserScopedClient
from app.repositories import review_repo
from app.schemas.review import ReviewCreate, ReviewResponse


def create_review(
    db: UserScopedClient,
    user_id: UUID,
    session_id: UUID,
    review_in: ReviewCreate,
) -> ReviewResponse:
    """Create a post-exchange review via public.create_review RPC."""
    review_data = review_repo.rpc_create_review(
        db,
        session_id=session_id,
        rating=review_in.rating,
        comment=review_in.comment,
    )
    return ReviewResponse.model_validate(review_data)
