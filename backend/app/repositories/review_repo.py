"""Database repository for session reviews using user-scoped Supabase client."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app.core.errors import DatabaseOperationError
from app.core.supabase import UserScopedClient


def _extract_single_record(data: Any) -> dict[str, Any]:
    """Extract a single dict record from PostgREST RPC response data."""
    if isinstance(data, list):
        if not data:
            raise DatabaseOperationError(
                message="Empty response from review operation"
            )
        return data[0]
    if isinstance(data, dict):
        return data
    raise DatabaseOperationError(
        message="Unexpected response format from review operation"
    )


def rpc_create_review(
    client: UserScopedClient,
    *,
    session_id: UUID,
    rating: int,
    comment: str,
) -> dict[str, Any]:
    """Invoke public.create_review(p_session_id, p_rating, p_comment)."""
    try:
        response = client.rpc(
            "create_review",
            {
                "p_session_id": str(session_id),
                "p_rating": rating,
                "p_comment": comment,
            },
        ).execute()
        return _extract_single_record(response.data)
    except APIError as exc:
        raise DatabaseOperationError(
            sqlstate=str(exc.code) if exc.code is not None else None,
            message=exc.message,
            details=exc.details,
        ) from exc
