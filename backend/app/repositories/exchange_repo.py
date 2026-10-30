"""Database repository for exchange requests and exchange sessions."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from postgrest.exceptions import APIError

from app.core.errors import DatabaseOperationError
from app.core.supabase import UserScopedClient

EXCHANGE_REQUEST_COLUMNS = (
    "id, requester_user_id, receiver_user_id, offered_skill_id, "
    "wanted_skill_id, message, status, proposed_datetime, format, "
    "created_at, updated_at"
)

EXCHANGE_SESSION_COLUMNS = (
    "id, request_id, scheduled_datetime, completion_status, "
    "requester_confirmed_at, receiver_confirmed_at, completed_at, "
    "notes, created_at, updated_at"
)

ALLOWED_REQUEST_INSERT_COLUMNS = frozenset(
    {
        "requester_user_id",
        "receiver_user_id",
        "offered_skill_id",
        "wanted_skill_id",
        "message",
        "proposed_datetime",
        "format",
    }
)


def _extract_single_record(data: Any) -> dict[str, Any]:
    """Extract a single dict record from PostgREST response data."""
    if isinstance(data, list):
        if not data:
            raise DatabaseOperationError(message="Empty response from database operation")
        return data[0]
    if isinstance(data, dict):
        return data
    raise DatabaseOperationError(message="Unexpected response format from database operation")


def select_exchange_requests(
    client: UserScopedClient,
    *,
    user_id: UUID,
    role: Literal["incoming", "outgoing"] | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Query exchange requests with participant filtering, pagination and exact count."""
    try:
        query = client.table("exchange_requests").select(
            EXCHANGE_REQUEST_COLUMNS, count="exact"
        )

        if role == "incoming":
            query = query.eq("receiver_user_id", str(user_id))
        elif role == "outgoing":
            query = query.eq("requester_user_id", str(user_id))
        else:
            query = query.or_(
                f"requester_user_id.eq.{user_id},receiver_user_id.eq.{user_id}"
            )

        if status:
            query = query.eq("status", status)

        query = query.order("created_at", desc=True).order("id", desc=False)
        query = query.range(offset, offset + limit - 1)

        response = query.execute()
        items = response.data if response.data is not None else []
        total = response.count if response.count is not None else len(items)
        return items, total
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def select_exchange_request_by_id(
    client: UserScopedClient, request_id: UUID
) -> dict[str, Any] | None:
    """Fetch a single exchange request by primary key."""
    try:
        response = (
            client.table("exchange_requests")
            .select(EXCHANGE_REQUEST_COLUMNS)
            .eq("id", str(request_id))
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def insert_exchange_request(
    client: UserScopedClient, request_data: dict[str, Any]
) -> dict[str, Any]:
    """Insert a new exchange request row and return the created record."""
    payload = {
        k: v for k, v in request_data.items() if k in ALLOWED_REQUEST_INSERT_COLUMNS
    }
    try:
        response = (
            client.table("exchange_requests")
            .insert(payload)
            .select(EXCHANGE_REQUEST_COLUMNS)
            .single()
            .execute()
        )
        return response.data
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def rpc_accept_exchange_request(
    client: UserScopedClient, request_id: UUID
) -> dict[str, Any]:
    """Invoke public.accept_exchange_request(p_request_id)."""
    try:
        response = client.rpc(
            "accept_exchange_request",
            {"p_request_id": str(request_id)},
        ).execute()
        return _extract_single_record(response.data)
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def rpc_decline_exchange_request(
    client: UserScopedClient, request_id: UUID
) -> dict[str, Any]:
    """Invoke public.decline_exchange_request(p_request_id)."""
    try:
        response = client.rpc(
            "decline_exchange_request",
            {"p_request_id": str(request_id)},
        ).execute()
        return _extract_single_record(response.data)
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def rpc_cancel_exchange_request(
    client: UserScopedClient, request_id: UUID
) -> dict[str, Any]:
    """Invoke public.cancel_exchange_request(p_request_id)."""
    try:
        response = client.rpc(
            "cancel_exchange_request",
            {"p_request_id": str(request_id)},
        ).execute()
        return _extract_single_record(response.data)
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def select_exchange_session_by_id(
    client: UserScopedClient, session_id: UUID
) -> dict[str, Any] | None:
    """Fetch a single exchange session by primary key."""
    try:
        response = (
            client.table("exchange_sessions")
            .select(EXCHANGE_SESSION_COLUMNS)
            .eq("id", str(session_id))
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def select_exchange_session_by_request_id(
    client: UserScopedClient, request_id: UUID
) -> dict[str, Any] | None:
    """Fetch a single exchange session associated with request_id (RLS enforced)."""
    try:
        response = (
            client.table("exchange_sessions")
            .select(EXCHANGE_SESSION_COLUMNS)
            .eq("request_id", str(request_id))
            .maybe_single()
            .execute()
        )
        return response.data if response is not None else None
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def rpc_confirm_exchange_session(
    client: UserScopedClient, session_id: UUID
) -> dict[str, Any]:
    """Invoke public.confirm_exchange_session(p_session_id)."""
    try:
        response = client.rpc(
            "confirm_exchange_session",
            {"p_session_id": str(session_id)},
        ).execute()
        return _extract_single_record(response.data)
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc
