"""Supabase client factories (publishable key only).

Two kinds of client are built here, both with the *publishable* key and never
with a service-role or secret key:

1. **Verification client** - used only to ask Supabase Auth "who owns this
   access token?" via ``auth.get_user(jwt)``. It holds no user state, so one
   instance per (URL, key) is cached and shared.
2. **User-scoped client** - a brand-new client for every authenticated request.
   It sends the caller's own JWT as ``Authorization: Bearer <jwt>`` on every
   PostgREST table query and RPC call, so PostgreSQL Row Level Security sees
   that user (``auth.uid()``) and keeps working. It is never cached or shared.

SDK facts this module relies on (supabase 2.33.0, checked in the installed
source, not from older examples):

* ``Client.create`` keeps an ``Authorization`` header passed in the options.
* ``Client`` registers an auth-state listener that rewrites the
  ``Authorization`` header on SIGNED_IN / TOKEN_REFRESHED / SIGNED_OUT. Our
  subclass turns that listener into a no-op so the verified JWT can never be
  replaced.
* When ``options.httpx_client`` is supplied, the SDK ignores its own timeout
  settings, so the timeout is configured on the ``httpx.Client`` we create.
* ``client.schema(...)`` builds a new PostgREST client that drops our
  ``httpx.Client`` (default 120 s timeout, never closed). It is disabled here;
  the app only uses the ``public`` schema.
* ``auth.get_user(jwt)`` does not touch session storage.

Resource management: every client owns one ``httpx.Client`` connection pool.
Call ``client.close()`` when finished. ``app.api.deps.get_user_db`` does this
automatically after each request. The cached verification client lives for the
process lifetime; ``reset_auth_verification_clients`` closes it (used by tests
and available for an application shutdown hook).

Nothing in this module touches the network at import time or when a client is
constructed. Network calls happen only when a query or ``get_user`` is run.
"""

from __future__ import annotations

import re
import threading
from typing import Any
from urllib.parse import urlsplit

import httpx
from supabase import Client, ClientOptions
from supabase_auth import SyncMemoryStorage

from app.core.config import Settings

PUBLISHABLE_KEY_PREFIX = "sb_publishable_"

# Short connect timeout so an outage fails fast; read timeout bounds a slow reply.
AUTH_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
DATABASE_TIMEOUT = httpx.Timeout(15.0, connect=3.0)

MAX_ACCESS_TOKEN_LENGTH = 4096
_FORBIDDEN_TOKEN_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


class SupabaseConfigurationError(RuntimeError):
    """Supabase settings are missing or unsafe. Messages never contain values."""


class _IsolatedClient(Client):
    """A Supabase ``Client`` whose Authorization header can never change."""

    def _listen_to_auth_events(self, event: Any, session: Any) -> None:
        # Deliberately ignore SIGNED_IN / TOKEN_REFRESHED / SIGNED_OUT. The base
        # class would swap the Authorization header for the event's session token.
        return None

    def schema(self, schema: str) -> Any:
        raise NotImplementedError(
            "Schema switching is disabled: the SDK would drop the managed HTTP "
            "client. SkillSwap only uses the public schema."
        )

    def close(self) -> None:
        """Close the HTTP connection pool owned by this client (safe to repeat)."""
        http_client = self.options.httpx_client
        if http_client is not None:
            http_client.close()

    def __repr__(self) -> str:
        # The default repr could expose headers (and therefore the JWT).
        return f"<{type(self).__name__}>"


class VerificationClient(_IsolatedClient):
    """Shared client used only for ``auth.get_user(jwt)`` token verification."""


class UserScopedClient(_IsolatedClient):
    """Per-request client that acts as one verified user. Never share it."""


def _validated_config(settings: Settings) -> tuple[str, str]:
    """Return (url, publishable_key) or raise ``SupabaseConfigurationError``."""
    url = (settings.SUPABASE_URL or "").strip()
    key = (settings.SUPABASE_PUBLISHABLE_KEY or "").strip()

    if not url or not key:
        raise SupabaseConfigurationError(
            "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be configured."
        )

    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SupabaseConfigurationError("SUPABASE_URL must be an http(s) URL.")

    # Only publishable keys are accepted. This also rejects sb_secret_ keys,
    # service_role JWTs and legacy anon JWTs.
    if not key.startswith(PUBLISHABLE_KEY_PREFIX):
        raise SupabaseConfigurationError(
            f"SUPABASE_PUBLISHABLE_KEY must be a publishable key ({PUBLISHABLE_KEY_PREFIX}...)."
        )
    return url, key


def _validate_access_token(access_token: str) -> str:
    if (
        not isinstance(access_token, str)
        or not access_token
        or len(access_token) > MAX_ACCESS_TOKEN_LENGTH
        or _FORBIDDEN_TOKEN_CHARS.search(access_token)
    ):
        raise ValueError("access_token is not a well-formed token.")
    return access_token


def _new_http_client(timeout: httpx.Timeout) -> httpx.Client:
    # No redirects: a redirect must never carry credentials somewhere else.
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _build_options(
    http_client: httpx.Client, authorization: str | None
) -> ClientOptions:
    headers = dict(ClientOptions().headers)  # SDK default X-Client-Info header
    if authorization is not None:
        headers["Authorization"] = authorization
    return ClientOptions(
        headers=headers,
        auto_refresh_token=False,  # no background refresh timers
        persist_session=False,  # nothing is stored; we never sign in
        storage=SyncMemoryStorage(),
        httpx_client=http_client,
    )


def _create(
    client_class: type[_IsolatedClient],
    settings: Settings,
    timeout: httpx.Timeout,
    authorization: str | None,
    http_client: httpx.Client | None,
) -> Any:
    url, key = _validated_config(settings)
    http = http_client or _new_http_client(timeout)
    try:
        return client_class.create(url, key, _build_options(http, authorization))
    except BaseException:
        http.close()
        raise


def create_auth_verification_client(
    settings: Settings, *, http_client: httpx.Client | None = None
) -> VerificationClient:
    """Build a new verification client. Use only ``client.auth.get_user(jwt)``.

    ``http_client`` is for tests (for example an ``httpx.MockTransport``).
    """
    return _create(VerificationClient, settings, AUTH_TIMEOUT, None, http_client)


def create_user_scoped_client(
    settings: Settings,
    access_token: str,
    *,
    http_client: httpx.Client | None = None,
) -> UserScopedClient:
    """Build a NEW client that runs table/RPC calls as the token's owner.

    Only pass a token that ``get_current_user`` has already verified. The
    caller owns the returned client and must call ``close()``. Do not call
    sign-in or session methods on it. ``http_client`` is for tests.
    """
    token = _validate_access_token(access_token)
    return _create(
        UserScopedClient, settings, DATABASE_TIMEOUT, f"Bearer {token}", http_client
    )


# --- Shared verification client cache (stateless, so safe to share) -----------
_verification_lock = threading.Lock()
_verification_clients: dict[tuple[str, str], VerificationClient] = {}


def get_auth_verification_client(settings: Settings) -> VerificationClient:
    """Return the shared verification client, creating it on first use."""
    cache_key = _validated_config(settings)
    with _verification_lock:
        client = _verification_clients.get(cache_key)
        if client is None:
            client = create_auth_verification_client(settings)
            _verification_clients[cache_key] = client
        return client


def reset_auth_verification_clients() -> None:
    """Close and forget all cached verification clients."""
    with _verification_lock:
        clients = list(_verification_clients.values())
        _verification_clients.clear()
    for client in clients:
        client.close()
