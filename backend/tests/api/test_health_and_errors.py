"""Offline unit and API tests for Step 3.4A (FastAPI foundation, health, and errors)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, ENV_FILE_PATH, Settings
from app.core.errors import AppError, DatabaseOperationError, translate_db_error
from app.main import app, create_app


def test_app_import_and_startup_succeeds() -> None:
    """Application factory and default app instance initialize cleanly."""
    assert app.title == "SkillSwap API"
    assert app.version == "0.1.0"


def test_health_endpoint_returns_200_and_expected_payload() -> None:
    """GET /health returns HTTP 200 and exact JSON body {'status': 'ok'}."""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_works_without_supabase_or_llm_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health succeeds when Supabase and LLM environment variables are empty."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    empty_settings = Settings(
        _env_file=None,
        SUPABASE_URL="",
        SUPABASE_PUBLISHABLE_KEY="",
        LLM_API_KEY="",
        LLM_MODEL="",
        CORS_ORIGINS="http://localhost:5173,https://skillswap.example.com",
    )
    isolated_app = create_app(settings=empty_settings)
    client = TestClient(isolated_app)

    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert empty_settings.cors_origins_list == [
        "http://localhost:5173",
        "https://skillswap.example.com",
    ]


@pytest.mark.parametrize(
    ("sqlstate", "raw_message", "expected_status", "expected_code"),
    [
        # 401 Unauthenticated
        ("42501", "not_authenticated", 401, "not_authenticated"),
        # 403 Forbidden (role / participant / table permission checks)
        (
            "42501",
            "not_permitted: only the receiver can accept a request",
            403,
            "not_permitted",
        ),
        (
            "42501",
            "review_not_permitted: reviewer must be a participant reviewing the other participant",
            403,
            "review_not_permitted",
        ),
        (
            "42501",
            "permission denied for table exchange_requests",
            403,
            "forbidden",
        ),
    ],
)
def test_auth_and_permission_errors_map_correctly(
    sqlstate: str,
    raw_message: str,
    expected_status: int,
    expected_code: str,
) -> None:
    """Authentication (401) and authorisation (403) SQLSTATE errors map accurately."""
    mapped = translate_db_error(sqlstate, raw_message)

    assert mapped.status_code == expected_status
    assert mapped.error_code == expected_code
    assert "exchange_requests" not in mapped.message


@pytest.mark.parametrize(
    ("sqlstate", "raw_message", "expected_code"),
    [
        ("P0002", "request_not_found", "request_not_found"),
        ("P0002", "session_not_found", "session_not_found"),
        ("P0002", "no_data_found", "not_found"),
    ],
)
def test_not_found_errors_map_to_404(
    sqlstate: str,
    raw_message: str,
    expected_code: str,
) -> None:
    """P0002 not-found errors map to HTTP 404."""
    mapped = translate_db_error(sqlstate, raw_message)

    assert mapped.status_code == 404
    assert mapped.error_code == expected_code


@pytest.mark.parametrize(
    ("sqlstate", "raw_message", "expected_code"),
    [
        (
            "P0001",
            "invalid_state: only a pending request can be accepted",
            "invalid_state",
        ),
        (
            "P0001",
            "invalid_transition: cannot change status from declined to accepted",
            "invalid_transition",
        ),
        (
            "P0001",
            "skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead",
            "skill_in_use",
        ),
        (
            "P0001",
            "skill_inactive: a skill in this request has been deactivated",
            "skill_inactive",
        ),
        (
            "P0001",
            "proposed_time_passed: the proposed time is in the past; ask for a new request",
            "proposed_time_passed",
        ),
        (
            "P0001",
            "session_not_completed: reviews are only allowed after both participants confirm",
            "session_not_completed",
        ),
        (
            "23505",
            "review_already_exists: you have already reviewed this session",
            "review_already_exists",
        ),
        (
            "23505",
            'duplicate key value violates unique constraint "reviews_one_per_reviewer_per_session"',
            "review_already_exists",
        ),
        (
            "23505",
            'duplicate key value violates unique constraint "skills_unique_active_per_owner"',
            "duplicate_active_skill",
        ),
    ],
)
def test_conflict_errors_map_to_409(
    sqlstate: str,
    raw_message: str,
    expected_code: str,
) -> None:
    """State-transition, in-use skill, and duplicate errors map to HTTP 409."""
    mapped = translate_db_error(sqlstate, raw_message)

    assert mapped.status_code == 409
    assert mapped.error_code == expected_code


@pytest.mark.parametrize(
    ("sqlstate", "raw_message", "expected_code"),
    [
        (
            "22023",
            "proposed_time_in_past: the proposed date and time must be in the future",
            "proposed_time_in_past",
        ),
        (
            "22023",
            "invalid_rating: rating must be between 1 and 5",
            "invalid_rating",
        ),
        (
            "22023",
            "invalid_comment: comment must be at most 500 characters",
            "invalid_comment",
        ),
        (
            "P0001",
            "invalid_offered_skill: must be an active offered skill owned by the requester",
            "invalid_offered_skill",
        ),
        (
            "P0001",
            "invalid_wanted_skill: must be an active offered skill owned by the receiver",
            "invalid_wanted_skill",
        ),
        (
            "23514",
            'new row for relation "reviews" violates check constraint "reviews_rating_range"',
            "invalid_input",
        ),
    ],
)
def test_invalid_input_errors_map_to_422(
    sqlstate: str,
    raw_message: str,
    expected_code: str,
) -> None:
    """Parameter validation and CHECK constraint errors map to HTTP 422."""
    mapped = translate_db_error(sqlstate, raw_message)

    assert mapped.status_code == 422
    assert mapped.error_code == expected_code


def test_unknown_internal_errors_do_not_expose_sensitive_details() -> None:
    """Unknown SQLSTATE codes and unexpected exceptions return a safe 500 response."""
    sensitive_sql_msg = (
        'relation "private.validate_review_insert" failed on SELECT * FROM auth.users'
    )
    mapped = translate_db_error("XX000", sensitive_sql_msg)

    assert mapped.status_code == 500
    assert mapped.error_code == "internal_error"
    assert mapped.message == "An unexpected server error occurred."
    assert "private" not in mapped.message
    assert "auth.users" not in mapped.message

    test_app = create_app()

    @test_app.get("/_test/db-error")
    def raise_db_error() -> None:
        raise DatabaseOperationError(sqlstate="42P01", message=sensitive_sql_msg)

    @test_app.get("/_test/app-error")
    def raise_app_error() -> None:
        raise AppError(
            status_code=403,
            error_code="not_permitted",
            message="You are not permitted to perform this action on this exchange.",
        )

    @test_app.get("/_test/unexpected-error")
    def raise_unexpected() -> None:
        raise RuntimeError("sensitive internal connection string or stack details")

    client = TestClient(test_app, raise_server_exceptions=False)

    db_resp = client.get("/_test/db-error")
    assert db_resp.status_code == 500
    assert db_resp.json() == {
        "detail": "An unexpected server error occurred.",
        "error": {
            "code": "internal_error",
            "message": "An unexpected server error occurred.",
        },
    }
    assert "auth.users" not in db_resp.text

    app_resp = client.get("/_test/app-error")
    assert app_resp.status_code == 403
    assert app_resp.json()["error"]["code"] == "not_permitted"

    unexpected_resp = client.get("/_test/unexpected-error")
    assert unexpected_resp.status_code == 500
    assert "sensitive internal" not in unexpected_resp.text


# ==============================================================================
# Configuration & CORS Validation Tests (Step 3.4A Revision 2)
# ==============================================================================


def test_env_file_path_is_anchored_to_backend_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The .env file path is anchored to backend/.env independent of working directory."""
    assert Settings.model_config["env_file"] == ENV_FILE_PATH
    assert ENV_FILE_PATH == BACKEND_DIR / ".env"
    assert BACKEND_DIR.name == "backend"

    # Even if working directory changes, model_config remains anchored to backend/.env
    monkeypatch.chdir(tmp_path)
    assert Settings.model_config["env_file"] == ENV_FILE_PATH


def test_cors_origins_accepts_valid_single_and_multiple_origins() -> None:
    """Valid localhost, IPv4, IPv6, and production HTTPS origins are parsed and preserved."""
    # Single localhost origin
    single = Settings(_env_file=None, CORS_ORIGINS="http://localhost:5173")
    assert single.cors_origins_list == ["http://localhost:5173"]

    # Localhost with IPv4 and alternate port
    ipv4 = Settings(_env_file=None, CORS_ORIGINS="http://127.0.0.1:3000")
    assert ipv4.cors_origins_list == ["http://127.0.0.1:3000"]

    # Production HTTPS domain
    prod = Settings(_env_file=None, CORS_ORIGINS="https://app.example.com")
    assert prod.cors_origins_list == ["https://app.example.com"]

    # IPv6 localhost origin
    ipv6 = Settings(_env_file=None, CORS_ORIGINS="http://[::1]:5173")
    assert ipv6.cors_origins_list == ["http://[::1]:5173"]

    # Multiple origins with surrounding whitespace
    multiple = Settings(
        _env_file=None,
        CORS_ORIGINS="  http://localhost:5173 , https://skillswap.example.com , http://127.0.0.1:8080 , http://[::1]:5173  ",
    )
    assert multiple.cors_origins_list == [
        "http://localhost:5173",
        "https://skillswap.example.com",
        "http://127.0.0.1:8080",
        "http://[::1]:5173",
    ]


@pytest.mark.parametrize("disallowed_origin", ["*", "null", "http://localhost:5173, *", "null, https://app.example.com"])
def test_cors_origins_rejects_wildcard_and_null(disallowed_origin: str) -> None:
    """Wildcards (*) and 'null' origins must be rejected for security."""
    with pytest.raises(ValidationError, match="Wildcard or null CORS origins are prohibited"):
        Settings(_env_file=None, CORS_ORIGINS=disallowed_origin)


@pytest.mark.parametrize(
    ("invalid_origin", "match_pattern"),
    [
        ("http://localhost:5173/", "trailing slash"),
        ("http://localhost:5173/api", "trailing slash"),
        ("http://localhost:5173?filter=true", "query string"),
        ("http://localhost:5173#section1", "URL fragment"),
        ("http://user:pass@localhost:5173", "embedded credentials"),
        ("http://@localhost:5173", "embedded credentials or user information"),
        ("http://localhost:0", "between 1 and 65535"),
        ("https://example.com:0", "between 1 and 65535"),
        ("http://bad host", "invalid hostname characters or whitespace"),
        ("http://localhost:99999", "Invalid port"),
        ("ftp://localhost:5173", "Must be 'http' or 'https'"),
        ("javascript:alert(1)", "Must be 'http' or 'https'"),
        ("", "cannot be empty"),
        ("   ", "cannot be empty"),
        ("http://localhost:5173, ", "empty origin entries"),
        ("not-a-valid-origin", "Must be 'http' or 'https'"),
    ],
)
def test_cors_origins_rejects_malformed_origins(
    invalid_origin: str,
    match_pattern: str,
) -> None:
    """Malformed origins containing paths, query strings, credentials, bad ports or bad hosts are rejected."""
    with pytest.raises(ValidationError, match=match_pattern):
        Settings(_env_file=None, CORS_ORIGINS=invalid_origin)


def test_cors_approved_and_unapproved_origins_via_http() -> None:
    """Approved origins receive CORS headers; unapproved origins do not."""
    custom_settings = Settings(
        _env_file=None,
        CORS_ORIGINS="http://localhost:5173, https://app.skillswap.local",
    )
    cors_app = create_app(settings=custom_settings)
    client = TestClient(cors_app)

    # 1. Unapproved origin simple request
    unapproved_resp = client.get(
        "/health",
        headers={"Origin": "https://malicious-site.example.com"},
    )
    assert unapproved_resp.status_code == 200
    assert "access-control-allow-origin" not in unapproved_resp.headers

    # 2. Unapproved origin preflight OPTIONS request
    unapproved_preflight = client.options(
        "/health",
        headers={
            "Origin": "https://malicious-site.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in unapproved_preflight.headers

    # 3. Approved origin simple request
    approved_resp = client.get(
        "/health",
        headers={"Origin": "https://app.skillswap.local"},
    )
    assert approved_resp.status_code == 200
    assert (
        approved_resp.headers.get("access-control-allow-origin")
        == "https://app.skillswap.local"
    )

    # 4. Approved origin preflight OPTIONS request
    approved_preflight = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert (
        approved_preflight.headers.get("access-control-allow-origin")
        == "http://localhost:5173"
    )
