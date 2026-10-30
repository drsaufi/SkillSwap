"""Offline API tests for the authentication dependencies.

The real Supabase SDK runs against `httpx.MockTransport` fakes of Supabase Auth
(GoTrue) and PostgREST, so error mapping is tested against genuine SDK
behaviour. No real network access is possible (the autouse fixture records and
fails on any DNS lookup or socket connection). All data is fictional.
"""

import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import (
    AuthApiError,
    AuthInvalidJwtError,
    AuthSessionMissingError,
    UserDoesntExist,
)

from app.api import deps
from app.api.deps import CurrentUser, UserDb, get_app_settings, get_auth_verifier
from app.core import supabase as sb
from app.core.config import Settings
from app.main import create_app

SUPABASE_URL = "https://example-project.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_test_key_not_real"

USER_A_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER_B_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"
KNOWN_USERS = {TOKEN_A: USER_A_ID, TOKEN_B: USER_B_ID}

EXPIRED_TOKEN = "header-x.payload-expired.signature-x"
REVOKED_TOKEN = "header-y.payload-revoked.signature-y"
ALL_TOKENS = [TOKEN_A, TOKEN_B, EXPIRED_TOKEN, REVOKED_TOKEN]


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Record (and then fail on) any attempt at real DNS or socket connections."""
    attempts: list[str] = []

    def blocked(*args: object, **kwargs: object) -> None:
        attempts.append("network access attempted")
        raise OSError("real network access is blocked in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    yield
    assert attempts == []


@pytest.fixture(autouse=True)
def clean_verification_cache():
    sb.reset_auth_verification_clients()
    yield
    sb.reset_auth_verification_clients()


def fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL=SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
    )


def user_json(user_id: str) -> dict[str, Any]:
    return {
        "id": user_id,
        "aud": "authenticated",
        "role": "authenticated",
        "email": "member@example.test",  # present in the reply, must never be kept
        "app_metadata": {},
        "user_metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
    }


class FakeSupabase:
    """Fake Supabase Auth + PostgREST. `auth_behaviour` can simulate failures."""

    def __init__(self) -> None:
        self.auth_calls: list[httpx.Request] = []
        self.rest_calls: list[httpx.Request] = []
        self.auth_behaviour: Any = None  # callable(request) -> Response | raises
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/user":
            with self._lock:
                self.auth_calls.append(request)
            if self.auth_behaviour is not None:
                return self.auth_behaviour(request)
            token = request.headers["authorization"].removeprefix("Bearer ")
            if token in KNOWN_USERS:
                return httpx.Response(200, json=user_json(KNOWN_USERS[token]))
            if token == EXPIRED_TOKEN:
                return httpx.Response(
                    403,
                    json={"code": 403, "error_code": "bad_jwt", "msg": f"token is expired {token}"},
                )
            return httpx.Response(
                403,
                json={"code": 403, "error_code": "bad_jwt", "msg": f"invalid JWT {token}"},
            )
        if request.url.path.startswith("/rest/v1/"):
            with self._lock:
                self.rest_calls.append(request)
            return httpx.Response(
                200, json=[{"authorization": request.headers.get("authorization")}]
            )
        return httpx.Response(404, json={"msg": "not found"})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def build_client(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase, settings: Settings | None = None
) -> tuple[TestClient, list[sb.UserScopedClient]]:
    """App with test routes; auth and DB clients are wired to the fake backend."""
    active = settings or fake_settings()
    app = create_app(Settings(_env_file=None))
    created: list[sb.UserScopedClient] = []
    real_create = sb.create_user_scoped_client

    def create_with_fake(settings: Settings, token: str) -> sb.UserScopedClient:
        client = real_create(settings, token, http_client=fake.http_client())
        created.append(client)
        return client

    monkeypatch.setattr(deps, "create_user_scoped_client", create_with_fake)
    app.dependency_overrides[get_app_settings] = lambda: active
    app.dependency_overrides[get_auth_verifier] = lambda: sb.create_auth_verification_client(
        active, http_client=fake.http_client()
    )

    @app.get("/_test/me")
    def me(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.user_id)}

    @app.get("/_test/me-repr")
    def me_repr(user: CurrentUser) -> dict[str, str]:
        return {"repr": repr(user), "dump": str(user.model_dump())}

    @app.post("/_test/whoami")
    def whoami(user: CurrentUser, body: dict[str, Any]) -> dict[str, Any]:
        return {"user_id": str(user.user_id), "body_user_id": body.get("user_id")}

    @app.get("/_test/db")
    def db(db: UserDb) -> Any:
        return db.table("profiles").select("*").execute().data

    @app.post("/_test/rpc")
    def rpc(db: UserDb) -> Any:
        return db.rpc("accept_exchange_request", {"p_request_id": "x"}).execute().data

    return TestClient(app, raise_server_exceptions=False), created


@pytest.fixture
def fake() -> FakeSupabase:
    return FakeSupabase()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase) -> TestClient:
    test_client, _ = build_client(monkeypatch, fake)
    return test_client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_unauthorized(response: Any, code: str) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == code
    assert response.json()["detail"] == response.json()["error"]["message"]


def assert_unavailable(response: Any) -> None:
    assert response.status_code == 503
    assert "www-authenticate" not in response.headers
    assert response.json()["error"]["code"] == "auth_unavailable"


# --- Missing / malformed credentials (spec 1, 2, 6) -----------------------------


def test_missing_authorization_header_returns_401(
    client: TestClient, fake: FakeSupabase
) -> None:
    response = client.get("/_test/me")
    assert_unauthorized(response, "not_authenticated")
    assert fake.auth_calls == []  # Supabase is never contacted


@pytest.mark.parametrize(
    "header",
    [
        "Bearer",
        "Bearer ",
        "Bearer  ",
        "bearer",
        "Basic dXNlcjpwYXNz",
        "Token header-a.payload-a.signature-a",
        "Bearer header-a.payload-a.signature-a extra",
        "Bearer  header-a.payload-a.signature-a",
        "Bearer not-a-jwt",
        "Bearer a.b",
        "Bearer a.b.c.d",
        "Bearer " + "a" * 5000 + ".b.c",
        "Bearer héader.pay.load",
        "header-a.payload-a.signature-a",
    ],
)
def test_malformed_authorization_headers_return_401(
    client: TestClient, fake: FakeSupabase, header: str
) -> None:
    response = client.get(
        "/_test/me", headers={"Authorization": header.encode("latin-1")}
    )
    assert_unauthorized(response, "invalid_token")
    assert fake.auth_calls == []


def test_whitespace_only_header_is_not_authenticated(client: TestClient) -> None:
    response = client.get("/_test/me", headers={"Authorization": "   "})
    assert_unauthorized(response, "not_authenticated")


def test_bearer_scheme_is_case_insensitive(client: TestClient) -> None:
    response = client.get("/_test/me", headers={"Authorization": f"BEARER {TOKEN_A}"})
    assert response.status_code == 200


# --- Verification outcomes (spec 3, 4, 5) -------------------------------------


def test_valid_token_returns_verified_user_uuid(
    client: TestClient, fake: FakeSupabase
) -> None:
    response = client.get("/_test/me", headers=bearer(TOKEN_A))
    assert response.status_code == 200
    assert response.json() == {"user_id": USER_A_ID}

    # Verified through Supabase Auth GET /auth/v1/user with this exact token.
    (call,) = fake.auth_calls
    assert call.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert call.headers["apikey"] == PUBLISHABLE_KEY


def test_each_user_is_resolved_to_their_own_uuid(client: TestClient) -> None:
    assert client.get("/_test/me", headers=bearer(TOKEN_A)).json()["user_id"] == USER_A_ID
    assert client.get("/_test/me", headers=bearer(TOKEN_B)).json()["user_id"] == USER_B_ID


def test_invalid_jwt_returns_401(client: TestClient) -> None:
    response = client.get("/_test/me", headers=bearer(REVOKED_TOKEN))
    assert_unauthorized(response, "invalid_token")
    assert REVOKED_TOKEN not in response.text


def test_expired_jwt_returns_401(client: TestClient) -> None:
    response = client.get("/_test/me", headers=bearer(EXPIRED_TOKEN))
    assert_unauthorized(response, "invalid_token")
    assert "expired" not in response.text.lower() or "has expired" in response.text


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_rejection_statuses_from_auth_map_to_401(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase, status: int
) -> None:
    fake.auth_behaviour = lambda r: httpx.Response(
        status, json={"code": status, "error_code": "bad_jwt", "msg": "nope"}
    )
    test_client, _ = build_client(monkeypatch, fake)
    assert_unauthorized(test_client.get("/_test/me", headers=bearer(TOKEN_A)), "invalid_token")


def test_response_without_user_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_user = SimpleNamespace(auth=SimpleNamespace(get_user=lambda token: None))
    test_client, _ = build_client(monkeypatch, FakeSupabase())
    test_client.app.dependency_overrides[get_auth_verifier] = lambda: no_user
    assert_unauthorized(test_client.get("/_test/me", headers=bearer(TOKEN_A)), "invalid_token")


# --- Service problems (spec 7, 8) -----------------------------------------------


@pytest.mark.parametrize(
    "error_factory",
    [AuthInvalidJwtError, lambda: UserDoesntExist(), lambda: AuthSessionMissingError()],
    ids=["invalid-jwt", "user-missing", "session-missing"],
)
def test_token_specific_sdk_errors_map_to_401(
    monkeypatch: pytest.MonkeyPatch, error_factory: Any
) -> None:
    def reject(token: str) -> None:
        raise error_factory("bad") if error_factory is AuthInvalidJwtError else error_factory()

    test_client, _ = build_client(monkeypatch, FakeSupabase())
    test_client.app.dependency_overrides[get_auth_verifier] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=reject)
    )
    assert_unauthorized(test_client.get("/_test/me", headers=bearer(TOKEN_A)), "invalid_token")


def raising(exc: Exception):
    def behaviour(request: httpx.Request) -> httpx.Response:
        raise exc

    return behaviour


@pytest.mark.parametrize(
    "behaviour",
    [
        raising(httpx.ConnectError("connection refused")),
        raising(httpx.ConnectTimeout("connect timed out")),
        raising(httpx.ReadTimeout("read timed out")),
        raising(httpx.RemoteProtocolError("server disconnected")),
        lambda r: httpx.Response(500, json={"code": 500, "error_code": "unexpected_failure", "msg": "boom"}),
        lambda r: httpx.Response(502, text="Bad Gateway"),
        lambda r: httpx.Response(503, text="Service Unavailable"),
        lambda r: httpx.Response(504, text="Gateway Timeout"),
        lambda r: httpx.Response(
            429, json={"code": 429, "error_code": "over_request_rate_limit", "msg": "slow down"}
        ),
        lambda r: httpx.Response(429, text="Too Many Requests"),
        lambda r: httpx.Response(500, text="Internal Server Error"),
        lambda r: httpx.Response(403, text="<html>blocked by gateway</html>"),
        lambda r: httpx.Response(
            400, json={"code": 400, "error_code": "request_timeout", "msg": "timed out"}
        ),
    ],
    ids=[
        "connect-error",
        "connect-timeout",
        "read-timeout",
        "protocol-error",
        "http-500",
        "http-502",
        "http-503",
        "http-504",
        "rate-limit-json",
        "rate-limit-plain",
        "http-500-plain",
        "gateway-403-non-json",
        "request-timeout-code",
    ],
)
def test_service_failures_return_503_not_401(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase, behaviour: Any
) -> None:
    fake.auth_behaviour = behaviour
    test_client, _ = build_client(monkeypatch, fake)
    response = test_client.get("/_test/me", headers=bearer(TOKEN_A))
    assert_unavailable(response)
    assert TOKEN_A not in response.text


@pytest.mark.parametrize(
    "behaviour",
    [
        lambda r: httpx.Response(200, text="this is not json"),
        lambda r: httpx.Response(200, json={"unexpected": "shape"}),
        lambda r: httpx.Response(200, json=user_json("not-a-uuid")),
    ],
    ids=["garbage-body", "wrong-shape", "bad-user-id"],
)
def test_unexpected_sdk_replies_fail_closed_with_503(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase, behaviour: Any
) -> None:
    fake.auth_behaviour = behaviour
    test_client, _ = build_client(monkeypatch, fake)
    response = test_client.get("/_test/me", headers=bearer(TOKEN_A))
    assert_unavailable(response)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(f"internal detail leaking {TOKEN_A}"),
        AuthApiError(f"weird failure {TOKEN_A}", 418, None),
        ValueError("secret connection string postgres://user:pw@host/db"),
    ],
)
def test_unexpected_exceptions_from_the_sdk_are_handled_safely(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    def explode(token: str) -> None:
        raise error

    test_client, _ = build_client(monkeypatch, FakeSupabase())
    test_client.app.dependency_overrides[get_auth_verifier] = lambda: SimpleNamespace(
        auth=SimpleNamespace(get_user=explode)
    )
    caplog.set_level(logging.DEBUG)

    response = test_client.get("/_test/me", headers=bearer(TOKEN_A))

    assert response.status_code in (401, 503)
    assert "postgres://" not in response.text and "postgres://" not in caplog.text
    assert TOKEN_A not in response.text and TOKEN_A not in caplog.text
    assert "Traceback" not in response.text


def test_no_user_db_client_is_created_when_authentication_fails(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase
) -> None:
    test_client, created = build_client(monkeypatch, fake)
    for headers in ({}, bearer("bad.token.value"), bearer(REVOKED_TOKEN)):
        assert test_client.get("/_test/db", headers=headers).status_code == 401
    fake.auth_behaviour = raising(httpx.ConnectError("down"))
    assert test_client.get("/_test/db", headers=bearer(TOKEN_A)).status_code == 503
    assert created == [] and fake.rest_calls == []


# --- Configuration problems (spec 9) --------------------------------------------


def test_missing_supabase_configuration_returns_503_but_missing_header_stays_401(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase
) -> None:
    empty = Settings(_env_file=None, SUPABASE_URL="", SUPABASE_PUBLISHABLE_KEY="")
    test_client, _ = build_client(monkeypatch, fake, empty)
    # Use the real verifier dependency so the configuration check really runs.
    del test_client.app.dependency_overrides[get_auth_verifier]

    assert_unavailable(test_client.get("/_test/me", headers=bearer(TOKEN_A)))
    assert_unauthorized(test_client.get("/_test/me"), "not_authenticated")
    assert_unauthorized(test_client.get("/_test/me", headers={"Authorization": "Bearer x"}), "invalid_token")


def test_non_publishable_key_is_treated_as_unavailable_not_used(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase
) -> None:
    unsafe = Settings(
        _env_file=None,
        SUPABASE_URL=SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY="sb_secret_fake_administrative_key",
    )
    test_client, _ = build_client(monkeypatch, fake, unsafe)
    del test_client.app.dependency_overrides[get_auth_verifier]
    response = test_client.get("/_test/me", headers=bearer(TOKEN_A))
    assert_unavailable(response)
    assert "sb_secret_" not in response.text
    assert fake.auth_calls == []


# --- Database client behaviour (spec 11-13, 15) ------------------------------------


def test_user_db_dependency_forwards_the_users_jwt_to_table_and_rpc(
    client: TestClient, fake: FakeSupabase
) -> None:
    assert client.get("/_test/db", headers=bearer(TOKEN_A)).status_code == 200
    assert client.post("/_test/rpc", headers=bearer(TOKEN_A)).status_code == 200

    table_call, rpc_call = fake.rest_calls
    assert table_call.url.path == "/rest/v1/profiles"
    assert rpc_call.url.path == "/rest/v1/rpc/accept_exchange_request"
    for call in (table_call, rpc_call):
        assert call.headers["authorization"] == f"Bearer {TOKEN_A}"
        assert call.headers["apikey"] == PUBLISHABLE_KEY


def test_each_request_gets_its_own_closed_after_use_db_client(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase
) -> None:
    test_client, created = build_client(monkeypatch, fake)
    for _ in range(3):
        assert test_client.get("/_test/db", headers=bearer(TOKEN_A)).status_code == 200

    assert len(created) == 3
    assert len({id(c) for c in created}) == 3
    assert len({id(c.options.httpx_client) for c in created}) == 3
    assert all(c.options.httpx_client.is_closed for c in created)


def test_concurrent_requests_from_two_users_never_mix_tokens(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase
) -> None:
    test_client, _ = build_client(monkeypatch, fake)

    def call(token: str) -> tuple[str, str]:
        response = test_client.get("/_test/db", headers=bearer(token))
        assert response.status_code == 200
        return token, response.json()[0]["authorization"]

    jobs = [TOKEN_A, TOKEN_B] * 20
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, jobs))

    assert len(results) == 40
    for token, echoed in results:
        assert echoed == f"Bearer {token}"


# --- Identity source (spec 17) --------------------------------------------------


def test_identity_is_never_taken_from_the_request_body(client: TestClient) -> None:
    response = client.post(
        "/_test/whoami?user_id=" + USER_B_ID,
        headers=bearer(TOKEN_A),
        json={"user_id": USER_B_ID, "owner_id": USER_B_ID},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == USER_A_ID  # from Supabase Auth only
    assert response.json()["body_user_id"] == USER_B_ID  # merely echoed data


def test_body_user_id_does_not_authenticate_without_a_token(client: TestClient) -> None:
    response = client.post("/_test/whoami", json={"user_id": USER_A_ID})
    assert_unauthorized(response, "not_authenticated")


# --- Secrecy (spec 18) --------------------------------------------------------------


def test_tokens_never_appear_in_logs_or_responses(
    monkeypatch: pytest.MonkeyPatch, fake: FakeSupabase, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    test_client, _ = build_client(monkeypatch, fake)

    responses = [
        test_client.get("/_test/me", headers=bearer(TOKEN_A)),
        test_client.get("/_test/me-repr", headers=bearer(TOKEN_A)),
        test_client.get("/_test/db", headers=bearer(TOKEN_A)),
        test_client.get("/_test/me", headers=bearer(EXPIRED_TOKEN)),
        test_client.get("/_test/me", headers=bearer(REVOKED_TOKEN)),
        test_client.get("/_test/me", headers={"Authorization": f"Bearer {TOKEN_A} x"}),
    ]
    fake.auth_behaviour = raising(httpx.ReadTimeout(f"timeout for {TOKEN_B}"))
    responses.append(test_client.get("/_test/me", headers=bearer(TOKEN_B)))

    # /_test/db deliberately echoes the Authorization header the fake PostgREST
    # received (that is how forwarding is observed); every other response must
    # be token-free, and so must all logs.
    for response in responses:
        if response.request.url.path == "/_test/db":
            continue
        for token in ALL_TOKENS:
            assert token not in response.text
    for token in ALL_TOKENS:
        assert token not in caplog.text
    me_repr = responses[1].json()
    assert TOKEN_A not in me_repr["repr"] and TOKEN_A not in me_repr["dump"]
    assert PUBLISHABLE_KEY not in caplog.text
    assert all(PUBLISHABLE_KEY not in r.text for r in responses)


# --- Public routes and existing behaviour (spec 19) ---------------------------------


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer garbage"}, bearer(REVOKED_TOKEN)]
)
def test_health_remains_public(
    client: TestClient, fake: FakeSupabase, headers: dict[str, str]
) -> None:
    response = client.get("/health", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake.auth_calls == []


def test_health_works_with_no_supabase_configuration() -> None:
    app = create_app(Settings(_env_file=None))
    response = TestClient(app).get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_existing_database_error_401_now_advertises_bearer_scheme() -> None:
    from app.core.errors import DatabaseOperationError

    app = create_app(Settings(_env_file=None))

    @app.get("/_test/db-401")
    def raise_db_401() -> None:
        raise DatabaseOperationError(sqlstate="42501", message="not_authenticated")

    response = TestClient(app).get("/_test/db-401")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "not_authenticated"
