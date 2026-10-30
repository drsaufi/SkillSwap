"""Pydantic schemas for post-exchange session reviews."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewCreate(BaseModel):
    """Payload for submitting a review for a completed exchange session."""

    model_config = ConfigDict(extra="forbid")

    rating: int
    comment: str = Field(default="")

    @field_validator("rating", mode="before")
    @classmethod
    def validate_rating(cls, value: Any) -> int:
        if value is None:
            raise ValueError("rating cannot be null.")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("rating must be an integer between 1 and 5.")
        if value < 1 or value > 5:
            raise ValueError("rating must be between 1 and 5.")
        return value

    @field_validator("comment", mode="before")
    @classmethod
    def validate_comment(cls, value: Any) -> str:
        if value is None:
            raise ValueError("comment cannot be null.")
        if not isinstance(value, str):
            raise ValueError("comment must be a string.")
        trimmed = value.strip()
        if len(trimmed) > 500:
            raise ValueError("comment cannot exceed 500 characters.")
        return trimmed


class ReviewResponse(BaseModel):
    """Public representation of a persisted session review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    session_id: UUID
    reviewer_user_id: UUID
    reviewee_user_id: UUID
    rating: int
    comment: str
    created_at: datetime
