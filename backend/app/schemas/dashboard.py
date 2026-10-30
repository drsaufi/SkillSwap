"""Pydantic schemas for the member dashboard summary."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.schemas.exchange import ExchangeSessionResponse


class DashboardSummaryResponse(BaseModel):
    """Summary metrics and upcoming sessions for the authenticated member's dashboard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_offered_skills_count: int
    active_wanted_skills_count: int
    incoming_pending_requests_count: int
    outgoing_pending_requests_count: int
    accepted_exchanges_count: int
    completed_exchanges_count: int
    average_rating: float | None = None
    reviews_received_count: int
    upcoming_sessions: list[ExchangeSessionResponse]
