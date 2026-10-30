"""Centralised error classes and PostgreSQL SQLSTATE to HTTP translation.

Database workflow functions and triggers in `supabase/migrations/` raise specific
SQLSTATE codes and identifier prefixes (for example `not_authenticated`,
`session_not_found`, `skill_in_use`, `review_already_exists`).

This module maps those database errors into safe, user-friendly HTTP responses
without exposing raw SQL statements, internal table names, or stack traces.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Structured application error with a safe HTTP status code and message."""

    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class DatabaseOperationError(Exception):
    """Wrapper for database/RPC errors carrying a SQLSTATE code and raw message."""

    def __init__(
        self,
        sqlstate: str | None = None,
        message: str | None = None,
        details: str | None = None,
    ) -> None:
        super().__init__(message or "Database operation failed")
        self.sqlstate = sqlstate
        self.raw_message = message or ""
        self.details = details


# Known (SQLSTATE, identifier_prefix) pairs raised by SkillSwap PL/pgSQL
# functions and triggers. Mapping each pair explicitly guarantees that only
# safe, allowlisted messages are returned to API callers.
_KNOWN_PREFIX_MAPPINGS: dict[tuple[str, str], tuple[int, str, str]] = {
    # 401 Unauthenticated
    ("42501", "not_authenticated"): (
        401,
        "not_authenticated",
        "Authentication is required to perform this action.",
    ),
    # 403 Forbidden
    ("42501", "not_permitted"): (
        403,
        "not_permitted",
        "You are not permitted to perform this action on this exchange.",
    ),
    ("42501", "review_not_permitted"): (
        403,
        "review_not_permitted",
        "Only a session participant may review the other participant.",
    ),
    # 404 Not Found
    ("P0002", "request_not_found"): (
        404,
        "request_not_found",
        "Exchange request not found.",
    ),
    ("P0002", "session_not_found"): (
        404,
        "session_not_found",
        "Exchange session not found.",
    ),
    # 409 Conflict (workflow state, immutability, and duplicate protections)
    ("P0001", "invalid_state"): (
        409,
        "invalid_state",
        "This action is not valid for the current status.",
    ),
    ("P0001", "invalid_transition"): (
        409,
        "invalid_transition",
        "This status transition is not allowed.",
    ),
    ("P0001", "skill_in_use"): (
        409,
        "skill_in_use",
        "This skill is part of an exchange request; deactivate it and create a new listing instead.",
    ),
    ("P0001", "skill_inactive"): (
        409,
        "skill_inactive",
        "A skill referenced by this request has been deactivated.",
    ),
    ("P0001", "proposed_time_passed"): (
        409,
        "proposed_time_passed",
        "The proposed session time has already passed; please request a new exchange.",
    ),
    ("P0001", "session_not_completed"): (
        409,
        "session_not_completed",
        "Reviews are only allowed after both participants confirm session completion.",
    ),
    ("23505", "review_already_exists"): (
        409,
        "review_already_exists",
        "You have already submitted a review for this session.",
    ),
    ("P0001", "skill_identity_immutable"): (
        409,
        "skill_identity_immutable",
        "The owner and type of an existing skill cannot be changed.",
    ),
    ("P0001", "request_fields_immutable"): (
        409,
        "request_fields_immutable",
        "Exchange request details cannot be modified after creation.",
    ),
    ("P0001", "session_fields_immutable"): (
        409,
        "session_fields_immutable",
        "Exchange session scheduling details cannot be modified.",
    ),
    ("P0001", "confirmation_immutable"): (
        409,
        "confirmation_immutable",
        "A recorded session confirmation cannot be changed.",
    ),
    # 422 Unprocessable Entity (input / domain validation errors)
    ("22023", "proposed_time_in_past"): (
        422,
        "proposed_time_in_past",
        "The proposed date and time must be in the future.",
    ),
    ("P0001", "invalid_offered_skill"): (
        422,
        "invalid_offered_skill",
        "The offered skill must be an active offered skill owned by the requester.",
    ),
    ("P0001", "invalid_wanted_skill"): (
        422,
        "invalid_wanted_skill",
        "The requested skill must be an active offered skill owned by the receiver.",
    ),
    ("P0001", "invalid_status"): (
        422,
        "invalid_status",
        "A new exchange request must start with pending status.",
    ),
    ("22023", "invalid_rating"): (
        422,
        "invalid_rating",
        "Rating must be an integer between 1 and 5.",
    ),
    ("22023", "invalid_comment"): (
        422,
        "invalid_comment",
        "Review comment must be at most 500 characters.",
    ),
}


def _extract_error_prefix(raw_message: str) -> str:
    """Extract the leading identifier token (before `:` or whitespace) from a message."""
    cleaned = raw_message.strip()
    if not cleaned:
        return ""
    head = cleaned.split(":", 1)[0].strip()
    if " " not in head:
        return head.lower()
    return ""


def translate_db_error(
    sqlstate: str | None,
    raw_message: str | None = None,
) -> AppError:
    """Translate a PostgreSQL SQLSTATE code and message into a safe `AppError`.

    Never returns raw database messages, table names, constraint definitions,
    or stack traces to the caller.
    """
    code = (sqlstate or "").strip().upper()
    msg = (raw_message or "").strip()
    prefix = _extract_error_prefix(msg)

    # 1. Match explicit (SQLSTATE, identifier_prefix) pairs first
    if (code, prefix) in _KNOWN_PREFIX_MAPPINGS:
        status_code, error_code, safe_message = _KNOWN_PREFIX_MAPPINGS[(code, prefix)]
        return AppError(
            status_code=status_code,
            error_code=error_code,
            message=safe_message,
        )

    # 2. Match known constraint names on unique violations (23505)
    if code == "23505":
        lowered = msg.lower()
        if "reviews_one_per_reviewer_per_session" in lowered:
            return AppError(
                status_code=409,
                error_code="review_already_exists",
                message="You have already submitted a review for this session.",
            )
        if "skills_unique_active_per_owner" in lowered:
            return AppError(
                status_code=409,
                error_code="duplicate_active_skill",
                message="You already have an active skill with this name and type.",
            )
        return AppError(
            status_code=409,
            error_code="conflict",
            message="A record with these details already exists.",
        )

    # 3. Fallback by standard PostgreSQL SQLSTATE category
    if code == "42501":
        return AppError(
            status_code=403,
            error_code="forbidden",
            message="You do not have permission to perform this action.",
        )

    if code == "P0002":
        return AppError(
            status_code=404,
            error_code="not_found",
            message="The requested resource was not found.",
        )

    if code == "P0001":
        return AppError(
            status_code=409,
            error_code="business_rule_violation",
            message="The operation could not be completed due to current state rules.",
        )

    if code in {"22023", "23514", "23502", "23503", "22P02"}:
        return AppError(
            status_code=422,
            error_code="invalid_input",
            message="The provided input failed validation.",
        )

    # 4. Unknown or internal database error: return generic 500 without leaking details
    return AppError(
        status_code=500,
        error_code="internal_error",
        message="An unexpected server error occurred.",
    )


def not_authenticated_error() -> AppError:
    """No usable credentials were supplied (HTTP 401)."""
    return AppError(
        status_code=401,
        error_code="not_authenticated",
        message="Authentication is required to perform this action.",
    )


def invalid_token_error() -> AppError:
    """The supplied access token is malformed, invalid or expired (HTTP 401)."""
    return AppError(
        status_code=401,
        error_code="invalid_token",
        message="The access token is invalid or has expired.",
    )


def auth_unavailable_error() -> AppError:
    """Authentication could not be checked right now (HTTP 503).

    Used for Supabase Auth outages, timeouts, rate limiting and server
    misconfiguration. It deliberately says nothing about the cause.
    """
    return AppError(
        status_code=503,
        error_code="auth_unavailable",
        message="Authentication is temporarily unavailable. Please try again later.",
    )


def _build_error_response(app_error: AppError) -> JSONResponse:
    """Format an `AppError` as a consistent JSON response."""
    # RFC 9110 requires every 401 to advertise how to authenticate.
    headers = {"WWW-Authenticate": "Bearer"} if app_error.status_code == 401 else None
    return JSONResponse(
        status_code=app_error.status_code,
        content={
            "detail": app_error.message,
            "error": {
                "code": app_error.error_code,
                "message": app_error.message,
            },
        },
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralised exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return _build_error_response(exc)

    @app.exception_handler(DatabaseOperationError)
    async def handle_db_operation_error(
        _request: Request, exc: DatabaseOperationError
    ) -> JSONResponse:
        mapped = translate_db_error(exc.sqlstate, exc.raw_message)
        return _build_error_response(mapped)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        _request: Request, _exc: Exception
    ) -> JSONResponse:
        safe_error = AppError(
            status_code=500,
            error_code="internal_error",
            message="An unexpected server error occurred.",
        )
        return _build_error_response(safe_error)
