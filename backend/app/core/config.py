"""Application configuration loaded from environment variables via Pydantic Settings.

No credentials or secrets are hardcoded here. All settings have safe defaults so
the application can boot, serve `/health`, and run offline unit/API tests without
requiring a live `.env` file or external network access.
"""

from functools import lru_cache
import ipaddress
from pathlib import Path
import re
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchored directory paths: ensure .env is always resolved from backend/
# regardless of current working directory when invoking uvicorn or python.
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = BACKEND_DIR / ".env"

# RFC 1123 compliant domain/hostname pattern (supports localhost, subdomains, etc.)
HOSTNAME_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)


def is_valid_hostname(host: str) -> bool:
    """Check if host is a valid RFC 1123 hostname or valid IPv4/IPv6 address."""
    if not host or any(char.isspace() for char in host):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return bool(HOSTNAME_PATTERN.match(host))


class Settings(BaseSettings):
    """Environment-driven settings matching `backend/.env.example`."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase (user-scoped publishable key only; never an elevated key) ---
    SUPABASE_URL: str = Field(default="")
    SUPABASE_PUBLISHABLE_KEY: str = Field(default="")

    # --- LLM provider (server-side only; optional at startup) ---
    LLM_API_KEY: str = Field(default="")
    LLM_MODEL: str = Field(default="")
    LLM_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=60)
    AI_MAX_CANDIDATES: int = Field(default=20, ge=1, le=50)

    # --- Application & CORS ---
    CORS_ORIGINS: str = Field(default="http://localhost:5173")

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """Validate explicit HTTP/HTTPS origins without wildcards, paths, or credentials."""
        if not isinstance(value, str):
            raise ValueError("CORS_ORIGINS must be a comma-separated string of origins.")

        trimmed = value.strip()
        if not trimmed:
            raise ValueError("CORS_ORIGINS cannot be empty or whitespace only.")

        raw_origins = [part.strip() for part in trimmed.split(",")]
        if not raw_origins or any(not o for o in raw_origins):
            raise ValueError("CORS_ORIGINS cannot contain empty origin entries.")

        validated: list[str] = []
        for origin in raw_origins:
            if origin in ("*", "null"):
                raise ValueError(
                    f"Wildcard or null CORS origins are prohibited for security: {origin!r}"
                )

            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    f"Invalid origin scheme '{parsed.scheme}'. Must be 'http' or 'https': {origin!r}"
                )

            if (
                parsed.username is not None
                or parsed.password is not None
                or "@" in parsed.netloc
            ):
                raise ValueError(
                    f"Origin cannot contain embedded credentials or user information: {origin!r}"
                )

            if not parsed.netloc or not parsed.hostname:
                raise ValueError(f"Origin must have a valid host/domain: {origin!r}")

            if not is_valid_hostname(parsed.hostname):
                raise ValueError(
                    f"Origin contains invalid hostname characters or whitespace: {origin!r}"
                )

            if parsed.path not in ("", None):
                raise ValueError(
                    f"Origin cannot contain a path or trailing slash: {origin!r}"
                )

            if parsed.query:
                raise ValueError(f"Origin cannot contain a query string: {origin!r}")

            if parsed.fragment:
                raise ValueError(f"Origin cannot contain a URL fragment: {origin!r}")

            try:
                port = parsed.port
            except ValueError as err:
                raise ValueError(f"Invalid port in origin {origin!r}: {err}") from err

            if port is not None and not (1 <= port <= 65535):
                raise ValueError(
                    f"Origin port must be between 1 and 65535: {origin!r}"
                )

            reconstructed = f"{parsed.scheme}://{parsed.netloc}"
            if origin != reconstructed:
                raise ValueError(f"Malformed origin format: {origin!r}")

            validated.append(origin)

        return ", ".join(validated)

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated `CORS_ORIGINS` into an explicit origin allowlist."""
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
