"""User-facing error text never carries request ids, headers or exception text.

The global ``HttpException`` handler rewrites ``message`` into a short human
sentence and returns the request id in its own ``request_id`` field; the raw
detail stays in the server log.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.testclient import TestClient

from app.asgi import exception_handler, validation_exception_handler
from app.core.observability import correlation_middleware
from app.core.public_errors import is_human_readable, public_message, status_message
from app.models.exception import HttpException

RID = "3f2a9c1e0b7d4e6fa1b2c3d4e5f60718"


@pytest.mark.parametrize(
    ("status", "raw", "expected"),
    [
        (401, f"{RID}: missing x-api-key header", "Please sign in to continue."),
        (401, f"{RID}: invalid bearer token: Signature has expired", "Please sign in to continue."),
        (503, f"{RID}: persistence layer is not available", status_message(503)),
        (500, f"{RID}: Traceback (most recent call last)", status_message(500)),
        (502, f"{RID}: payment provider returned no checkout url", status_message(502)),
        (404, f"{RID}: job not found", "Job not found"),
        (402, f"{RID}: insufficient credits: balance 0 < required 3", "Insufficient credits"),
        (402, f"{RID}: This format is not available yet (premium_voice)", "This format is not available yet"),
        (403, f"{RID}: checkout is not enabled for this launch phase",
         "Checkout is not enabled for this launch phase"),
        (400, f"{RID}: ValueError('bad input')", status_message(400)),
        (400, f"{RID}: image_key is required", status_message(400)),
        (400, "invalid token: https://example.test/x, Mozilla/5.0", status_message(400)),
        (409, "Your free reels are already unlocked. Go to Create to make a reel.",
         "Your free reels are already unlocked. Go to Create to make a reel."),
        (400, "", status_message(400)),
    ],
)
def test_public_message(status: int, raw: str, expected: str) -> None:
    assert public_message(status, raw, [RID]) == expected


@pytest.mark.parametrize(
    "raw",
    [
        f"{RID}: insufficient credits: balance=3, required=5",
        f"{RID}: internal-pilot credit allocation is exhausted",
        f"{RID}: request costs 12 credits, above the internal-pilot per-request cap",
    ],
)
def test_credit_402_copy_still_matches_mobile_top_up_patterns(raw: str) -> None:
    # apps/mobile GenerationErrorNotice CREDIT_PATTERNS (subset that survives).
    message = public_message(402, raw, [RID]).lower()
    assert "insufficient credits" in message or "not enough credits" in message
    assert "=" not in message


def test_pro_402_copy_still_matches_mobile_paywall_pattern() -> None:
    message = public_message(402, f"{RID}: an active Pro entitlement is required", [RID])
    assert "active pro entitlement is required" in message.lower()


def test_non_string_task_id_does_not_break_handler() -> None:
    assert public_message(404, "12345678: job not found", [12345678, None]) == "Job not found"


def test_curated_5xx_copy_is_kept() -> None:
    copy = "Card payments are not switched on yet. Try again in a few minutes."
    assert public_message(503, f"{RID}: {copy}", [RID]) == copy


def test_unknown_status_and_long_text_fall_back() -> None:
    assert public_message(418, "x" * 500) == status_message(418)
    assert not is_human_readable("line one\nline two")


def _client() -> TestClient:
    app = FastAPI()
    app.middleware("http")(correlation_middleware)
    app.add_exception_handler(HttpException, exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    class Body(BaseModel):
        name: str

    @app.get("/auth")
    def auth(request: Request):
        rid = request.state.correlation_id
        raise HttpException(task_id=rid, status_code=401, message=f"{rid}: missing x-api-key header")

    @app.get("/locked")
    def locked(request: Request):
        rid = request.state.correlation_id
        raise HttpException(
            task_id=rid,
            status_code=402,
            message=f"{rid}: This format is not available yet (premium_voice)",
            data={"code": "format_locked", "format": "avatar"},
        )

    @app.post("/body")
    def body(payload: Body):
        return {"ok": payload.name}

    return TestClient(app)


def test_handler_hides_detail_and_returns_request_id() -> None:
    resp = _client().get("/auth", headers={"X-Correlation-ID": RID})
    assert resp.status_code == 401
    body = resp.json()
    assert body["message"] == "Please sign in to continue."
    assert body["request_id"] == RID
    assert RID not in body["message"] and "x-api-key" not in resp.text


def test_handler_keeps_status_and_data_clients_parse() -> None:
    resp = _client().get("/locked", headers={"X-Correlation-ID": RID})
    assert resp.status_code == 402
    body = resp.json()
    assert body["data"] == {"code": "format_locked", "format": "avatar"}
    assert body["message"] == "This format is not available yet"
    assert body["status"] == 402


def test_validation_errors_are_human() -> None:
    resp = _client().post("/body", json={}, headers={"X-Correlation-ID": RID})
    assert resp.status_code == 400
    body = resp.json()
    assert RID not in body["message"]
    assert body["request_id"] == RID
    assert body["data"]  # field-level detail stays available for API clients
