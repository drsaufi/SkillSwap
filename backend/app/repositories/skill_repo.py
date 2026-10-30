"""Database repository for public.skills using user-scoped Supabase client."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app.core.errors import DatabaseOperationError
from app.core.supabase import UserScopedClient

SKILL_COLUMNS = (
    "id, owner_user_id, skill_name, category, proficiency_level, "
    "skill_type, description, is_active, created_at, updated_at"
)

ALLOWED_INSERT_COLUMNS = frozenset(
    {
        "owner_user_id",
        "skill_name",
        "category",
        "proficiency_level",
        "skill_type",
        "description",
    }
)

ALLOWED_UPDATE_COLUMNS = frozenset(
    {"skill_name", "category", "proficiency_level", "description", "is_active"}
)


def select_skills(
    client: UserScopedClient,
    *,
    search: str | None = None,
    category: str | None = None,
    proficiency_level: str | None = None,
    skill_type: str | None = None,
    owner_user_id: UUID | None = None,
    is_active: bool | None = True,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Query skills with discovery filters, pagination and exact count."""
    try:
        query = client.table("skills").select(SKILL_COLUMNS, count="exact")

        if is_active is not None:
            query = query.eq("is_active", is_active)
        if category:
            query = query.eq("category", category)
        if proficiency_level:
            query = query.eq("proficiency_level", proficiency_level)
        if skill_type:
            query = query.eq("skill_type", skill_type)
        if owner_user_id:
            query = query.eq("owner_user_id", str(owner_user_id))
        if search:
            sanitized = search.strip()
            if sanitized:
                query = query.ilike("skill_name", f"%{sanitized}%")

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


def select_skill_by_id(
    client: UserScopedClient, skill_id: UUID
) -> dict[str, Any] | None:
    """Fetch a single skill record by primary key."""
    try:
        response = (
            client.table("skills")
            .select(SKILL_COLUMNS)
            .eq("id", str(skill_id))
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


def insert_skill(
    client: UserScopedClient, skill_data: dict[str, Any]
) -> dict[str, Any]:
    """Insert a new skill record and return the created row."""
    payload = {
        k: v for k, v in skill_data.items() if k in ALLOWED_INSERT_COLUMNS
    }
    try:
        response = (
            client.table("skills")
            .insert(payload)
            .select(SKILL_COLUMNS)
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


def update_skill(
    client: UserScopedClient, skill_id: UUID, updates: dict[str, Any]
) -> dict[str, Any] | None:
    """Update allowlisted fields of an existing skill and return the updated row."""
    payload = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_COLUMNS}
    if not payload:
        return select_skill_by_id(client, skill_id)

    try:
        response = (
            client.table("skills")
            .update(payload)
            .eq("id", str(skill_id))
            .select(SKILL_COLUMNS)
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
