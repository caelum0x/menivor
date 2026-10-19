"""Deterministic tests for the versioned provider execution contract."""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from reelforge_provider_adapter import (
    EXECUTION_SCHEMA_V1,
    HANDLE_SCHEMA_V1,
    RESULT_SCHEMA_V1,
    ProviderCostV1,
    ProviderExecutionErrorV1,
    ProviderExecutionException,
    ProviderExecutorRegistry,
    ProviderHandleV1,
    ProviderOutputV1,
    ProviderRequestV1,
    ProviderResultV1,
    decode_legacy_execution,
    should_fail_over,
    validate_output_reference,
)

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden" / "execution-v1.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(_GOLDEN.read_text())


def _handle(state: str = "IN_QUEUE", **changes) -> ProviderHandleV1:
    values = {
        "provider_key": "runway",
        "model_ref": "runwayml/gen-4",
        "run_id": "run_123",
        "state": state,
    }
    values.update(changes)
    return ProviderHandleV1(**values)


def _error(**changes) -> ProviderExecutionErrorV1:
    values = {
        "phase": "submit",
        "category": "capacity",
        "retryable": True,
        "acceptance": "not_accepted",
        "message": "provider is at capacity",
    }
    values.update(changes)
    return ProviderExecutionErrorV1(**values)


def test_schema_ids_are_pinned():
    assert EXECUTION_SCHEMA_V1 == "menivor.provider-execution/v1"
    assert HANDLE_SCHEMA_V1 == "menivor.provider-handle/v1"
    assert RESULT_SCHEMA_V1 == "menivor.provider-result/v1"


def test_request_reproduces_golden_and_round_trips(golden):
    request = ProviderRequestV1.from_dict(golden["request"])
    assert request.to_dict() == golden["request"]
    assert ProviderRequestV1.from_dict(request.to_dict()) == request


def test_completed_result_reproduces_golden_and_round_trips(golden):
    result = ProviderResultV1.from_dict(golden["completed"])
    assert result.to_dict() == golden["completed"]
    assert result.state == "COMPLETED"
    assert result.is_terminal
    assert ProviderResultV1.from_dict(result.to_dict()) == result


def test_handle_preserves_nested_opaque_json_without_aliasing_input():
    original = {"cursor": {"page": 2}, "flags": [True, None, "x"]}
    handle = _handle(opaque=original)
    original["cursor"]["page"] = 99
    assert handle.opaque == {"cursor": {"page": 2}, "flags": [True, None, "x"]}
    assert ProviderHandleV1.from_dict(handle.to_dict()).opaque == handle.opaque


@pytest.mark.parametrize(
    "opaque",
    [
        {"bad": object()},
        {1: "non-string-key"},
        {"tuple": ("not", "json")},
        {"nan": float("nan")},
        {"infinity": float("inf")},
    ],
)
def test_handle_rejects_non_json_or_non_finite_opaque_values(opaque):
    with pytest.raises(ValueError, match="JSON"):
        _handle(opaque=opaque)


@pytest.mark.parametrize("state", ["queued", "DONE", "", " completed "])
def test_handle_rejects_noncanonical_state(state):
    with pytest.raises(ValueError, match="normalized state"):
        _handle(state)


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "relative/output.mp4",
        "file:///tmp/output.mp4",
        "data:text/plain,secret",
        "javascript:alert(1)",
        "https://user:password@example.com/output.mp4",
        " https://cdn.example/output.mp4",
    ],
)
def test_output_reference_rejects_unsafe_or_ambiguous_values(reference):
    with pytest.raises(ValueError):
        validate_output_reference(reference)


def test_output_reference_accepts_absolute_http_and_https():
    assert validate_output_reference("https://cdn.example/a.mp4") == "https://cdn.example/a.mp4"
    assert (
        validate_output_reference("http://127.0.0.1:8080/test.png")
        == "http://127.0.0.1:8080/test.png"
    )


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg", "image/webp"])
def test_output_reference_accepts_bounded_inline_images(media_type):
    payload = base64.b64encode(b"deterministic-image-bytes").decode("ascii")
    reference = f"data:{media_type};base64,{payload}"
    assert validate_output_reference(reference) == reference
    assert ProviderOutputV1(reference, "image").reference == reference


@pytest.mark.parametrize(
    "reference",
    [
        "data:text/plain;base64,aGVsbG8=",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "data:image/png,not-base64",
        "data:image/png;base64,",
        "data:image/png;base64,%%%%",
        "data:image/png;base64,YQ====",
        "data:image/png;base64,Y Q==",
    ],
)
def test_output_reference_rejects_arbitrary_or_malformed_inline_data(reference):
    with pytest.raises(ValueError):
        validate_output_reference(reference)


def test_inline_image_enforces_decoded_size_limit(monkeypatch):
    import reelforge_provider_adapter.execution as execution

    monkeypatch.setattr(execution, "MAX_INLINE_IMAGE_BYTES", 2)
    payload = base64.b64encode(b"123").decode("ascii")
    with pytest.raises(ValueError, match="exceeds 16 MiB"):
        execution.validate_output_reference(f"data:image/png;base64,{payload}")


def test_inline_data_is_only_valid_for_image_output_kind():
    payload = base64.b64encode(b"image").decode("ascii")
    with pytest.raises(ValueError, match="only for image"):
        ProviderOutputV1(f"data:image/png;base64,{payload}", "file")


def test_cost_is_success_only():
    assert ProviderCostV1.not_chargeable().to_dict()["cost_micros"] == 0
    with pytest.raises(ValueError, match="non-success cost"):
        ProviderCostV1(False, 1, source="provider_reported")
    with pytest.raises(ValueError, match="non-success cost"):
        ProviderCostV1(False, 0, source="catalog_estimate")
    with pytest.raises(ValueError, match="declare its source"):
        ProviderCostV1(True, 1)
    with pytest.raises(ValueError, match="integer"):
        ProviderCostV1(True, True, source="provider_reported")


def test_completed_requires_output_and_successful_cost():
    cost = ProviderCostV1(True, 0, source="free")
    with pytest.raises(ValueError, match="at least one output"):
        ProviderResultV1(_handle("COMPLETED"), cost)
    with pytest.raises(ValueError, match="successful cost"):
        ProviderResultV1(
            _handle("COMPLETED"),
            ProviderCostV1.not_chargeable(),
            (ProviderOutputV1("https://cdn.example/out.mp4", "video"),),
        )


def test_completed_rejects_error_and_failed_rejects_output_or_billable_cost():
    output = ProviderOutputV1("https://cdn.example/out.mp4", "video")
    success_cost = ProviderCostV1(True, 5, source="provider_reported")
    with pytest.raises(ValueError, match="must not contain an error"):
        ProviderResultV1(_handle("COMPLETED"), success_cost, (output,), _error())
    with pytest.raises(ValueError, match="must not contain outputs"):
        ProviderResultV1(_handle("FAILED"), ProviderCostV1.not_chargeable(), (output,), _error())
    with pytest.raises(ValueError, match="must not carry billable"):
        ProviderResultV1(_handle("FAILED"), success_cost, (), _error())


def test_failed_and_cancelled_require_typed_error():
    for state in ("FAILED", "CANCELLED"):
        with pytest.raises(ValueError, match="typed error"):
            ProviderResultV1(_handle(state), ProviderCostV1.not_chargeable())


def test_inflight_result_rejects_output_error_and_billable_cost():
    output = ProviderOutputV1("https://cdn.example/out.mp4", "video")
    with pytest.raises(ValueError, match="in-flight"):
        ProviderResultV1(_handle(), ProviderCostV1.not_chargeable(), (output,))
    with pytest.raises(ValueError, match="in-flight"):
        ProviderResultV1(_handle(), ProviderCostV1.not_chargeable(), error=_error())
    with pytest.raises(ValueError, match="billable"):
        ProviderResultV1(_handle(), ProviderCostV1(True, 2, source="catalog_estimate"))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, True),
        ({"category": "rate_limit"}, True),
        ({"category": "transport"}, True),
        ({"category": "provider"}, True),
        ({"category": "auth"}, False),
        ({"category": "validation"}, False),
        ({"category": "policy"}, False),
        ({"phase": "poll", "acceptance": "accepted"}, False),
        ({"retryable": False}, False),
        ({"acceptance": "accepted"}, False),
        ({"acceptance": "unknown"}, False),
    ],
)
def test_failover_requires_safe_submit_certainty(changes, expected):
    assert should_fail_over(_error(**changes)) is expected


def test_error_taxonomy_is_strict():
    with pytest.raises(ValueError, match="phase"):
        _error(phase="retry")
    with pytest.raises(ValueError, match="category"):
        _error(category="timeout")
    with pytest.raises(ValueError, match="acceptance"):
        _error(acceptance="maybe")
    with pytest.raises(ValueError, match="boolean"):
        _error(retryable=1)


def test_execution_exception_carries_structured_error_for_handleless_submit_failure():
    error = _error(category="rate_limit", provider_code="429")
    exception = ProviderExecutionException(error)
    assert exception.error is error
    assert str(exception) == "provider is at capacity"
    assert should_fail_over(exception.error)
    with pytest.raises(ValueError, match="ProviderExecutionErrorV1"):
        ProviderExecutionException("not structured")


class _FakeExecutor:
    provider_key = "runway"

    def __init__(self) -> None:
        self.result = ProviderResultV1(_handle(), ProviderCostV1.not_chargeable())

    def submit(self, request):
        return self.result

    def poll(self, handle):
        return self.result

    def cancel(self, handle):
        return self.result


def test_registry_dispatches_and_orders_provider_keys_deterministically():
    registry = ProviderExecutorRegistry()
    executor = _FakeExecutor()
    registry.register(executor)
    assert registry.provider_keys == ("runway",)
    request = ProviderRequestV1(
        provider_key="runway",
        model_ref="runwayml/gen-4",
        correlation_id="corr-1",
        modality="video",
        prompt="prompt",
    )
    assert registry.submit(request) is executor.result
    assert registry.poll(_handle()) is executor.result
    assert registry.cancel(_handle()) is executor.result


def test_registry_rejects_duplicate_and_missing_provider():
    registry = ProviderExecutorRegistry()
    registry.register(_FakeExecutor())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_FakeExecutor())
    registry.register(_FakeExecutor(), replace_existing=True)
    with pytest.raises(LookupError, match="no provider executor"):
        registry.require("missing")
    registry.unregister("runway")
    assert registry.provider_keys == ()


@pytest.mark.parametrize(
    ("handle_changes", "message"),
    [
        ({"provider_key": "other"}, "provider"),
        ({"model_ref": "other/model"}, "model"),
        ({"run_id": "other-run"}, "run"),
    ],
)
def test_registry_rejects_adapter_identity_drift(handle_changes, message):
    registry = ProviderExecutorRegistry()
    executor = _FakeExecutor()
    registry.register(executor)
    executor.result = ProviderResultV1(
        _handle(**handle_changes), ProviderCostV1.not_chargeable()
    )
    with pytest.raises(ValueError, match=message):
        registry.poll(_handle())


def test_registry_rejects_state_regression_and_terminal_redispatch():
    registry = ProviderExecutorRegistry()
    executor = _FakeExecutor()
    registry.register(executor)
    with pytest.raises(ValueError, match="regress"):
        registry.poll(_handle("IN_PROGRESS"))
    for state in ("COMPLETED", "FAILED", "CANCELLED"):
        terminal_handle = _handle(state)
        with pytest.raises(ValueError, match="must not be polled"):
            registry.poll(terminal_handle)
        with pytest.raises(ValueError, match="must not be cancelled"):
            registry.cancel(terminal_handle)


def test_legacy_completed_reproduces_golden_and_preserves_unknown_fields(golden):
    fixture = golden["legacy_completed"]
    result = decode_legacy_execution(
        fixture["input"], provider_key="runway", model_ref="runwayml/gen-4"
    )
    assert result.to_dict() == fixture["output"]


def test_legacy_inflight_cost_is_preserved_as_nonbillable_metadata():
    result = decode_legacy_execution(
        {"status": "queued", "provider_ref": "job-1", "cost_micros": 700},
        provider_key="kling-fal",
        model_ref="kwaivgi/kling-v2-master",
        phase="submit",
    )
    assert result.state == "IN_QUEUE"
    assert result.cost == ProviderCostV1.not_chargeable()
    assert result.handle.opaque["legacy_estimated_cost_micros"] == 700


def test_legacy_failure_becomes_typed_nonretryable_unknown_acceptance():
    result = decode_legacy_execution(
        {"status": "failed", "provider_ref": "job-2", "error": "upstream failed"},
        provider_key="runway",
        model_ref="runwayml/gen-4",
    )
    assert result.state == "FAILED"
    assert result.error == ProviderExecutionErrorV1(
        phase="poll",
        category="provider",
        retryable=False,
        acceptance="unknown",
        message="upstream failed",
    )
    assert not should_fail_over(result.error)


def test_legacy_terminal_without_provider_ref_gets_stable_content_derived_id():
    legacy = {
        "status": "completed",
        "output_url": "https://cdn.example/image.png",
        "cost_micros": 12,
    }
    first = decode_legacy_execution(legacy, provider_key="openai-image", model_ref="gpt-image-1")
    second = decode_legacy_execution(
        dict(reversed(list(legacy.items()))),
        provider_key="openai-image",
        model_ref="gpt-image-1",
    )
    assert first.handle.run_id == second.handle.run_id
    assert first.handle.run_id.startswith("legacy-")


def test_live_legacy_execution_requires_provider_reference():
    with pytest.raises(ValueError, match="requires provider_ref"):
        decode_legacy_execution(
            {"status": "running"}, provider_key="runway", model_ref="runwayml/gen-4"
        )


def test_legacy_completed_rejects_missing_or_unsafe_output():
    for output_url in ("", "file:///tmp/out.mp4", "data:text/plain,no"):
        with pytest.raises(ValueError):
            decode_legacy_execution(
                {"status": "completed", "output_url": output_url},
                provider_key="runway",
                model_ref="runwayml/gen-4",
            )


def test_legacy_completed_preserves_bounded_inline_image_output():
    payload = base64.b64encode(b"legacy-image").decode("ascii")
    reference = f"data:image/png;base64,{payload}"
    result = decode_legacy_execution(
        {"status": "completed", "output_url": reference, "cost_micros": 10},
        provider_key="openai-image",
        model_ref="gpt-image-1",
    )
    assert result.outputs == (ProviderOutputV1(reference, "image"),)


def test_decoders_reject_unknown_schema_versions():
    with pytest.raises(ValueError, match="unsupported schema"):
        ProviderHandleV1.from_dict({"schema": "menivor.provider-handle/v2"})
    with pytest.raises(ValueError, match="unsupported schema"):
        ProviderRequestV1.from_dict({"schema": "menivor.provider-execution/v2"})
    with pytest.raises(ValueError, match="unsupported schema"):
        ProviderResultV1.from_dict({"schema": "menivor.provider-result/v2"})


def test_value_objects_are_frozen():
    handle = _handle()
    with pytest.raises(FrozenInstanceError):
        handle.state = "FAILED"
    assert handle.with_state("IN_PROGRESS").state == "IN_PROGRESS"
    assert handle.state == "IN_QUEUE"
