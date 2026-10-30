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


def enrich_exchange_requests(
    client: UserScopedClient,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich exchange request items with participant display names and skill names.

    Performs safe, bounded read-only queries against profiles and skills using the
    caller's authenticated user-scoped client. Never exposes sensitive fields.
    """
    if not items:
        return items

    user_ids = {
        str(r[k])
        for r in items
        for k in ("requester_user_id", "receiver_user_id")
        if r.get(k) is not None
    }
    skill_ids = {
        str(r[k])
        for r in items
        for k in ("offered_skill_id", "wanted_skill_id")
        if r.get(k) is not None
    }

    profile_names: dict[str, str] = {}
    if user_ids:
        try:
            p_resp = (
                client.table("profiles")
                .select("user_id, display_name")
                .in_("user_id", list(user_ids))
                .execute()
            )
            if p_resp and p_resp.data:
                for row in p_resp.data:
                    if "user_id" in row and "display_name" in row:
                        profile_names[str(row["user_id"])] = row["display_name"]
        except Exception:
            pass

    skill_names: dict[str, str] = {}
    if skill_ids:
        try:
            s_resp = (
                client.table("skills")
                .select("id, skill_name")
                .in_("id", list(skill_ids))
                .execute()
            )
            if s_resp and s_resp.data:
                for row in s_resp.data:
                    if "id" in row and "skill_name" in row:
                        skill_names[str(row["id"])] = row["skill_name"]
        except Exception:
            pass

    for r in items:
        req_uid = str(r["requester_user_id"]) if r.get("requester_user_id") else None
        rec_uid = str(r["receiver_user_id"]) if r.get("receiver_user_id") else None
        off_sid = str(r["offered_skill_id"]) if r.get("offered_skill_id") else None
        wan_sid = str(r["wanted_skill_id"]) if r.get("wanted_skill_id") else None

        r["requester_display_name"] = profile_names.get(req_uid) if req_uid else None
        r["receiver_display_name"] = profile_names.get(rec_uid) if rec_uid else None
        r["offered_skill_name"] = skill_names.get(off_sid) if off_sid else None
        r["wanted_skill_name"] = skill_names.get(wan_sid) if wan_sid else None

    return items
