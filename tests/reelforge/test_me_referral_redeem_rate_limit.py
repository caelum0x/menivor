"""Rate limiting on ``POST /api/v1/me/referral/redeem``.

Unlike most "me" endpoints, redeeming a referral code grants real credits and
an unrecognized code falls through to
:func:`app.services.referrals._find_referrer_id`'s full-user-table scan
fallback — so this endpoint needed the same per-caller
:func:`app.services.ratelimit.enforce_rate_limit` guard every other
credit-granting / abuse-prone endpoint in this codebase already has.

These tests exercise the REAL fixed-window counting logic in
:mod:`app.services.ratelimit` (:func:`app.services.ratelimit.rate_limit` /
:func:`app.services.ratelimit.enforce_rate_limit`) wired through the real
router, so they fail if the guard is ever removed or its bucket stops being
keyed per-user. The module's lazily-built Redis client is forced to ``None``
here so the test is hermetic: this sandbox's "redis" hostname is sometimes
reachable and sometimes isn't (flaky DNS), and the module caches whatever
client it builds for the lifetime of the process, so a prior test — or a
prior ``pytest`` invocation hitting a real, stateful Redis — must never leak
into this one. Forcing the in-process fallback exercises the exact code path
production falls back to during a Redis outage, which is what the limiter is
designed to fail closed on anyway.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.controllers.v1 import me as me_mod
from app.models.exception import HttpException
from app.services import ratelimit as ratelimit_mod
from app.utils import utils


class _FakeUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


@contextmanager
def _fake_session():
    """``get_session`` replacement: no real DB is needed for this endpoint,
    since ``redeem_referral`` itself is monkeypatched below."""
    yield object()


@pytest.fixture(autouse=True)
def _force_in_process_rate_limiter(monkeypatch):
    """Make the rate limiter deterministic: no real Redis, no leaked state.

    ``_fresh_in_process_rate_limits`` (tests/reelforge/conftest.py) already
    clears the in-process fallback dict before every test; this additionally
    pins ``_get_client`` so ``rate_limit`` always takes the in-process branch
    instead of racing a real (and in this sandbox, inconsistently reachable)
    Redis instance keyed by the same bucket name across test runs.
    """
    monkeypatch.setattr(ratelimit_mod, "_get_client", lambda: None)


def _build_app(monkeypatch, *, user_id: str = "user-1", redeem_result: dict | None = None):
    """Mount ``me.router`` with everything redeem touches stubbed except the
    rate limiter, which is deliberately left real."""
    result = redeem_result or {
        "ok": False,
        "error": "invalid_code",
        "message": "referral code not recognized",
    }

    monkeypatch.setattr(me_mod, "_require_db", lambda request_id: None)
    monkeypatch.setattr(
        me_mod, "_resolve_user", lambda request, session, request_id: _FakeUser(user_id)
    )
    monkeypatch.setattr(me_mod, "get_session", _fake_session)
    # redeem_referral is imported lazily inside the handler
    # (``from app.services.referrals import redeem_referral``), so patch it on
    # the real module it is imported from.
    import app.services.referrals as referrals_mod

    monkeypatch.setattr(referrals_mod, "redeem_referral", lambda session, uid, code: result)

    app = FastAPI()
    app.include_router(me_mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        ),
    )
    return TestClient(app)


def _redeem(client: TestClient, code: str = "ABCDEFGH"):
    return client.post("/api/v1/me/referral/redeem", json={"code": code})


def test_redeem_allowed_under_the_limit(monkeypatch):
    client = _build_app(monkeypatch, user_id="allowed-under-limit")
    for _ in range(me_mod._REDEEM_RATE_LIMIT):
        resp = _redeem(client)
        # Each call reaches the (stubbed) service and gets its guarded 400,
        # never a 429 while under budget.
        assert resp.status_code == 400, resp.text


def test_redeem_rate_limited_after_limit_exceeded(monkeypatch):
    client = _build_app(monkeypatch, user_id="limit-exceeded")
    for _ in range(me_mod._REDEEM_RATE_LIMIT):
        resp = _redeem(client)
        assert resp.status_code == 400, resp.text

    # One more attempt within the same window must be rejected before ever
    # reaching redeem_referral (and therefore before the expensive
    # unknown-code fallback scan runs again).
    resp = _redeem(client)
    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert "rate limit" in (body.get("message") or "").lower()


def test_redeem_rate_limit_is_per_user_not_global(monkeypatch):
    """A second caller must not be punished by the first caller's attempts."""
    client_a = _build_app(monkeypatch, user_id="per-user-a")
    for _ in range(me_mod._REDEEM_RATE_LIMIT):
        assert _redeem(client_a).status_code == 400
    assert _redeem(client_a).status_code == 429

    client_b = _build_app(monkeypatch, user_id="per-user-b")
    resp = _redeem(client_b)
    assert resp.status_code == 400, (
        "a fresh user id must get a fresh rate-limit bucket, not inherit "
        "another caller's exhausted one"
    )


def test_redeem_success_path_still_works_under_the_limit(monkeypatch):
    """A real (mocked-ok) redemption still succeeds through the new guard."""
    ok_result = {
        "ok": True,
        "referrer_id": "referrer-1",
        "referee_id": "user-1",
        "referrer_grant": 10,
        "referee_grant": 5,
        "referee_balance": 5,
    }
    # notify_referral_earned is imported lazily from app.services.notifications
    # inside the handler; stub it there so a successful redemption never tries
    # to touch a real notifications backend.
    import app.services.notifications as notifications_mod

    monkeypatch.setattr(notifications_mod, "notify_referral_earned", lambda *a, **k: None)

    client = _build_app(monkeypatch, user_id="success-path", redeem_result=ok_result)
    resp = _redeem(client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["ok"] is True


@pytest.mark.parametrize("limit", [me_mod._REDEEM_RATE_LIMIT])
def test_rate_limit_constant_is_sane(limit):
    """Guard against a future edit silently disabling the limiter again."""
    assert 0 < limit <= 100
    assert me_mod._REDEEM_RATE_WINDOW_S > 0
