"""Authenticated user context produced by Supabase Auth token verification."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthenticatedUser(BaseModel):
    """The identity of the caller, as verified by Supabase Auth.

    Only two things are kept: the verified user id and the access token needed
    to make user-scoped database calls (so Row Level Security stays in force).
    No email address or other personal data is stored.

    This object is only ever built by `app.api.deps.get_current_user` after
    `auth.get_user(jwt)` succeeded. Never build it from request data.

    The token is a `SecretStr` that is also excluded from serialisation, so it
    does not appear in `repr()`, `str()`, `model_dump()`, JSON output or logs.
    Read it deliberately with `access_token.get_secret_value()`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    access_token: SecretStr = Field(repr=False, exclude=True)
