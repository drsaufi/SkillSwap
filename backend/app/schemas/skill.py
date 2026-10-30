"""Pydantic schemas for SkillSwap skills."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SKILL_CATEGORIES = (
    "Technology",
    "Design",
    "Business",
    "Languages",
    "Music",
    "Arts and Crafts",
    "Health and Fitness",
    "Cooking",
    "Academics",
    "Other",
)

SkillCategory = Literal[
    "Technology",
    "Design",
    "Business",
    "Languages",
    "Music",
    "Arts and Crafts",
    "Health and Fitness",
    "Cooking",
    "Academics",
    "Other",
]

SkillProficiencyLevel = Literal["beginner", "intermediate", "advanced", "expert"]
SkillType = Literal["offered", "wanted"]


class SkillResponse(BaseModel):
    """Complete representation of a skill record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    owner_user_id: UUID
    skill_name: str
    category: str
    proficiency_level: str
    skill_type: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SkillListResponse(BaseModel):
    """Paginated list of skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[SkillResponse]
    total: int
    limit: int
    offset: int


class SkillCreate(BaseModel):
    """Payload for creating a new skill."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str
    category: SkillCategory
    proficiency_level: SkillProficiencyLevel
    skill_type: SkillType
    description: str = Field(default="")

    @field_validator("skill_name")
    @classmethod
    def validate_skill_name(cls, value: str) -> str:
        if value is None:
            raise ValueError("skill_name cannot be null.")
        trimmed = value.strip()
        if len(trimmed) < 2 or len(trimmed) > 80:
            raise ValueError(
                "skill_name must be between 2 and 80 characters after trimming."
            )
        return trimmed

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if value is None:
            raise ValueError("description cannot be null.")
        if len(value) > 500:
            raise ValueError("description cannot exceed 500 characters.")
        return value


class SkillUpdate(BaseModel):
    """Payload for updating an existing skill."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str | None = Field(default=None)
    category: SkillCategory | None = Field(default=None)
    proficiency_level: SkillProficiencyLevel | None = Field(default=None)
    description: str | None = Field(default=None)

    @field_validator("skill_name")
    @classmethod
    def validate_skill_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("skill_name cannot be null.")
        trimmed = value.strip()
        if len(trimmed) < 2 or len(trimmed) > 80:
            raise ValueError(
                "skill_name must be between 2 and 80 characters after trimming."
            )
        return trimmed

    @field_validator("category")
    @classmethod
    def validate_category(
        cls, value: SkillCategory | None
    ) -> SkillCategory | None:
        if value is None:
            raise ValueError("category cannot be null.")
        return value

    @field_validator("proficiency_level")
    @classmethod
    def validate_proficiency_level(
        cls, value: SkillProficiencyLevel | None
    ) -> SkillProficiencyLevel | None:
        if value is None:
            raise ValueError("proficiency_level cannot be null.")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("description cannot be null.")
        if len(value) > 500:
            raise ValueError("description cannot exceed 500 characters.")
        return value
