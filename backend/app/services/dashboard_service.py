"""Business logic service for the member dashboard summary."""

from __future__ import annotations

from uuid import UUID

from app.core.supabase import UserScopedClient
from app.repositories import dashboard_repo
from app.schemas.dashboard import DashboardSummaryResponse
from app.schemas.exchange import ExchangeSessionResponse

UPCOMING_SESSIONS_LIMIT = 5


def get_dashboard_summary(
    db: UserScopedClient,
    user_id: UUID,
) -> DashboardSummaryResponse:
    """Compute real database-backed dashboard counts, average rating and upcoming sessions."""
    offered_count = dashboard_repo.count_active_skills_by_type(
        db, user_id, "offered"
    )
    wanted_count = dashboard_repo.count_active_skills_by_type(
        db, user_id, "wanted"
    )
    incoming_pending = dashboard_repo.count_pending_requests_by_role(
        db, user_id, "incoming"
    )
    outgoing_pending = dashboard_repo.count_pending_requests_by_role(
        db, user_id, "outgoing"
    )
    accepted_count = dashboard_repo.count_exchanges_by_status(
        db, user_id, "accepted"
    )
    completed_count = dashboard_repo.count_exchanges_by_status(
        db, user_id, "completed"
    )

    ratings = dashboard_repo.select_received_review_ratings(db, user_id)
    reviews_count = len(ratings)
    average_rating = (
        round(sum(ratings) / reviews_count, 2) if reviews_count > 0 else None
    )

    session_rows = dashboard_repo.select_upcoming_sessions(
        db, limit=UPCOMING_SESSIONS_LIMIT
    )
    upcoming_sessions = [
        ExchangeSessionResponse.model_validate(row) for row in session_rows
    ]

    return DashboardSummaryResponse(
        active_offered_skills_count=offered_count,
        active_wanted_skills_count=wanted_count,
        incoming_pending_requests_count=incoming_pending,
        outgoing_pending_requests_count=outgoing_pending,
        accepted_exchanges_count=accepted_count,
        completed_exchanges_count=completed_count,
        average_rating=average_rating,
        reviews_received_count=reviews_count,
        upcoming_sessions=upcoming_sessions,
    )
