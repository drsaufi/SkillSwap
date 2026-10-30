"""FastAPI application entrypoint and factory for SkillSwap."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.exchange_requests import router as exchange_requests_router
from app.api.routes.exchange_sessions import router as exchange_sessions_router
from app.api.routes.health import router as health_router
from app.api.routes.members import router as members_router
from app.api.routes.profiles import router as profiles_router
from app.api.routes.skills import router as skills_router
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
    application.include_router(profiles_router)
    application.include_router(skills_router)
    application.include_router(members_router)
    application.include_router(exchange_requests_router)
    application.include_router(exchange_sessions_router)

    return application


app = create_app()
