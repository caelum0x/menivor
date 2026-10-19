"""Async provider submissions must not duplicate possibly accepted work."""

from __future__ import annotations

import pytest

from app.domains.routing.providers.kling_fal import KlingError, KlingFalAdapter
from app.domains.routing.providers.luma_gen import LumaAdapter
from app.domains.routing.providers.minimax_gen import MinimaxAdapter
from app.domains.routing.providers.runway_gen import RunwayAdapter
from app.domains.routing.providers.suno_gen import SunoAdapter
from app.domains.routing.providers.veo_gen import VeoAdapter
from app.domains.routing.providers.wan_replicate import WanAdapter


class _Response:
    status_code = 503
    headers: dict[str, str] = {}
    text = "unavailable"

    @staticmethod
    def json() -> dict:
        return {"error": {"message": "unavailable"}}


class _Session:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return _Response()


class _TimeoutSession:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        import requests

        self.calls += 1
        raise requests.exceptions.Timeout("response lost")


@pytest.mark.parametrize(
    "factory",
    [
        lambda session: KlingFalAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: RunwayAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: VeoAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: LumaAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: MinimaxAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: WanAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
        lambda session: SunoAdapter(
            api_key="key", session=session, max_retries=4, sleep=lambda _s: None
        ),
    ],
    ids=["kling", "runway", "veo", "luma", "minimax", "wan", "suno"],
)
def test_submit_5xx_is_not_retried_and_reports_unknown_acceptance(factory):
    session = _Session()
    adapter = factory(session)

    with pytest.raises(KlingError) as error:
        adapter._call("POST", "https://provider.invalid/submit", json={})

    assert session.calls == 1
    assert error.value.retryable is True
    assert error.value.acceptance == "unknown"
    assert error.value.may_have_been_accepted is True


def test_poll_5xx_retains_bounded_retry_behavior():
    session = _Session()
    adapter = RunwayAdapter(
        api_key="key", session=session, max_retries=2, sleep=lambda _s: None
    )

    with pytest.raises(KlingError) as error:
        adapter._call("GET", "https://provider.invalid/task")

    assert session.calls == 3
    assert error.value.acceptance == "definitely_not_accepted"
    assert error.value.may_have_been_accepted is False


def test_submit_timeout_is_not_retried_and_reports_unknown_acceptance():
    session = _TimeoutSession()
    adapter = KlingFalAdapter(
        api_key="key", session=session, max_retries=4, sleep=lambda _s: None
    )

    with pytest.raises(KlingError) as error:
        adapter.submit(prompt="possibly accepted")

    assert session.calls == 1
    assert error.value.acceptance == "unknown"
