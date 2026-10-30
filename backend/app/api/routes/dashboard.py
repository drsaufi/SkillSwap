"""Dashboard routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserDb
from app.schemas.dashboard import DashboardSummaryResponse
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    current_user: CurrentUser,
    db: UserDb,
) -> DashboardSummaryResponse:
    """Return dashboard summary metrics and upcoming sessions for the authenticated member."""
    return dashboard_service.get_dashboard_summary(db, current_user.user_id)
