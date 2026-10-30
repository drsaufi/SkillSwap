"""Database repository for member dashboard queries using user-scoped Supabase client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from postgrest.exceptions import APIError

from app.core.errors import DatabaseOperationError
from app.core.supabase import UserScopedClient
from app.repositories.exchange_repo import EXCHANGE_SESSION_COLUMNS

REVIEWS_PAGE_SIZE = 500


def count_active_skills_by_type(
    client: UserScopedClient,
    user_id: UUID,
    skill_type: Literal["offered", "wanted"],
) -> int:
    """Count active skills owned by user_id of the given skill_type."""
    try:
        response = (
            client.table("skills")
            .select("id", count="exact")
            .eq("owner_user_id", str(user_id))
            .eq("skill_type", skill_type)
            .eq("is_active", True)
            .range(0, 0)
            .execute()
        )
        if response.count is not None:
            return response.count
        return len(response.data) if response.data is not None else 0
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def count_pending_requests_by_role(
    client: UserScopedClient,
    user_id: UUID,
    role: Literal["incoming", "outgoing"],
) -> int:
    """Count pending exchange requests for user_id by incoming or outgoing role."""
    col = "receiver_user_id" if role == "incoming" else "requester_user_id"
    try:
        response = (
            client.table("exchange_requests")
            .select("id", count="exact")
            .eq(col, str(user_id))
            .eq("status", "pending")
            .range(0, 0)
            .execute()
        )
        if response.count is not None:
            return response.count
        return len(response.data) if response.data is not None else 0
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def count_exchanges_by_status(
    client: UserScopedClient,
    user_id: UUID,
    status: Literal["accepted", "completed"],
) -> int:
    """Count exchange requests involving user_id with the specified status."""
    try:
        response = (
            client.table("exchange_requests")
            .select("id", count="exact")
            .or_(f"requester_user_id.eq.{user_id},receiver_user_id.eq.{user_id}")
            .eq("status", status)
            .range(0, 0)
            .execute()
        )
        if response.count is not None:
            return response.count
        return len(response.data) if response.data is not None else 0
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def select_received_review_ratings(
    client: UserScopedClient,
    user_id: UUID,
) -> list[int]:
    """Fetch all rating values from reviews where user_id is the reviewee."""
    ratings: list[int] = []
    offset = 0
    try:
        while True:
            response = (
                client.table("reviews")
                .select("id, rating", count="exact")
                .eq("reviewee_user_id", str(user_id))
                .order("created_at", desc=True)
                .order("id", desc=False)
                .range(offset, offset + REVIEWS_PAGE_SIZE - 1)
                .execute()
            )
            rows = response.data if response.data is not None else []
            if not rows:
                break

            ratings.extend(int(r["rating"]) for r in rows)
            offset += len(rows)

            total = response.count if response.count is not None else len(rows)
            if len(ratings) >= total or len(rows) < REVIEWS_PAGE_SIZE:
                break

        return ratings
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc


def select_upcoming_sessions(
    client: UserScopedClient,
    limit: int = 5,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch up to `limit` upcoming scheduled sessions (scheduled_datetime >= now) visible to caller."""
    current_time = now or datetime.now(timezone.utc)
    try:
        response = (
            client.table("exchange_sessions")
            .select(EXCHANGE_SESSION_COLUMNS)
            .eq("completion_status", "scheduled")
            .gte("scheduled_datetime", current_time.isoformat())
            .order("scheduled_datetime", desc=False)
            .order("id", desc=False)
            .range(0, limit - 1)
            .execute()
        )
        return response.data if response.data is not None else []
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc
