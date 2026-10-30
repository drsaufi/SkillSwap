"""Exchange requests routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, UserDb
from app.schemas.exchange import (
    ExchangeRequestCreate,
    ExchangeRequestListResponse,
    ExchangeRequestResponse,
    ExchangeSessionResponse,
    RequestStatus,
)
from app.services import exchange_service

router = APIRouter(prefix="/exchange-requests", tags=["exchange-requests"])


@router.get("", response_model=ExchangeRequestListResponse)
def get_exchange_requests(
    current_user: CurrentUser,
    db: UserDb,
    role: Literal["incoming", "outgoing"] | None = Query(
        default=None,
        description="Filter requests by participant role: incoming or outgoing.",
    ),
    status_filter: RequestStatus | None = Query(
        default=None,
        alias="status",
        description="Filter requests by status.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Maximum items to return.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset for pagination.",
    ),
) -> ExchangeRequestListResponse:
    """Retrieve exchange requests involving the authenticated caller."""
    return exchange_service.list_exchange_requests(
        db,
        current_user.user_id,
        role=role,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=ExchangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_exchange_request(
    payload: ExchangeRequestCreate,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeRequestResponse:
    """Submit a new skill exchange request."""
    return exchange_service.create_exchange_request(
        db, current_user.user_id, payload
    )


@router.post("/{id}/accept", response_model=ExchangeSessionResponse)
def accept_exchange_request(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeSessionResponse:
    """Accept an incoming pending exchange request and create its scheduled session."""
    return exchange_service.accept_exchange_request(
        db, current_user.user_id, id
    )


@router.post("/{id}/decline", response_model=ExchangeRequestResponse)
def decline_exchange_request(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeRequestResponse:
    """Decline an incoming pending exchange request."""
    return exchange_service.decline_exchange_request(
        db, current_user.user_id, id
    )


@router.post("/{id}/cancel", response_model=ExchangeRequestResponse)
def cancel_exchange_request(
    id: UUID,
    current_user: CurrentUser,
    db: UserDb,
) -> ExchangeRequestResponse:
    """Cancel a pending request (requester only) or accepted request (either participant)."""
    return exchange_service.cancel_exchange_request(
        db, current_user.user_id, id
    )
