"""Database access repository for public.profiles using user-scoped Supabase client."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app.core.errors import DatabaseOperationError
from app.core.supabase import UserScopedClient

PROFILE_COLUMNS = (
    "user_id, display_name, bio, interests, "
    "learning_preferences, availability, created_at, updated_at"
)

ALLOWED_UPDATE_COLUMNS = frozenset(
    {"display_name", "bio", "interests", "learning_preferences", "availability"}
)


def select_by_user_id(
    client: UserScopedClient, user_id: UUID
) -> dict[str, Any] | None:
    """Fetch profile for user_id using the authenticated user-scoped client."""
    try:
        response = (
            client.table("profiles")
            .select(PROFILE_COLUMNS)
            .eq("user_id", str(user_id))
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


def update_by_user_id(
    client: UserScopedClient, user_id: UUID, updates: dict[str, Any]
) -> dict[str, Any] | None:
    """Update allowlisted profile columns for user_id and return the updated row."""
    filtered_updates = {
        k: v for k, v in updates.items() if k in ALLOWED_UPDATE_COLUMNS
    }
    if not filtered_updates:
        return select_by_user_id(client, user_id)

    try:
        response = (
            client.table("profiles")
            .update(filtered_updates)
            .eq("user_id", str(user_id))
            .select(PROFILE_COLUMNS)
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
