"""FastAPI authentication dependencies.

Flow for a protected route::

    Authorization header --get_bearer_token--> token string
        --get_current_user--> Supabase Auth ``auth.get_user(jwt)``
        --> AuthenticatedUser (verified user id + token)
        --get_user_db--> a fresh user-scoped Supabase client for this request

The caller's identity comes ONLY from Supabase Auth. Request bodies, query
strings and path parameters are never used to decide who the caller is.

All dependencies here are plain ``def`` functions, so FastAPI runs them in its
thread pool. The Supabase SDK is synchronous; running it inside an ``async def``
dependency would block the event loop.

Error mapping (the response never contains the token, keys or SDK messages):

* no / malformed / invalid / expired token ........ 401 + ``WWW-Authenticate: Bearer``
* Auth service down, timeout, 5xx, rate limit ...... 503
* missing/unsafe Supabase configuration ............ 503
* anything unexpected from the SDK ................. 503 (fails closed)
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidCredentialsError,
    AuthInvalidJwtError,
    AuthRetryableError,
    AuthSessionMissingError,
    UserDoesntExist,
)

from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    auth_unavailable_error,
    invalid_token_error,
    not_authenticated_error,
)
from app.core.supabase import (
    MAX_ACCESS_TOKEN_LENGTH,
    SupabaseConfigurationError,
    UserScopedClient,
    VerificationClient,
    create_user_scoped_client,
    get_auth_verification_client,
)
from app.schemas.auth import AuthenticatedUser

logger = logging.getLogger(__name__)

# Only used so the OpenAPI docs show an "Authorize" button. The real parsing is
# done in get_bearer_token so that we control every failure case.
_bearer_docs_scheme = HTTPBearer(auto_error=False, description="Supabase access token")

# A JWT is three base64url segments separated by dots.
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$")

# AuthApiError codes that mean "the service had a problem", not "bad token".
_UNAVAILABLE_ERROR_CODES = frozenset(
    {
        "over_request_rate_limit",
        "over_email_send_rate_limit",
        "over_sms_send_rate_limit",
        "request_timeout",
        "hook_timeout",
        "hook_timeout_after_retry",
        "unexpected_failure",
    }
)

# SDK errors that specifically mean "this token does not identify a user".
_TOKEN_REJECTED_ERRORS = (
    AuthInvalidJwtError,
    UserDoesntExist,
    AuthSessionMissingError,
    AuthInvalidCredentialsError,
)


def get_app_settings() -> Settings:
    """Return application settings (a dependency so tests can override it)."""
    return get_settings()


def get_bearer_token(
    request: Request,
    _docs: Annotated[
        HTTPAuthorizationCredentials | None, Security(_bearer_docs_scheme)
    ] = None,
) -> str:
    """Extract a well-formed bearer token or raise HTTP 401."""
    header = request.headers.get("authorization")
    if header is None or not header.strip():
        raise not_authenticated_error()

    # Exactly "Bearer <token>": one space, no extra whitespace anywhere.
    scheme, separator, token = header.partition(" ")
    if (
        scheme.lower() != "bearer"
        or not separator
        or not token
        or len(token) > MAX_ACCESS_TOKEN_LENGTH
        or not _JWT_SHAPE.match(token)
    ):
        raise invalid_token_error()
    return token


def get_auth_verifier(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> VerificationClient:
    """Return the shared Supabase Auth verification client."""
    try:
        return get_auth_verification_client(settings)
    except SupabaseConfigurationError:
        # Do not log the message or settings: keep configuration details private.
        logger.error("Supabase configuration is missing or invalid.")
        raise auth_unavailable_error() from None


def _classify_api_error(exc: AuthApiError) -> AppError:
    """Tell a rejected token (401) apart from a service problem (503)."""
    status = exc.status
    if (
        exc.code in _UNAVAILABLE_ERROR_CODES
        or status in (408, 429)
        or status >= 500
        or status < 400
    ):
        logger.warning("Supabase Auth unavailable (HTTP status %s).", status)
        return auth_unavailable_error()
    # Remaining 4xx (400/401/403/404...): bad_jwt, expired, banned, user gone.
    logger.info("Access token rejected by Supabase Auth (HTTP status %s).", status)
    return invalid_token_error()


def _verify_access_token(verifier: VerificationClient, token: str) -> UUID:
    """Ask Supabase Auth who owns ``token``. Raises ``AppError`` on any problem."""
    try:
        response = verifier.auth.get_user(token)
    except AuthRetryableError as exc:  # SDK-wrapped 502/503/504 and similar
        logger.warning("Supabase Auth unavailable (HTTP status %s).", exc.status)
        raise auth_unavailable_error() from None
    except AuthApiError as exc:
        raise _classify_api_error(exc) from None
    except httpx.HTTPError as exc:
        # Connection failures and timeouts are NOT wrapped by the SDK.
        logger.warning("Supabase Auth request failed: %s.", type(exc).__name__)
        raise auth_unavailable_error() from None
    except _TOKEN_REJECTED_ERRORS as exc:
        logger.info("Access token rejected: %s.", type(exc).__name__)
        raise invalid_token_error() from None
    except Exception as exc:
        # Everything else fails closed as "unavailable". This includes
        # AuthUnknownError, which the SDK raises when an error reply is not
        # JSON (typically a proxy/gateway answering instead of Supabase Auth)
        # and which discards the HTTP status, so it must not mean "bad token".
        logger.error("Unexpected token verification failure: %s.", type(exc).__name__)
        raise auth_unavailable_error() from None

    user = getattr(response, "user", None)
    if user is None:
        logger.info("Supabase Auth returned no user for the token.")
        raise invalid_token_error()

    try:
        return UUID(str(user.id))
    except (ValueError, AttributeError):
        logger.error("Supabase Auth returned an unusable user id.")
        raise auth_unavailable_error() from None


def get_current_user(
    token: Annotated[str, Depends(get_bearer_token)],
    verifier: Annotated[VerificationClient, Depends(get_auth_verifier)],
) -> AuthenticatedUser:
    """Verify the bearer token with Supabase Auth and return the caller."""
    user_id = _verify_access_token(verifier, token)
    return AuthenticatedUser(user_id=user_id, access_token=token)


def get_user_db(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Iterator[UserScopedClient]:
    """Yield a fresh user-scoped Supabase client for this request only.

    Created after authentication succeeded, never cached or shared, and its
    HTTP connection pool is closed when the request finishes.
    """
    try:
        client = create_user_scoped_client(
            settings, user.access_token.get_secret_value()
        )
    except SupabaseConfigurationError:
        logger.error("Supabase configuration is missing or invalid.")
        raise auth_unavailable_error() from None
    try:
        yield client
    finally:
        client.close()


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
UserDb = Annotated[UserScopedClient, Depends(get_user_db)]
