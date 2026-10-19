"""Shared production provider boundary used by the API and Prism."""

from __future__ import annotations

import pytest

from reelforge_provider_adapter.execution import (
    ProviderExecutionException,
    ProviderRequestV1,
    should_fail_over,
)

from app.domains.gateway.provider_execution import MediaProviderExecutor


class _Response:
    def __init__(self, body: dict, status_code: int = 200) -> None:
        self.status_code = status_code
        self._body = body
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> dict:
        return self._body


class _Session:
    def __init__(self, *responses: _Response) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, *, headers=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return self.responses.pop(0)


def _runway_request(cost_micros: int = 2_500_000) -> ProviderRequestV1:
    return ProviderRequestV1(
        provider_key="runway",
        model_ref="gen4_turbo",
        correlation_id="request-provider-contract",
        modality="video",
        prompt="a deliberate lateral camera move",
        duration_seconds=5,
        aspect_ratio="16:9",
        input_refs=("https://assets.example/frame.png",),
        parameters={
            "estimated_cost_micros": cost_micros,
            "cost_source": "catalog_estimate",
            "unit": "second",
            "quantity_units": 5,
            "price_version": "catalog-test-v1",
        },
    )


def test_runway_submit_and_poll_share_one_versioned_handle_and_exact_cost():
    session = _Session(
        _Response({"id": "runway-task-1"}),
        _Response(
            {
                "status": "SUCCEEDED",
                "output": ["https://cdn.example/output.mp4"],
            }
        ),
    )
    executor = MediaProviderExecutor(api_key="runway-test", session_http=session)

    submitted = executor.submit(_runway_request())
    assert submitted.state == "IN_QUEUE"
    assert submitted.handle.run_id == "runway-task-1"
    assert submitted.handle.model_ref == "gen4_turbo"
    assert submitted.cost.cost_micros == 0
    assert session.calls[0]["json"]["ratio"] == "1280:768"

    completed = executor.poll(submitted.handle)
    assert completed.state == "COMPLETED"
    assert completed.outputs[0].reference == "https://cdn.example/output.mp4"
    assert completed.cost.success is True
    assert completed.cost.cost_micros == 2_500_000
    assert completed.cost.price_version == "catalog-test-v1"


def test_terminal_provider_failure_is_non_billable_and_typed():
    session = _Session(
        _Response({"id": "runway-task-fail"}),
        _Response({"status": "FAILED", "failure": "content policy"}),
    )
    executor = MediaProviderExecutor(api_key="runway-test", session_http=session)
    submitted = executor.submit(_runway_request())

    failed = executor.poll(submitted.handle)
    assert failed.state == "FAILED"
    assert failed.cost.success is False
    assert failed.cost.cost_micros == 0
    assert failed.error is not None
    assert failed.error.acceptance == "accepted"
    assert "content policy" in failed.error.message


def test_definite_validation_failure_never_authorizes_fallback():
    executor = MediaProviderExecutor(api_key="runway-test", session_http=_Session())
    invalid = ProviderRequestV1(
        provider_key="runway",
        model_ref="gen4_turbo",
        correlation_id="request-no-frame",
        modality="video",
        prompt="missing required source frame",
        duration_seconds=5,
        aspect_ratio="9:16",
        parameters={"estimated_cost_micros": 1},
    )

    with pytest.raises(ProviderExecutionException) as caught:
        executor.submit(invalid)
    assert caught.value.error.category == "validation"
    assert caught.value.error.acceptance == "not_accepted"
    assert should_fail_over(caught.value.error) is False


def test_unknown_provider_fails_explicitly_instead_of_polling_forever():
    executor = MediaProviderExecutor(api_key="irrelevant", session_http=_Session())
    request = ProviderRequestV1(
        provider_key="removed-provider",
        model_ref="old-model",
        correlation_id="request-removed-provider",
        modality="video",
        prompt="x",
        duration_seconds=1,
        aspect_ratio="9:16",
        parameters={"estimated_cost_micros": 1},
    )

    with pytest.raises(ProviderExecutionException) as caught:
        executor.submit(request)
    assert caught.value.error.category == "validation"
    assert caught.value.error.acceptance == "not_accepted"

