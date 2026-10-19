"""Server-to-server Prism client contract tests with no network."""

from __future__ import annotations

import httpx
import pytest

from app.domains.gateway.prism_client import PrismClient, PrismClientError


def test_generate_forwards_auth_correlation_and_hard_cost_cap():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "gen_1",
                "correlation_id": "gateway_job-1",
                "status": "queued",
                "model": "model-a",
                "provider": "provider-a",
                "modality": "video",
                "cost_micros": 400_000,
                "attempts": [],
            },
        )

    client = PrismClient(
        "http://prism.test",
        "secret",
        client=httpx.Client(
            base_url="http://prism.test", transport=httpx.MockTransport(handler)
        ),
    )
    result = client.generate(
        model="model-a",
        prompt="a prompt",
        modality="video",
        duration_seconds=5,
        aspect_ratio="16:9",
        image_url="",
        max_cost_micros=420_000,
        correlation_id="gateway_job-1",
    )

    assert result["id"] == "gen_1"
    request = seen[0]
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["X-Correlation-ID"] == "gateway_job-1"
    body = __import__("json").loads(request.content)
    assert body["routing"]["max_cost_micros"] == 420_000
    assert body["routing"]["fallback"] == "equivalent"
    assert body["image_url"] is None
    assert body["aspect_ratio"] == "16:9"


def test_submit_5xx_is_marked_ambiguous():
    client = PrismClient(
        "http://prism.test",
        "secret",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                503, json={"error": {"message": "upstream unavailable"}}
            )
        ),
    )

    with pytest.raises(PrismClientError) as error:
        client.generate(
            model="model-a",
            prompt="a prompt",
            modality="video",
            max_cost_micros=420_000,
            correlation_id="gateway_job-1",
        )
    assert error.value.may_have_been_accepted is True
    assert error.value.acceptance == "unknown"


def test_generation_forwards_the_same_correlation_id_on_recovery_lookup():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"id": "gen_1", "correlation_id": "gateway_job-1"}
        )

    client = PrismClient(
        "http://prism.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    client.generation("gen_1", correlation_id="gateway_job-1")
    assert seen[0].headers["X-Correlation-ID"] == "gateway_job-1"


def test_generation_by_correlation_recovers_without_another_submit():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "gen_recovered",
                "correlation_id": "gateway_lost-response",
                "status": "running",
            },
        )

    client = PrismClient(
        "http://prism.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    recovered = client.generation_by_correlation("gateway_lost-response")

    assert recovered["id"] == "gen_recovered"
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/v1/generation/by-correlation"
    assert seen[0].url.params["correlation_id"] == "gateway_lost-response"


def test_generation_maps_prism_error_without_leaking_response_body():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            404, json={"error": {"message": "generation not found"}}
        )
    )
    client = PrismClient(
        "http://prism.test",
        "secret",
        client=httpx.Client(base_url="http://prism.test", transport=transport),
    )

    with pytest.raises(PrismClientError) as error:
        client.generation("gen_missing")
    assert error.value.status_code == 404
    assert error.value.message == "generation not found"
