"""Pydantic schemas for the AI Skill Match Assistant — Lite."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.skill import SkillCategory, SkillProficiencyLevel, SkillType


class AiSkillMatchRequest(BaseModel):
    """Optional empty request body for POST /ai/skill-matches."""

    model_config = ConfigDict(extra="forbid")


class AiMatchedSkillSummary(BaseModel):
    """Factual skill summary verified from database records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    skill_name: str
    category: SkillCategory
    proficiency_level: SkillProficiencyLevel
    skill_type: SkillType


class AiSkillMatchItem(BaseModel):
    """A single grounded AI skill match recommendation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    member_user_id: UUID
    display_name: str
    offered_skill_id: UUID
    offered_skill: AiMatchedSkillSummary
    matching_wanted_skill_id: UUID | None = None
    matching_wanted_skill: AiMatchedSkillSummary | None = None
    explanation: str


class AiSkillMatchListResponse(BaseModel):
    """Response schema for POST /ai/skill-matches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    matches: list[AiSkillMatchItem]
    candidate_count: int
