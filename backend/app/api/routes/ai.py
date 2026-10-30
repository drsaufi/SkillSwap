"""HTTP route for the AI Skill Match Assistant — Lite."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import CurrentUser, UserDb, get_app_settings
from app.core.config import Settings
from app.schemas.ai import AiSkillMatchListResponse, AiSkillMatchRequest
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/skill-matches", response_model=AiSkillMatchListResponse)
def generate_skill_matches(
    current_user: CurrentUser,
    db: UserDb,
    settings: Annotated[Settings, Depends(get_app_settings)],
    _body: AiSkillMatchRequest | None = Body(default=None),
) -> AiSkillMatchListResponse:
    """Return up to 3 grounded AI skill match recommendations for the authenticated member."""
    return ai_service.generate_skill_matches(db, current_user.user_id, settings)
