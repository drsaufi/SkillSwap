"""Public health-check route (`GET /health`)."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Backend health check")
def get_health() -> dict[str, str]:
    """Return service health status without requiring database or AI credentials."""
    return {"status": "ok"}
