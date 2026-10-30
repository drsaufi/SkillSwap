"""Offline tests for the Supabase client factories and the auth user context.

Nothing here contacts Supabase. Requests are served by `httpx.MockTransport`
and every test fails if the code tries to resolve a host or open a socket.
All tokens, keys, ids and addresses are fictional.
"""

import json
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from app.core import supabase as sb
from app.core.config import Settings
from app.schemas.auth import AuthenticatedUser

PUBLISHABLE_KEY = "sb_publishable_test_key_not_real"
SUPABASE_URL = "https://example-project.supabase.co"
TOKEN_A = "header-a.payload-a.signature-a"
TOKEN_B = "header-b.payload-b.signature-b"


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


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        SUPABASE_URL=SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
    )


class Recorder:
    """Mock Supabase backend that records requests and echoes the auth header."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        return httpx.Response(
            200, json=[{"authorization": request.headers.get("authorization")}]
        )

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


# --- Configuration (spec items 9 and 10) --------------------------------------


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("", ""),
        (SUPABASE_URL, ""),
        ("", PUBLISHABLE_KEY),
        ("   ", "   "),
    ],
)
def test_missing_configuration_is_rejected(url: str, key: str) -> None:
    empty = Settings(_env_file=None, SUPABASE_URL=url, SUPABASE_PUBLISHABLE_KEY=key)
    with pytest.raises(sb.SupabaseConfigurationError):
        sb.create_user_scoped_client(empty, TOKEN_A)
    with pytest.raises(sb.SupabaseConfigurationError):
        sb.create_auth_verification_client(empty)
    with pytest.raises(sb.SupabaseConfigurationError):
        sb.get_auth_verification_client(empty)


@pytest.mark.parametrize(
    "bad_key",
    [
        "sb_secret_fake_administrative_key",
        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.fake",  # service_role-style JWT
        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.fake",  # legacy anon-style JWT
        "plain-string-key",
    ],
)
def test_only_publishable_keys_are_accepted(bad_key: str) -> None:
    bad = Settings(
        _env_file=None, SUPABASE_URL=SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY=bad_key
    )
    with pytest.raises(sb.SupabaseConfigurationError) as excinfo:
        sb.create_user_scoped_client(bad, TOKEN_A)
    assert bad_key not in str(excinfo.value)
    with pytest.raises(sb.SupabaseConfigurationError):
        sb.create_auth_verification_client(bad)


@pytest.mark.parametrize("bad_url", ["ftp://example.supabase.co", "not-a-url", "https://"])
def test_invalid_url_is_rejected(bad_url: str) -> None:
    bad = Settings(
        _env_file=None, SUPABASE_URL=bad_url, SUPABASE_PUBLISHABLE_KEY=PUBLISHABLE_KEY
    )
    with pytest.raises(sb.SupabaseConfigurationError):
        sb.create_user_scoped_client(bad, TOKEN_A)


@pytest.mark.parametrize(
    "bad_token", ["", "has space.in.it", "line\nbreak.in.token", "x" * 5000]
)
def test_malformed_tokens_are_refused_by_the_factory(
    settings: Settings, bad_token: str
) -> None:
    with pytest.raises(ValueError):
        sb.create_user_scoped_client(settings, bad_token)


def test_constructing_clients_makes_no_network_or_thread_activity(
    settings: Settings,
) -> None:
    threads_before = threading.active_count()
    user_client = sb.create_user_scoped_client(settings, TOKEN_A)
    verifier = sb.create_auth_verification_client(settings)
    assert threading.active_count() == threads_before
    user_client.close()
    verifier.close()  # the autouse fixture fails the test on any socket use


def test_sessions_are_not_persisted_and_refresh_is_off(settings: Settings) -> None:
    client = sb.create_user_scoped_client(settings, TOKEN_A)
    assert client.options.auto_refresh_token is False
    assert client.options.persist_session is False
    client.close()


def test_default_timeouts_are_configured_on_the_http_client(settings: Settings) -> None:
    client = sb.create_user_scoped_client(settings, TOKEN_A)
    verifier = sb.create_auth_verification_client(settings)
    assert client.options.httpx_client.timeout == sb.DATABASE_TIMEOUT
    assert verifier.options.httpx_client.timeout == sb.AUTH_TIMEOUT
    assert sb.DATABASE_TIMEOUT.connect <= 5 and sb.AUTH_TIMEOUT.connect <= 5
    client.close()
    verifier.close()


def test_schema_switching_is_disabled(settings: Settings) -> None:
    client = sb.create_user_scoped_client(settings, TOKEN_A)
    with pytest.raises(NotImplementedError):
        client.schema("private")
    client.close()


def test_client_repr_does_not_expose_the_token(settings: Settings) -> None:
    client = sb.create_user_scoped_client(settings, TOKEN_A)
    assert TOKEN_A not in repr(client) and TOKEN_A not in str(client)
    client.close()


def test_close_closes_the_http_pool_and_is_repeatable(settings: Settings) -> None:
    http = Recorder().http_client()
    client = sb.create_user_scoped_client(settings, TOKEN_A, http_client=http)
    client.close()
    client.close()
    assert http.is_closed


# --- Actual outgoing requests (spec items 10-13) -------------------------------


def test_table_request_sends_user_jwt_and_publishable_key(settings: Settings) -> None:
    backend = Recorder()
    client = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend.http_client()
    )

    client.table("profiles").select("user_id").execute()

    (request,) = backend.requests
    assert request.method == "GET"
    assert str(request.url).startswith(f"{SUPABASE_URL}/rest/v1/profiles")
    assert request.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert request.headers["apikey"] == PUBLISHABLE_KEY
    client.close()


def test_rpc_request_sends_user_jwt_and_publishable_key(settings: Settings) -> None:
    backend = Recorder()
    client = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend.http_client()
    )

    client.rpc(
        "accept_exchange_request",
        {"p_request_id": "00000000-0000-4000-8000-000000000001"},
    ).execute()

    (request,) = backend.requests
    assert request.method == "POST"
    assert request.url.path == "/rest/v1/rpc/accept_exchange_request"
    assert request.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert request.headers["apikey"] == PUBLISHABLE_KEY
    assert json.loads(request.content) == {
        "p_request_id": "00000000-0000-4000-8000-000000000001"
    }
    client.close()


def test_only_the_publishable_key_is_ever_sent(settings: Settings) -> None:
    backend = Recorder()
    client = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend.http_client()
    )
    client.table("skills").select("*").execute()
    client.rpc("cancel_exchange_request", {"p_request_id": "x"}).execute()

    for request in backend.requests:
        sent = " ".join(f"{k}={v}" for k, v in request.headers.items())
        assert "sb_secret_" not in sent and "service_role" not in sent
        assert request.headers["apikey"].startswith(sb.PUBLISHABLE_KEY_PREFIX)
        # The bearer is the user's token, never the project key.
        assert request.headers["authorization"] == f"Bearer {TOKEN_A}"
    client.close()


def test_verification_request_forwards_the_supplied_token(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "11111111-1111-4111-8111-111111111111",
                "aud": "authenticated",
                "app_metadata": {},
                "user_metadata": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    verifier = sb.create_auth_verification_client(settings, http_client=http)

    response = verifier.auth.get_user(TOKEN_A)

    assert str(response.user.id) == "11111111-1111-4111-8111-111111111111"
    (request,) = seen
    assert request.method == "GET" and request.url.path == "/auth/v1/user"
    assert request.headers["authorization"] == f"Bearer {TOKEN_A}"
    assert request.headers["apikey"] == PUBLISHABLE_KEY
    verifier.close()


# --- Isolation (spec items 14-16) ---------------------------------------------


def test_two_users_get_completely_separate_clients(settings: Settings) -> None:
    backend_a, backend_b = Recorder(), Recorder()
    client_a = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend_a.http_client()
    )
    client_b = sb.create_user_scoped_client(
        settings, TOKEN_B, http_client=backend_b.http_client()
    )

    assert client_a is not client_b
    assert client_a.options is not client_b.options
    assert client_a.options.headers is not client_b.options.headers
    assert client_a.options.httpx_client is not client_b.options.httpx_client
    assert client_a.postgrest is not client_b.postgrest

    client_a.table("profiles").select("*").execute()
    client_b.table("profiles").select("*").execute()
    assert backend_a.requests[0].headers["authorization"] == f"Bearer {TOKEN_A}"
    assert backend_b.requests[0].headers["authorization"] == f"Bearer {TOKEN_B}"
    client_a.close()
    client_b.close()


def test_default_factory_creates_a_new_http_pool_each_time(settings: Settings) -> None:
    first = sb.create_user_scoped_client(settings, TOKEN_A)
    second = sb.create_user_scoped_client(settings, TOKEN_A)
    assert first is not second
    assert first.options.httpx_client is not second.options.httpx_client
    first.close()
    second.close()


def test_interleaved_requests_never_mix_user_tokens(settings: Settings) -> None:
    backend = Recorder()
    client_a = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend.http_client()
    )
    client_b = sb.create_user_scoped_client(
        settings, TOKEN_B, http_client=backend.http_client()
    )

    for _ in range(5):  # strict A, B, B, A interleaving on one thread
        for client in (client_a, client_b, client_b, client_a):
            echoed = client.table("profiles").select("*").execute().data[0]
            expected = TOKEN_A if client is client_a else TOKEN_B
            assert echoed["authorization"] == f"Bearer {expected}"
    client_a.close()
    client_b.close()


def test_concurrent_threads_never_mix_user_tokens(settings: Settings) -> None:
    backend = Recorder()
    barrier = threading.Barrier(2)

    def worker(token: str) -> list[str]:
        client = sb.create_user_scoped_client(
            settings, token, http_client=backend.http_client()
        )
        barrier.wait()  # start both users at the same moment
        try:
            return [
                client.table("profiles").select("*").execute().data[0]["authorization"]
                for _ in range(25)
            ]
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results_a, results_b = pool.map(worker, (TOKEN_A, TOKEN_B))

    assert set(results_a) == {f"Bearer {TOKEN_A}"}
    assert set(results_b) == {f"Bearer {TOKEN_B}"}


def test_auth_state_events_cannot_overwrite_the_verified_jwt(
    settings: Settings,
) -> None:
    backend = Recorder()
    client = sb.create_user_scoped_client(
        settings, TOKEN_A, http_client=backend.http_client()
    )
    attacker_token = "attacker.session.token"

    for event in ("SIGNED_IN", "TOKEN_REFRESHED", "SIGNED_OUT"):
        client.auth._notify_all_subscribers(
            event, SimpleNamespace(access_token=attacker_token)
        )

    client.table("profiles").select("*").execute()
    client.rpc("create_review", {"p": 1}).execute()
    for request in backend.requests:
        assert request.headers["authorization"] == f"Bearer {TOKEN_A}"
        assert attacker_token not in request.headers["authorization"]
    assert client.options.headers["Authorization"] == f"Bearer {TOKEN_A}"
    client.close()


def test_stock_sdk_client_would_have_been_overwritten(settings: Settings) -> None:
    """Control: proves the previous test is meaningful for this SDK version."""
    from supabase import Client, ClientOptions

    stock = Client.create(
        SUPABASE_URL,
        PUBLISHABLE_KEY,
        ClientOptions(
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            persist_session=False,
            auto_refresh_token=False,
        ),
    )
    stock.auth._notify_all_subscribers(
        "SIGNED_IN", SimpleNamespace(access_token="attacker.session.token")
    )
    assert stock.options.headers["Authorization"] == "Bearer attacker.session.token"
    stock.options.httpx_client and stock.options.httpx_client.close()


# --- Verification client cache -------------------------------------------------


def test_verification_client_is_shared_and_can_be_reset(settings: Settings) -> None:
    first = sb.get_auth_verification_client(settings)
    assert sb.get_auth_verification_client(settings) is first
    sb.reset_auth_verification_clients()
    assert first.options.httpx_client.is_closed
    assert sb.get_auth_verification_client(settings) is not first


# --- AuthenticatedUser context ----------------------------------------------------


def test_authenticated_user_holds_only_id_and_token_and_hides_token() -> None:
    user = AuthenticatedUser(
        user_id=UUID("11111111-1111-4111-8111-111111111111"), access_token=TOKEN_A
    )

    assert set(AuthenticatedUser.model_fields) == {"user_id", "access_token"}
    assert user.access_token.get_secret_value() == TOKEN_A
    for text in (repr(user), str(user), json.dumps(user.model_dump(mode="json"))):
        assert TOKEN_A not in text
    assert "access_token" not in user.model_dump()
    assert TOKEN_A not in user.model_dump_json()


def test_authenticated_user_is_immutable_and_strict() -> None:
    user = AuthenticatedUser(
        user_id=UUID("11111111-1111-4111-8111-111111111111"), access_token=TOKEN_A
    )
    with pytest.raises(ValidationError):
        user.user_id = UUID("22222222-2222-4222-8222-222222222222")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        user.access_token = TOKEN_B  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        AuthenticatedUser(
            user_id="11111111-1111-4111-8111-111111111111",
            access_token=TOKEN_A,
            email="member@example.test",  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        AuthenticatedUser(user_id="not-a-uuid", access_token=TOKEN_A)
