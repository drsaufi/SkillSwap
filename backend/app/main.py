"""FastAPI application entrypoint and factory for SkillSwap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the SkillSwap FastAPI application."""
    active_settings = settings or get_settings()

    application = FastAPI(
        title="SkillSwap API",
        description="Backend REST API for the SkillSwap peer-to-peer skill exchange platform.",
        version="0.1.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    register_exception_handlers(application)
    application.include_router(health_router)

    return application


app = create_app()
