"""Pydantic schemas for exchange requests and exchange sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequestStatus = Literal[
    "pending", "accepted", "declined", "cancelled", "completed"
]
RequestFormat = Literal["online", "in_person"]
SessionCompletionStatus = Literal["scheduled", "completed", "cancelled"]
RequestRole = Literal["incoming", "outgoing"]


class ExchangeRequestCreate(BaseModel):
    """Payload for submitting a new skill exchange request."""

    model_config = ConfigDict(extra="forbid")

    receiver_user_id: UUID
    offered_skill_id: UUID
    wanted_skill_id: UUID
    message: str
    proposed_datetime: datetime
    format: RequestFormat

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if value is None:
            raise ValueError("message cannot be null.")
        trimmed = value.strip()
        if len(trimmed) < 1 or len(trimmed) > 500:
            raise ValueError(
                "message must be between 1 and 500 characters after trimming."
            )
        return trimmed

    @field_validator("proposed_datetime")
    @classmethod
    def validate_proposed_datetime(cls, value: datetime) -> datetime:
        if value is None:
            raise ValueError("proposed_datetime cannot be null.")
        if value.tzinfo is None:
            raise ValueError("proposed_datetime must be timezone-aware.")
        if value <= datetime.now(timezone.utc):
            raise ValueError("proposed_datetime must be in the future.")
        return value


class ExchangeRequestResponse(BaseModel):
    """Public representation of an exchange request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    requester_user_id: UUID
    receiver_user_id: UUID
    offered_skill_id: UUID
    wanted_skill_id: UUID
    message: str
    status: RequestStatus
    proposed_datetime: datetime
    format: RequestFormat
    created_at: datetime
    updated_at: datetime
    requester_display_name: str | None = None
    receiver_display_name: str | None = None
    offered_skill_name: str | None = None
    wanted_skill_name: str | None = None


class ExchangeRequestListResponse(BaseModel):
    """Paginated collection of exchange requests."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: list[ExchangeRequestResponse]
    total: int
    limit: int
    offset: int


class ExchangeSessionResponse(BaseModel):
    """Public representation of an exchange session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    request_id: UUID
    scheduled_datetime: datetime
    completion_status: SessionCompletionStatus
    requester_confirmed_at: datetime | None = None
    receiver_confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime
