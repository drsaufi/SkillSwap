"""Pydantic schemas for SkillSwap member directory."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.skill import SkillResponse


class MemberDetailResponse(BaseModel):
    """Public member detail view including active offered and wanted skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    display_name: str
    bio: str
    interests: list[str]
    learning_preferences: str
    availability: str
    created_at: datetime
    updated_at: datetime
    skills: list[SkillResponse]
