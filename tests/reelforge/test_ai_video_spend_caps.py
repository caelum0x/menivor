"""Unit tests for the owner-approved AI-video spend protection.

Covers the two new spend-protection surfaces added for the live Replicate
enablement (2026-09-15):

* ``app.domains.broll.spend_caps`` — per-user (2/day) + global (20/day) UTC-day
  Redis caps that FAIL CLOSED, hand back slots on rejection, and honor the
  ``AI_VIDEO_DAILY_CAP`` / ``AI_VIDEO_USER_DAILY_CAP`` env knobs.
* ``app.domains.broll.router._broll_ai_video_credits`` — AI clips are charged
  AI-video credits at 3x the provider cost (``AI_VIDEO_CLIP_COST_USD``).
* ``app.domains.broll.providers.replicate_wan`` — the hosted Wan provider:
  registry membership, enablement via ``REPLICATE_API_TOKEN``, the t2v happy
  path (submit -> poll -> download -> local mp4), and graceful ``None`` on
  provider failure.

No external I/O anywhere: Redis is an in-memory fake, the Replicate adapter is
a stub, and downloads write to tmp_path.
"""

from __future__ import annotations

import pytest

from app.domains.broll import spend_caps
from app.models.exception import HttpException


# =========================================================================== #
# Fake Redis (INCR/DECR/EXPIRE only — the full cap surface)
# =========================================================================== #
class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    def expire(self, key: str, ttl: int) -> None:
        self.ttls[key] = ttl


class _BrokenRedis:
    def incr(self, key: str) -> int:  # noqa: ARG002
        raise ConnectionError("redis down mid-call")


@pytest.fixture()
def fake_redis(monkeypatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(spend_caps, "_redis_client", lambda: client)
    return client


def _counts(client: _FakeRedis) -> tuple[int, int]:
    user = sum(v for k, v in client.values.items() if ":user:" in k)
    global_ = sum(v for k, v in client.values.items() if ":global:" in k)
    return user, global_


# =========================================================================== #
# Cap enforcement
# =========================================================================== #
def test_under_cap_consumes_one_user_and_global_slot(fake_redis):
    spend_caps.enforce_ai_video_daily_caps("u1", "req-1")
    assert _counts(fake_redis) == (1, 1)
    # Keys self-clean: both carry the 2-day TTL.
    assert set(fake_redis.ttls.values()) == {2 * 86400}


def test_user_daily_cap_trips_at_limit_and_returns_slot(fake_redis, monkeypatch):
    monkeypatch.setenv("AI_VIDEO_USER_DAILY_CAP", "2")
    spend_caps.enforce_ai_video_daily_caps("u1", "r")
    spend_caps.enforce_ai_video_daily_caps("u1", "r")
    with pytest.raises(HttpException) as exc:
        spend_caps.enforce_ai_video_daily_caps("u1", "r")
    assert exc.value.status_code == 429
    assert "limit" in exc.value.message
    # The rejected attempt consumed nothing.
    assert _counts(fake_redis) == (2, 2)


def test_global_daily_cap_trips_across_users_and_returns_both_slots(
    fake_redis, monkeypatch
):
    monkeypatch.setenv("AI_VIDEO_DAILY_CAP", "2")
    monkeypatch.setenv("AI_VIDEO_USER_DAILY_CAP", "5")
    spend_caps.enforce_ai_video_daily_caps("u1", "r")
    spend_caps.enforce_ai_video_daily_caps("u2", "r")
    with pytest.raises(HttpException) as exc:
        spend_caps.enforce_ai_video_daily_caps("u3", "r")
    assert exc.value.status_code == 429
    assert "capacity today" in exc.value.message
    # u3's tentative user+global increments were both handed back.
    assert _counts(fake_redis) == (2, 2)


def test_caps_fail_closed_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(spend_caps, "_redis_client", lambda: None)
    with pytest.raises(HttpException) as exc:
        spend_caps.enforce_ai_video_daily_caps("u1", "r")
    assert exc.value.status_code == 503


def test_caps_fail_closed_on_redis_error(monkeypatch):
    monkeypatch.setattr(spend_caps, "_redis_client", lambda: _BrokenRedis())
    with pytest.raises(HttpException) as exc:
        spend_caps.enforce_ai_video_daily_caps("u1", "r")
    assert exc.value.status_code == 503


def test_release_returns_one_slot(fake_redis):
    spend_caps.enforce_ai_video_daily_caps("u1", "r")
    spend_caps.release_ai_video_slot("u1")
    assert _counts(fake_redis) == (0, 0)


def test_release_never_raises(monkeypatch):
    monkeypatch.setattr(spend_caps, "_redis_client", lambda: _BrokenRedis())
    spend_caps.release_ai_video_slot("u1")  # must not raise


def test_cap_envs_are_read(monkeypatch):
    monkeypatch.setenv("AI_VIDEO_DAILY_CAP", "7")
    monkeypatch.setenv("AI_VIDEO_USER_DAILY_CAP", "3")
    assert spend_caps.global_daily_cap() == 7
    assert spend_caps.user_daily_cap() == 3
    monkeypatch.setenv("AI_VIDEO_DAILY_CAP", "not-a-number")
    assert spend_caps.global_daily_cap() == 20  # documented default


# =========================================================================== #
# AI-video credit price (3x the provider cost, never standard credits)
# =========================================================================== #
def test_broll_ai_video_credits_are_three_times_provider_cost(monkeypatch):
    from app.domains.broll import router as broll_router

    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "0.50")
    assert broll_router._broll_ai_video_credits() == 150  # $1.50 of AI-video credit
    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "")
    assert broll_router._broll_ai_video_credits() == 150  # documented default
    monkeypatch.setenv("AI_VIDEO_CLIP_COST_USD", "junk")
    assert broll_router._broll_ai_video_credits() == 150


# =========================================================================== #
# Replicate Wan provider (hosted t2v/i2v)
# =========================================================================== #
class _FakePrediction:
    def __init__(self) -> None:
        self.prediction_id = "pred-1"
        self.status = "starting"
        self.output_url = ""
        self.failure = ""
        self.raw = {"input": {"num_frames": 81}}

    @property
    def is_terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "canceled")


class _FakeAdapter:
    """Stubbed WanAdapter: one poll tick to success."""

    outcome = "succeeded"

    def __init__(self, *, model: str) -> None:
        self.model = model

    def submit(self, **kwargs):  # noqa: ANN003
        self._pred = _FakePrediction()
        self._kwargs = kwargs
        return self._pred

    def poll(self, pred):
        pred.status = type(self).outcome
        if pred.status == "succeeded":
            pred.output_url = "https://replicate.delivery/fake/out.mp4"
        else:
            pred.failure = "boom"
        return pred

    def cancel(self, pred) -> bool:  # noqa: ARG002
        return True


@pytest.fixture()
def replicate_provider(monkeypatch, tmp_path):
    import app.domains.broll.providers.replicate_wan as mod

    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test_token")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    import app.domains.routing.providers.wan_replicate as wan_mod

    _FakeAdapter.outcome = "succeeded"
    monkeypatch.setattr(wan_mod, "WanAdapter", _FakeAdapter)
    monkeypatch.setattr(
        mod.ReplicateWanProvider,
        "_download_clip",
        staticmethod(lambda _url: str(tmp_path / "clip.mp4")),
    )
    return mod.ReplicateWanProvider()


def test_replicate_provider_is_registered():
    from app.domains.broll import BROLL_GEN_PROVIDERS, get_broll_provider

    provider = get_broll_provider("replicate")
    assert provider.name == "replicate"
    assert "replicate" in BROLL_GEN_PROVIDERS


def test_replicate_enabled_only_with_token(monkeypatch):
    from app.domains.broll.providers.replicate_wan import ReplicateWanProvider

    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    assert ReplicateWanProvider().is_enabled() is False
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_x")
    assert ReplicateWanProvider().is_enabled() is True


def test_replicate_t2v_happy_path(replicate_provider):
    result = replicate_provider.generate_clip(
        "a slow aerial over a neon city", width=1080, height=1920, duration_s=5.0
    )
    assert result is not None
    assert result["clip_path"].endswith("clip.mp4")
    assert result["provider_job_id"] == "pred-1"
    assert result["duration"] == pytest.approx(81 / 16.0, abs=0.01)


def test_replicate_failure_returns_none(replicate_provider):
    _FakeAdapter.outcome = "failed"
    assert replicate_provider.generate_clip("prompt") is None


def test_replicate_i2v_requires_image(replicate_provider):
    assert replicate_provider.generate_clip("prompt", mode="i2v") is None


def test_replicate_disabled_returns_none(monkeypatch):
    from app.domains.broll.providers.replicate_wan import ReplicateWanProvider

    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    assert ReplicateWanProvider().generate_clip("prompt") is None
