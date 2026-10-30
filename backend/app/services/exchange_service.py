"""Business logic service for exchange requests and exchange sessions."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from app.api.deps import AuthenticatedUser
from app.core.errors import AppError
from app.core.supabase import UserScopedClient
from app.repositories import exchange_repo
from app.schemas.exchange import (
    ExchangeRequestCreate,
    ExchangeRequestListResponse,
    ExchangeRequestResponse,
    ExchangeSessionResponse,
)


def list_exchange_requests(
    db: UserScopedClient,
    user_id: UUID,
    *,
    role: Literal["incoming", "outgoing"] | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ExchangeRequestListResponse:
    """List exchange requests where the caller is a participant."""
    items_data, total = exchange_repo.select_exchange_requests(
        db,
        user_id=user_id,
        role=role,
        status=status,
        limit=limit,
        offset=offset,
    )
    enriched_items = exchange_repo.enrich_exchange_requests(db, items_data)
    items = [ExchangeRequestResponse.model_validate(r) for r in enriched_items]
    return ExchangeRequestListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


def create_exchange_request(
    db: UserScopedClient,
    user_id: UUID,
    request_in: ExchangeRequestCreate,
) -> ExchangeRequestResponse:
    """Create a new pending exchange request for the authenticated user."""
    if request_in.receiver_user_id == user_id:
        raise AppError(
            status_code=422,
            error_code="self_request_not_allowed",
            message="You cannot create an exchange request to yourself.",
        )

    payload = {
        "requester_user_id": str(user_id),
        "receiver_user_id": str(request_in.receiver_user_id),
        "offered_skill_id": str(request_in.offered_skill_id),
        "wanted_skill_id": str(request_in.wanted_skill_id),
        "message": request_in.message,
        "proposed_datetime": request_in.proposed_datetime.isoformat(),
        "format": request_in.format,
    }

    record = exchange_repo.insert_exchange_request(db, payload)
    enriched = exchange_repo.enrich_exchange_requests(db, [record])
    return ExchangeRequestResponse.model_validate(enriched[0] if enriched else record)


def accept_exchange_request(
    db: UserScopedClient,
    user_id: UUID,
    request_id: UUID,
) -> ExchangeSessionResponse:
    """Accept a pending exchange request (receiver only) and create its session."""
    session_data = exchange_repo.rpc_accept_exchange_request(db, request_id)
    return ExchangeSessionResponse.model_validate(session_data)


def decline_exchange_request(
    db: UserScopedClient,
    user_id: UUID,
    request_id: UUID,
) -> ExchangeRequestResponse:
    """Decline a pending exchange request (receiver only)."""
    request_data = exchange_repo.rpc_decline_exchange_request(db, request_id)
    enriched = exchange_repo.enrich_exchange_requests(db, [request_data])
    return ExchangeRequestResponse.model_validate(enriched[0] if enriched else request_data)


def cancel_exchange_request(
    db: UserScopedClient,
    user_id: UUID,
    request_id: UUID,
) -> ExchangeRequestResponse:
    """Cancel a pending request (requester only) or accepted request (either participant)."""
    request_data = exchange_repo.rpc_cancel_exchange_request(db, request_id)
    enriched = exchange_repo.enrich_exchange_requests(db, [request_data])
    return ExchangeRequestResponse.model_validate(enriched[0] if enriched else request_data)


def get_exchange_session(
    db: UserScopedClient,
    user_id: UUID,
    session_id: UUID,
) -> ExchangeSessionResponse:
    """Retrieve an exchange session where caller is a participant."""
    session_data = exchange_repo.select_exchange_session_by_id(db, session_id)
    if session_data is None:
        raise AppError(
            status_code=404,
            error_code="session_not_found",
            message="Exchange session not found.",
        )
    return ExchangeSessionResponse.model_validate(session_data)


def get_exchange_session_by_request(
    db: UserScopedClient,
    user_id: UUID,
    request_id: UUID,
) -> ExchangeSessionResponse:
    """Retrieve an exchange session for a request where caller is an authorized participant."""
    session_data = exchange_repo.select_exchange_session_by_request_id(
        db, request_id
    )
    if session_data is None:
        raise AppError(
            status_code=404,
            error_code="session_not_found",
            message="Exchange session not found.",
        )
    return ExchangeSessionResponse.model_validate(session_data)


def confirm_exchange_session(
    db: UserScopedClient,
    user_id: UUID,
    session_id: UUID,
) -> ExchangeSessionResponse:
    """Record participant session completion confirmation."""
    session_data = exchange_repo.rpc_confirm_exchange_session(db, session_id)
    return ExchangeSessionResponse.model_validate(session_data)
