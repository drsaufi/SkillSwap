"""Exchange sessions routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, UserDb
from app.schemas.exchange import ExchangeSessionResponse
from app.schemas.review import ReviewCreate, ReviewResponse
from app.services import exchange_service, review_service

router = APIRouter(prefix="/exchange-sessions", tags=["exchange-sessions"])


@router.get("/{id}", response_model=ExchangeSessionResponse)
def get_exchange_session(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeSessionResponse:
    """Retrieve an exchange session where caller is an authorized participant."""
    return exchange_service.get_exchange_session(
        db, current_user.user_id, id
    )


@router.post("/{id}/confirm", response_model=ExchangeSessionResponse)
def confirm_exchange_session(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeSessionResponse:
    """Record participant session completion confirmation."""
    return exchange_service.confirm_exchange_session(
        db, current_user.user_id, id
    )


@router.post(
    "/{id}/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session_review(
    id: UUID,
    payload: ReviewCreate,
    current_user: CurrentUser,
    db: UserDb,
) -> ReviewResponse:
    """Submit a post-exchange review for a completed session."""
    return review_service.create_review(
        db, current_user.user_id, id, payload
    )
