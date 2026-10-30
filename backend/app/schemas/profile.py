"""Pydantic schemas for SkillSwap member profiles."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileResponse(BaseModel):
    """Public member profile matching public.profiles columns."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    display_name: str
    bio: str
    interests: list[str]
    learning_preferences: str
    availability: str
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Payload for partial profile updates via PATCH /profile/me."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None)
    bio: str | None = Field(default=None)
    interests: list[str] | None = Field(default=None)
    learning_preferences: str | None = Field(default=None)
    availability: str | None = Field(default=None)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("display_name cannot be null.")
        trimmed = value.strip()
        if len(trimmed) < 2 or len(trimmed) > 60:
            raise ValueError(
                "display_name must be between 2 and 60 characters after trimming."
            )
        return trimmed

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("bio cannot be null.")
        if len(value) > 500:
            raise ValueError("bio cannot exceed 500 characters.")
        return value

    @field_validator("interests")
    @classmethod
    def validate_interests(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            raise ValueError("interests cannot be null.")
        if len(value) > 10:
            raise ValueError("interests cannot contain more than 10 entries.")
        sanitized: list[str] = []
        for item in value:
            if item is None or not isinstance(item, str):
                raise ValueError("Each interest must be a non-null string.")
            if len(item) > 40:
                raise ValueError("Each interest must be at most 40 characters.")
            trimmed = item.strip()
            if len(trimmed) < 1:
                raise ValueError("Interest entry cannot be blank or whitespace only.")
            if len(trimmed) > 40:
                raise ValueError(
                    "Each interest must be at most 40 characters after trimming."
                )
            sanitized.append(trimmed)
        return sanitized

    @field_validator("learning_preferences")
    @classmethod
    def validate_learning_preferences(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("learning_preferences cannot be null.")
        if len(value) > 300:
            raise ValueError("learning_preferences cannot exceed 300 characters.")
        return value

    @field_validator("availability")
    @classmethod
    def validate_availability(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("availability cannot be null.")
        if len(value) > 300:
            raise ValueError("availability cannot exceed 300 characters.")
        return value
