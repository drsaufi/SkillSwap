"""Offline unit tests for exchange requests and sessions schemas, services, and repositories."""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.api.deps import AuthenticatedUser
from app.core.errors import AppError, DatabaseOperationError
from app.repositories import exchange_repo
from app.schemas.exchange import (
    ExchangeRequestCreate,
    ExchangeRequestListResponse,
    ExchangeRequestResponse,
    ExchangeSessionResponse,
)
from app.services import exchange_service

USER_A_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_B_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_C_ID = UUID("33333333-3333-4333-8333-333333333333")

OFFERED_SKILL_ID = UUID("44444444-4444-4444-8444-444444444444")
WANTED_SKILL_ID = UUID("55555555-5555-4555-8555-555555555555")
REQUEST_ID = UUID("66666666-6666-4666-8666-666666666666")
SESSION_ID = UUID("77777777-7777-4777-8777-777777777777")

NOW = datetime.now(timezone.utc)
FUTURE_TIME = NOW + timedelta(days=2)

SAMPLE_REQUEST_ROW: dict[str, Any] = {
    "id": str(REQUEST_ID),
    "requester_user_id": str(USER_A_ID),
    "receiver_user_id": str(USER_B_ID),
    "offered_skill_id": str(OFFERED_SKILL_ID),
    "wanted_skill_id": str(WANTED_SKILL_ID),
    "message": "Hi, I would love to swap skills with you!",
    "status": "pending",
    "proposed_datetime": FUTURE_TIME.isoformat(),
    "format": "online",
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}

SAMPLE_SESSION_ROW: dict[str, Any] = {
    "id": str(SESSION_ID),
    "request_id": str(REQUEST_ID),
    "scheduled_datetime": FUTURE_TIME.isoformat(),
    "completion_status": "scheduled",
    "requester_confirmed_at": None,
    "receiver_confirmed_at": None,
    "completed_at": None,
    "notes": "Discussed initial outline.",
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch):
    """Ensure no real DNS or network connections can occur."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise OSError("real network access is blocked in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "gethostbyname", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


class FakeUserScopedClient:
    """Mock UserScopedClient for unit tests."""


# ==============================================================================
# 1. Schema Unit Tests
# ==============================================================================


def test_exchange_request_create_valid() -> None:
    req = ExchangeRequestCreate(
        receiver_user_id=USER_B_ID,
        offered_skill_id=OFFERED_SKILL_ID,
        wanted_skill_id=WANTED_SKILL_ID,
        message="Valid message",
        proposed_datetime=FUTURE_TIME,
        format="online",
    )
    assert req.receiver_user_id == USER_B_ID
    assert req.message == "Valid message"
    assert req.format == "online"


def test_exchange_request_create_trims_message() -> None:
    req = ExchangeRequestCreate(
        receiver_user_id=USER_B_ID,
        offered_skill_id=OFFERED_SKILL_ID,
        wanted_skill_id=WANTED_SKILL_ID,
        message="   Trimmed message   ",
        proposed_datetime=FUTURE_TIME,
        format="in_person",
    )
    assert req.message == "Trimmed message"


@pytest.mark.parametrize("empty_msg", ["", "   "])
def test_exchange_request_create_rejects_empty_message(empty_msg: str) -> None:
    with pytest.raises(ValidationError) as exc:
        ExchangeRequestCreate(
            receiver_user_id=USER_B_ID,
            offered_skill_id=OFFERED_SKILL_ID,
            wanted_skill_id=WANTED_SKILL_ID,
            message=empty_msg,
            proposed_datetime=FUTURE_TIME,
            format="online",
        )
    assert "between 1 and 500 characters" in str(exc.value)


def test_exchange_request_create_rejects_long_message() -> None:
    with pytest.raises(ValidationError) as exc:
        ExchangeRequestCreate(
            receiver_user_id=USER_B_ID,
            offered_skill_id=OFFERED_SKILL_ID,
            wanted_skill_id=WANTED_SKILL_ID,
            message="A" * 501,
            proposed_datetime=FUTURE_TIME,
            format="online",
        )
    assert "between 1 and 500 characters" in str(exc.value)


def test_exchange_request_create_rejects_naive_datetime() -> None:
    naive_dt = datetime(2030, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError) as exc:
        ExchangeRequestCreate(
            receiver_user_id=USER_B_ID,
            offered_skill_id=OFFERED_SKILL_ID,
            wanted_skill_id=WANTED_SKILL_ID,
            message="Test",
            proposed_datetime=naive_dt,
            format="online",
        )
    assert "timezone-aware" in str(exc.value)


def test_exchange_request_create_rejects_past_datetime() -> None:
    past_dt = NOW - timedelta(minutes=10)
    with pytest.raises(ValidationError) as exc:
        ExchangeRequestCreate(
            receiver_user_id=USER_B_ID,
            offered_skill_id=OFFERED_SKILL_ID,
            wanted_skill_id=WANTED_SKILL_ID,
            message="Test",
            proposed_datetime=past_dt,
            format="online",
        )
    assert "in the future" in str(exc.value)


def test_exchange_request_create_rejects_invalid_format() -> None:
    with pytest.raises(ValidationError):
        ExchangeRequestCreate.model_validate(
            {
                "receiver_user_id": str(USER_B_ID),
                "offered_skill_id": str(OFFERED_SKILL_ID),
                "wanted_skill_id": str(WANTED_SKILL_ID),
                "message": "Test",
                "proposed_datetime": FUTURE_TIME.isoformat(),
                "format": "hybrid",
            }
        )


def test_exchange_request_create_rejects_forbidden_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        ExchangeRequestCreate.model_validate(
            {
                "receiver_user_id": str(USER_B_ID),
                "offered_skill_id": str(OFFERED_SKILL_ID),
                "wanted_skill_id": str(WANTED_SKILL_ID),
                "message": "Test",
                "proposed_datetime": FUTURE_TIME.isoformat(),
                "format": "online",
                "status": "accepted",
                "requester_user_id": str(USER_A_ID),
            }
        )
    assert "extra_forbidden" in str(exc.value)


def test_exchange_request_response_serialization() -> None:
    resp = ExchangeRequestResponse.model_validate(SAMPLE_REQUEST_ROW)
    assert resp.id == REQUEST_ID
    assert resp.status == "pending"
    assert resp.format == "online"


def test_exchange_session_response_serialization() -> None:
    resp = ExchangeSessionResponse.model_validate(SAMPLE_SESSION_ROW)
    assert resp.id == SESSION_ID
    assert resp.completion_status == "scheduled"
    assert resp.requester_confirmed_at is None


def test_exchange_request_list_response() -> None:
    resp = ExchangeRequestListResponse(
        items=[ExchangeRequestResponse.model_validate(SAMPLE_REQUEST_ROW)],
        total=1,
        limit=20,
        offset=0,
    )
    assert len(resp.items) == 1
    assert resp.total == 1


# ==============================================================================
# 2. Service Unit Tests
# ==============================================================================


def test_create_exchange_request_rejects_self_request() -> None:
    req_in = ExchangeRequestCreate(
        receiver_user_id=USER_A_ID,  # self request
        offered_skill_id=OFFERED_SKILL_ID,
        wanted_skill_id=WANTED_SKILL_ID,
        message="Self swap",
        proposed_datetime=FUTURE_TIME,
        format="online",
    )
    with pytest.raises(AppError) as exc_info:
        exchange_service.create_exchange_request(
            FakeUserScopedClient(), USER_A_ID, req_in  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "self_request_not_allowed"


def test_create_exchange_request_success(monkeypatch: pytest.MonkeyPatch) -> None:
    req_in = ExchangeRequestCreate(
        receiver_user_id=USER_B_ID,
        offered_skill_id=OFFERED_SKILL_ID,
        wanted_skill_id=WANTED_SKILL_ID,
        message="Let's swap",
        proposed_datetime=FUTURE_TIME,
        format="online",
    )
    captured_data: dict[str, Any] = {}

    def fake_insert(db: Any, data: dict[str, Any]) -> dict[str, Any]:
        nonlocal captured_data
        captured_data = data
        return SAMPLE_REQUEST_ROW

    monkeypatch.setattr(exchange_repo, "insert_exchange_request", fake_insert)

    res = exchange_service.create_exchange_request(
        FakeUserScopedClient(), USER_A_ID, req_in  # type: ignore[arg-type]
    )
    assert res.id == REQUEST_ID
    assert captured_data["requester_user_id"] == str(USER_A_ID)
    assert captured_data["receiver_user_id"] == str(USER_B_ID)
    assert "status" not in captured_data


def test_list_exchange_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_select(db: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        assert kwargs["user_id"] == USER_A_ID
        assert kwargs["role"] == "incoming"
        assert kwargs["status"] == "pending"
        return [SAMPLE_REQUEST_ROW], 1

    monkeypatch.setattr(exchange_repo, "select_exchange_requests", fake_select)

    res = exchange_service.list_exchange_requests(
        FakeUserScopedClient(),  # type: ignore[arg-type]
        USER_A_ID,
        role="incoming",
        status="pending",
        limit=10,
        offset=0,
    )
    assert res.total == 1
    assert len(res.items) == 1
    assert res.items[0].id == REQUEST_ID


def test_accept_exchange_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exchange_repo,
        "rpc_accept_exchange_request",
        lambda db, rid: SAMPLE_SESSION_ROW,
    )

    res = exchange_service.accept_exchange_request(
        FakeUserScopedClient(), USER_B_ID, REQUEST_ID  # type: ignore[arg-type]
    )
    assert res.id == SESSION_ID
    assert res.completion_status == "scheduled"


def test_decline_exchange_request(monkeypatch: pytest.MonkeyPatch) -> None:
    declined_row = dict(SAMPLE_REQUEST_ROW, status="declined")
    monkeypatch.setattr(
        exchange_repo,
        "rpc_decline_exchange_request",
        lambda db, rid: declined_row,
    )

    res = exchange_service.decline_exchange_request(
        FakeUserScopedClient(), USER_B_ID, REQUEST_ID  # type: ignore[arg-type]
    )
    assert res.id == REQUEST_ID
    assert res.status == "declined"


def test_cancel_exchange_request(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled_row = dict(SAMPLE_REQUEST_ROW, status="cancelled")
    monkeypatch.setattr(
        exchange_repo,
        "rpc_cancel_exchange_request",
        lambda db, rid: cancelled_row,
    )

    res = exchange_service.cancel_exchange_request(
        FakeUserScopedClient(), USER_A_ID, REQUEST_ID  # type: ignore[arg-type]
    )
    assert res.id == REQUEST_ID
    assert res.status == "cancelled"


def test_get_exchange_session_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exchange_repo,
        "select_exchange_session_by_id",
        lambda db, sid: SAMPLE_SESSION_ROW,
    )

    res = exchange_service.get_exchange_session(
        FakeUserScopedClient(), USER_A_ID, SESSION_ID  # type: ignore[arg-type]
    )
    assert res.id == SESSION_ID
    assert res.request_id == REQUEST_ID


def test_get_exchange_session_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        exchange_repo, "select_exchange_session_by_id", lambda db, sid: None
    )

    with pytest.raises(AppError) as exc_info:
        exchange_service.get_exchange_session(
            FakeUserScopedClient(), USER_A_ID, SESSION_ID  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.error_code == "session_not_found"


def test_confirm_exchange_session(monkeypatch: pytest.MonkeyPatch) -> None:
    confirmed_row = dict(
        SAMPLE_SESSION_ROW,
        requester_confirmed_at=NOW.isoformat(),
    )
    monkeypatch.setattr(
        exchange_repo,
        "rpc_confirm_exchange_session",
        lambda db, sid: confirmed_row,
    )

    res = exchange_service.confirm_exchange_session(
        FakeUserScopedClient(), USER_A_ID, SESSION_ID  # type: ignore[arg-type]
    )
    assert res.id == SESSION_ID
    assert res.requester_confirmed_at is not None


# ==============================================================================
# 3. Repository Unit Tests & Error Translation
# ==============================================================================


def test_extract_single_record() -> None:
    rec = {"a": 1}
    assert exchange_repo._extract_single_record(rec) == rec
    assert exchange_repo._extract_single_record([rec]) == rec

    with pytest.raises(DatabaseOperationError):
        exchange_repo._extract_single_record([])

    with pytest.raises(DatabaseOperationError):
        exchange_repo._extract_single_record("string")


def test_repo_catches_api_error_on_insert() -> None:
    class FailingQueryBuilder:
        def insert(self, *args: Any) -> FailingQueryBuilder:
            return self

        def select(self, *args: Any) -> FailingQueryBuilder:
            return self

        def single(self) -> FailingQueryBuilder:
            return self

        def execute(self) -> Any:
            raise APIError(
                {
                    "code": "22023",
                    "message": "proposed_time_in_past: in the past",
                    "details": None,
                    "hint": None,
                }
            )

    class FailingClient:
        def table(self, table_name: str) -> FailingQueryBuilder:
            return FailingQueryBuilder()

    with pytest.raises(DatabaseOperationError) as exc_info:
        exchange_repo.insert_exchange_request(
            FailingClient(), {"message": "Test"}  # type: ignore[arg-type]
        )
    assert exc_info.value.sqlstate == "22023"


def test_repo_catches_api_error_on_rpc() -> None:
    class FailingClient:
        def rpc(self, *args: Any, **kwargs: Any) -> Any:
            class RPCBuilder:
                def execute(self) -> Any:
                    raise APIError(
                        {
                            "code": "42501",
                            "message": "not_permitted: only receiver can accept",
                            "details": None,
                            "hint": None,
                        }
                    )

            return RPCBuilder()

    with pytest.raises(DatabaseOperationError) as exc_info:
        exchange_repo.rpc_accept_exchange_request(
            FailingClient(), REQUEST_ID  # type: ignore[arg-type]
        )
    assert exc_info.value.sqlstate == "42501"


def test_repo_catches_api_error_on_select_session() -> None:
    class FailingQueryBuilder:
        def select(self, *args: Any) -> FailingQueryBuilder:
            return self

        def eq(self, *args: Any) -> FailingQueryBuilder:
            return self

        def maybe_single(self) -> FailingQueryBuilder:
            return self

        def execute(self) -> Any:
            raise APIError(
                {
                    "code": "P0002",
                    "message": "session_not_found",
                    "details": None,
                    "hint": None,
                }
            )

    class FailingClient:
        def table(self, table_name: str) -> FailingQueryBuilder:
            return FailingQueryBuilder()

    with pytest.raises(DatabaseOperationError) as exc_info:
        exchange_repo.select_exchange_session_by_id(
            FailingClient(), SESSION_ID  # type: ignore[arg-type]
        )
    assert exc_info.value.sqlstate == "P0002"
