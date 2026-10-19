"""Versioned, persistence-neutral provider execution contract.

This module contains only immutable value objects and validation.  Provider
HTTP clients may implement :class:`ProviderExecutor`; Menivor and Prism remain
responsible for authentication, persistence, retries, and wallet settlement.

All serialized shapes carry a schema identifier.  Unknown provider polling
fields belong in ``ProviderHandleV1.opaque`` and survive a decode/encode cycle.
Secrets must never be placed in a request, handle, result, or error.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.parse import urlsplit

from .envelope import STATES, normalize_state

EXECUTION_SCHEMA_V1 = "menivor.provider-execution/v1"
HANDLE_SCHEMA_V1 = "menivor.provider-handle/v1"
RESULT_SCHEMA_V1 = "menivor.provider-result/v1"

ERROR_PHASES = ("validate", "submit", "poll", "cancel", "output")
ERROR_CATEGORIES = (
    "auth",
    "validation",
    "rate_limit",
    "capacity",
    "transport",
    "provider",
    "not_found",
    "policy",
    "unknown",
)
ACCEPTANCE_CERTAINTIES = ("not_accepted", "accepted", "unknown")
COST_SOURCES = ("none", "provider_reported", "catalog_estimate", "free", "legacy")
OUTPUT_KINDS = ("image", "video", "audio", "file")
INLINE_IMAGE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
MAX_INLINE_IMAGE_BYTES = 16 * 1024 * 1024


def _require_string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _json_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    _validate_json_value(value, name)
    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only finite JSON values") from exc
    if not isinstance(decoded, dict):  # pragma: no cover - guarded by Mapping
        raise ValueError(f"{name} must be a JSON object")
    return decoded


def _validate_json_value(value: Any, name: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain only finite JSON values")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} JSON object keys must be strings")
            _validate_json_value(item, name)
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, name)
        return
    raise ValueError(f"{name} must contain only JSON values")


def _schema(value: Mapping[str, Any], expected: str) -> None:
    if value.get("schema") != expected:
        raise ValueError(f"unsupported schema: expected {expected!r}")


def validate_output_reference(reference: str) -> str:
    """Validate a provider output URL without performing network access.

    HTTP(S) references require a hostname and may not embed credentials.  The
    only inline form is a valid base64 PNG, JPEG, or WebP image no larger than
    16 MiB decoded.  Local files and executable/arbitrary data schemes must not
    cross the provider boundary.
    """

    reference = _require_string(reference, "output reference")
    if reference.startswith("data:"):
        header, separator, payload = reference.partition(",")
        if not separator or header not in {
            f"data:{media_type};base64" for media_type in INLINE_IMAGE_MEDIA_TYPES
        }:
            raise ValueError("inline output must be base64 PNG, JPEG, or WebP")
        if not payload or any(character.isspace() for character in payload):
            raise ValueError("inline image payload must be non-empty base64 without whitespace")
        padding = len(payload) - len(payload.rstrip("="))
        if padding > 2:
            raise ValueError("inline image payload has invalid base64 padding")
        estimated_bytes = (len(payload) * 3) // 4 - padding
        if estimated_bytes > MAX_INLINE_IMAGE_BYTES:
            raise ValueError("inline image payload exceeds 16 MiB")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("inline image payload is not valid base64") from exc
        if not decoded:
            raise ValueError("inline image payload must not be empty")
        if len(decoded) > MAX_INLINE_IMAGE_BYTES:
            raise ValueError("inline image payload exceeds 16 MiB")
        return reference

    if len(reference) > 8_192:
        raise ValueError("output reference is too long")
    parsed = urlsplit(reference)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("output reference must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("output reference must not contain credentials")
    return reference


@dataclass(frozen=True)
class ProviderRequestV1:
    provider_key: str
    model_ref: str
    correlation_id: str
    modality: str
    prompt: str
    duration_seconds: int = 0
    aspect_ratio: str = ""
    input_refs: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema: str = EXECUTION_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema != EXECUTION_SCHEMA_V1:
            raise ValueError(f"unsupported request schema {self.schema!r}")
        for name in ("provider_key", "model_ref", "correlation_id", "modality", "prompt"):
            _require_string(getattr(self, name), name)
        _require_int(self.duration_seconds, "duration_seconds")
        _require_string(self.aspect_ratio, "aspect_ratio", allow_empty=True)
        if not isinstance(self.input_refs, tuple):
            raise ValueError("input_refs must be a tuple")
        for item in self.input_refs:
            validate_output_reference(item)
        object.__setattr__(self, "parameters", _json_object(self.parameters, "parameters"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "provider_key": self.provider_key,
            "model_ref": self.model_ref,
            "correlation_id": self.correlation_id,
            "modality": self.modality,
            "prompt": self.prompt,
            "duration_seconds": self.duration_seconds,
            "aspect_ratio": self.aspect_ratio,
            "input_refs": list(self.input_refs),
            "parameters": _json_object(self.parameters, "parameters"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderRequestV1":
        _schema(value, EXECUTION_SCHEMA_V1)
        input_refs = value.get("input_refs", [])
        if not isinstance(input_refs, list) or not all(
            isinstance(item, str) for item in input_refs
        ):
            raise ValueError("input_refs must be an array of strings")
        return cls(
            schema=value["schema"],
            provider_key=value.get("provider_key"),
            model_ref=value.get("model_ref"),
            correlation_id=value.get("correlation_id"),
            modality=value.get("modality"),
            prompt=value.get("prompt"),
            duration_seconds=value.get("duration_seconds", 0),
            aspect_ratio=value.get("aspect_ratio", ""),
            input_refs=tuple(input_refs),
            parameters=value.get("parameters", {}),
        )


@dataclass(frozen=True)
class ProviderHandleV1:
    provider_key: str
    model_ref: str
    run_id: str
    state: str = "IN_QUEUE"
    status_url: str = ""
    response_url: str = ""
    opaque: Mapping[str, Any] = field(default_factory=dict)
    schema: str = HANDLE_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema != HANDLE_SCHEMA_V1:
            raise ValueError(f"unsupported handle schema {self.schema!r}")
        for name in ("provider_key", "model_ref", "run_id"):
            _require_string(getattr(self, name), name)
        if self.state not in STATES:
            raise ValueError(f"invalid normalized state {self.state!r}")
        for name in ("status_url", "response_url"):
            value = getattr(self, name)
            _require_string(value, name, allow_empty=True)
            if value:
                validate_output_reference(value)
        object.__setattr__(self, "opaque", _json_object(self.opaque, "opaque"))

    def with_state(self, state: str) -> "ProviderHandleV1":
        return replace(self, state=state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "provider_key": self.provider_key,
            "model_ref": self.model_ref,
            "run_id": self.run_id,
            "state": self.state,
            "status_url": self.status_url,
            "response_url": self.response_url,
            "opaque": _json_object(self.opaque, "opaque"),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderHandleV1":
        _schema(value, HANDLE_SCHEMA_V1)
        return cls(
            schema=value["schema"],
            provider_key=value.get("provider_key"),
            model_ref=value.get("model_ref"),
            run_id=value.get("run_id"),
            state=value.get("state", "IN_QUEUE"),
            status_url=value.get("status_url", ""),
            response_url=value.get("response_url", ""),
            opaque=value.get("opaque", {}),
        )


@dataclass(frozen=True)
class ProviderOutputV1:
    reference: str
    kind: str
    media_type: str = ""

    def __post_init__(self) -> None:
        validate_output_reference(self.reference)
        if self.kind not in OUTPUT_KINDS:
            raise ValueError(f"unsupported output kind {self.kind!r}")
        if self.reference.startswith("data:") and self.kind != "image":
            raise ValueError("inline data output is permitted only for image results")
        _require_string(self.media_type, "media_type", allow_empty=True)

    def to_dict(self) -> dict[str, Any]:
        return {"reference": self.reference, "kind": self.kind, "media_type": self.media_type}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderOutputV1":
        return cls(
            reference=value.get("reference"),
            kind=value.get("kind"),
            media_type=value.get("media_type", ""),
        )


@dataclass(frozen=True)
class ProviderCostV1:
    success: bool
    cost_micros: int
    currency: str = "USD"
    source: str = "none"
    unit: str = ""
    quantity_units: int = 0
    price_version: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.success, bool):
            raise ValueError("success must be a boolean")
        _require_int(self.cost_micros, "cost_micros")
        _require_int(self.quantity_units, "quantity_units")
        _require_string(self.currency, "currency")
        if self.source not in COST_SOURCES:
            raise ValueError(f"unsupported cost source {self.source!r}")
        _require_string(self.unit, "unit", allow_empty=True)
        _require_string(self.price_version, "price_version", allow_empty=True)
        if not self.success and (self.cost_micros != 0 or self.source != "none"):
            raise ValueError("non-success cost must be zero with source='none'")
        if self.success and self.source == "none":
            raise ValueError("successful cost must declare its source")

    @classmethod
    def not_chargeable(cls) -> "ProviderCostV1":
        return cls(success=False, cost_micros=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "cost_micros": self.cost_micros,
            "currency": self.currency,
            "source": self.source,
            "unit": self.unit,
            "quantity_units": self.quantity_units,
            "price_version": self.price_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCostV1":
        return cls(
            success=value.get("success"),
            cost_micros=value.get("cost_micros"),
            currency=value.get("currency", "USD"),
            source=value.get("source", "none"),
            unit=value.get("unit", ""),
            quantity_units=value.get("quantity_units", 0),
            price_version=value.get("price_version", ""),
        )


@dataclass(frozen=True)
class ProviderExecutionErrorV1:
    phase: str
    category: str
    retryable: bool
    acceptance: str
    message: str
    provider_code: str = ""

    def __post_init__(self) -> None:
        if self.phase not in ERROR_PHASES:
            raise ValueError(f"unsupported error phase {self.phase!r}")
        if self.category not in ERROR_CATEGORIES:
            raise ValueError(f"unsupported error category {self.category!r}")
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a boolean")
        if self.acceptance not in ACCEPTANCE_CERTAINTIES:
            raise ValueError(f"unsupported acceptance certainty {self.acceptance!r}")
        _require_string(self.message, "message")
        _require_string(self.provider_code, "provider_code", allow_empty=True)
    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "category": self.category,
            "retryable": self.retryable,
            "acceptance": self.acceptance,
            "message": self.message,
            "provider_code": self.provider_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderExecutionErrorV1":
        return cls(
            phase=value.get("phase"),
            category=value.get("category"),
            retryable=value.get("retryable"),
            acceptance=value.get("acceptance"),
            message=value.get("message"),
            provider_code=value.get("provider_code", ""),
        )


class ProviderExecutionException(Exception):
    """Raised when provider execution cannot return a valid durable result.

    In particular, submit failures that produced no provider run handle use
    this exception.  The structured ``error`` determines whether a caller may
    safely retry or fail over; the exception string is its sanitized message.
    """

    def __init__(self, error: ProviderExecutionErrorV1) -> None:
        if not isinstance(error, ProviderExecutionErrorV1):
            raise ValueError("error must be ProviderExecutionErrorV1")
        self.error = error
        super().__init__(error.message)


def should_fail_over(error: ProviderExecutionErrorV1) -> bool:
    """Return whether another provider may safely receive the same request.

    Failover is deliberately narrower than retryability: only a submit failure
    known not to have been accepted can be rerouted without duplicate spend.
    """

    return (
        error.phase == "submit"
        and error.retryable
        and error.acceptance == "not_accepted"
        and error.category in {"rate_limit", "capacity", "transport", "provider"}
    )


@dataclass(frozen=True)
class ProviderResultV1:
    handle: ProviderHandleV1
    cost: ProviderCostV1
    outputs: tuple[ProviderOutputV1, ...] = ()
    error: ProviderExecutionErrorV1 | None = None
    schema: str = RESULT_SCHEMA_V1

    def __post_init__(self) -> None:
        if self.schema != RESULT_SCHEMA_V1:
            raise ValueError(f"unsupported result schema {self.schema!r}")
        if not isinstance(self.handle, ProviderHandleV1):
            raise ValueError("handle must be ProviderHandleV1")
        if not isinstance(self.cost, ProviderCostV1):
            raise ValueError("cost must be ProviderCostV1")
        if not isinstance(self.outputs, tuple) or not all(
            isinstance(item, ProviderOutputV1) for item in self.outputs
        ):
            raise ValueError("outputs must be a tuple of ProviderOutputV1")

        state = self.handle.state
        if state == "COMPLETED":
            if not self.outputs:
                raise ValueError("completed result must contain at least one output")
            if self.error is not None:
                raise ValueError("completed result must not contain an error")
            if not self.cost.success:
                raise ValueError("completed result must carry successful cost semantics")
        elif state in {"FAILED", "CANCELLED"}:
            if self.outputs:
                raise ValueError("failed or cancelled result must not contain outputs")
            if self.error is None:
                raise ValueError("failed or cancelled result must contain a typed error")
            if self.cost.success:
                raise ValueError("failed or cancelled result must not carry billable cost")
        else:
            if self.outputs or self.error is not None:
                raise ValueError("in-flight result must not contain outputs or errors")
            if self.cost.success:
                raise ValueError("in-flight result must not carry billable cost")

    @property
    def state(self) -> str:
        return self.handle.state

    @property
    def is_terminal(self) -> bool:
        return self.state in {"COMPLETED", "FAILED", "CANCELLED"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "handle": self.handle.to_dict(),
            "cost": self.cost.to_dict(),
            "outputs": [item.to_dict() for item in self.outputs],
            "error": self.error.to_dict() if self.error is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderResultV1":
        _schema(value, RESULT_SCHEMA_V1)
        handle = value.get("handle")
        cost = value.get("cost")
        outputs = value.get("outputs", [])
        error = value.get("error")
        if not isinstance(handle, Mapping):
            raise ValueError("handle must be an object")
        if not isinstance(cost, Mapping):
            raise ValueError("cost must be an object")
        if not isinstance(outputs, list) or not all(isinstance(item, Mapping) for item in outputs):
            raise ValueError("outputs must be an array of objects")
        if error is not None and not isinstance(error, Mapping):
            raise ValueError("error must be an object or null")
        return cls(
            schema=value["schema"],
            handle=ProviderHandleV1.from_dict(handle),
            cost=ProviderCostV1.from_dict(cost),
            outputs=tuple(ProviderOutputV1.from_dict(item) for item in outputs),
            error=ProviderExecutionErrorV1.from_dict(error) if error is not None else None,
        )


@runtime_checkable
class ProviderExecutor(Protocol):
    """Pure provider I/O seam; implementations must not own wallet state.

    Methods return a validated result when a provider handle exists and may
    raise :class:`ProviderExecutionException` when no valid handle can be
    returned (for example, a known-not-accepted submit rejection).
    """

    @property
    def provider_key(self) -> str: ...

    def submit(self, request: ProviderRequestV1) -> ProviderResultV1: ...

    def poll(self, handle: ProviderHandleV1) -> ProviderResultV1: ...

    def cancel(self, handle: ProviderHandleV1) -> ProviderResultV1: ...


class ProviderExecutorRegistry:
    """Process-local adapter registry and identity-checking dispatcher.

    The registry owns no credentials, persistence, or retry policy.  It merely
    resolves the selected provider and proves that an adapter did not return a
    result for a different provider, model, or run.
    """

    def __init__(self) -> None:
        self._executors: dict[str, ProviderExecutor] = {}

    @property
    def provider_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))

    def register(self, executor: ProviderExecutor, *, replace_existing: bool = False) -> None:
        provider_key = _require_string(getattr(executor, "provider_key", None), "provider_key")
        if provider_key in self._executors and not replace_existing:
            raise ValueError(f"provider executor {provider_key!r} is already registered")
        self._executors[provider_key] = executor

    def unregister(self, provider_key: str) -> None:
        self._executors.pop(_require_string(provider_key, "provider_key"), None)

    def get(self, provider_key: str) -> ProviderExecutor | None:
        return self._executors.get(_require_string(provider_key, "provider_key"))

    def require(self, provider_key: str) -> ProviderExecutor:
        provider_key = _require_string(provider_key, "provider_key")
        executor = self._executors.get(provider_key)
        if executor is None:
            raise LookupError(f"no provider executor registered for {provider_key!r}")
        return executor

    def submit(self, request: ProviderRequestV1) -> ProviderResultV1:
        if not isinstance(request, ProviderRequestV1):
            raise ValueError("request must be ProviderRequestV1")
        result = self.require(request.provider_key).submit(request)
        _validate_dispatched_result(
            result,
            provider_key=request.provider_key,
            model_ref=request.model_ref,
        )
        return result

    def poll(self, handle: ProviderHandleV1) -> ProviderResultV1:
        if not isinstance(handle, ProviderHandleV1):
            raise ValueError("handle must be ProviderHandleV1")
        if handle.state in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("terminal provider handle must not be polled")
        result = self.require(handle.provider_key).poll(handle)
        _validate_dispatched_result(
            result,
            provider_key=handle.provider_key,
            model_ref=handle.model_ref,
            run_id=handle.run_id,
        )
        if handle.state == "IN_PROGRESS" and result.state == "IN_QUEUE":
            raise ValueError("provider result must not regress from IN_PROGRESS to IN_QUEUE")
        return result

    def cancel(self, handle: ProviderHandleV1) -> ProviderResultV1:
        if not isinstance(handle, ProviderHandleV1):
            raise ValueError("handle must be ProviderHandleV1")
        if handle.state in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("terminal provider handle must not be cancelled")
        result = self.require(handle.provider_key).cancel(handle)
        _validate_dispatched_result(
            result,
            provider_key=handle.provider_key,
            model_ref=handle.model_ref,
            run_id=handle.run_id,
        )
        return result


def _validate_dispatched_result(
    result: ProviderResultV1,
    *,
    provider_key: str,
    model_ref: str,
    run_id: str | None = None,
) -> None:
    if not isinstance(result, ProviderResultV1):
        raise ValueError("provider executor must return ProviderResultV1")
    if result.handle.provider_key != provider_key:
        raise ValueError("provider result does not match dispatched provider")
    if result.handle.model_ref != model_ref:
        raise ValueError("provider result does not match dispatched model")
    if run_id is not None and result.handle.run_id != run_id:
        raise ValueError("provider result does not match dispatched run")


_LEGACY_KNOWN_FIELDS = frozenset(
    {
        "status",
        "output_url",
        "cost_micros",
        "provider_ref",
        "status_url",
        "response_url",
        "error",
        "opaque",
    }
)


def decode_legacy_execution(
    value: Mapping[str, Any],
    *,
    provider_key: str,
    model_ref: str,
    phase: str = "poll",
) -> ProviderResultV1:
    """Decode Prism's legacy ``ExecutionOutcome``-shaped mapping.

    Unknown top-level fields and a legacy ``opaque`` object are preserved in
    the v1 handle.  A positive legacy cost on an in-flight/failed result is
    retained as non-billable metadata, never promoted to billable cost.
    """

    if not isinstance(value, Mapping):
        raise ValueError("legacy execution value must be an object")
    raw = _json_object(value, "legacy execution value")
    state = normalize_state(raw.get("status", ""))
    legacy_opaque = raw.get("opaque", {})
    if not isinstance(legacy_opaque, Mapping):
        raise ValueError("legacy opaque must be an object")
    opaque = _json_object(legacy_opaque, "legacy opaque")
    unknown = {key: item for key, item in raw.items() if key not in _LEGACY_KNOWN_FIELDS}
    if unknown:
        opaque["legacy_fields"] = unknown

    legacy_cost = raw.get("cost_micros")
    if legacy_cost is None:
        legacy_cost = 0
    _require_int(legacy_cost, "legacy cost_micros")
    if state != "COMPLETED" and legacy_cost:
        opaque["legacy_estimated_cost_micros"] = legacy_cost

    run_id = raw.get("provider_ref", "")
    if not run_id:
        if state in {"IN_QUEUE", "IN_PROGRESS"}:
            raise ValueError("live legacy execution requires provider_ref")
        canonical = json.dumps(raw, allow_nan=False, sort_keys=True, separators=(",", ":"))
        run_id = "legacy-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    handle = ProviderHandleV1(
        provider_key=provider_key,
        model_ref=model_ref,
        run_id=run_id,
        state=state,
        status_url=raw.get("status_url", ""),
        response_url=raw.get("response_url", ""),
        opaque=opaque,
    )
    if state == "COMPLETED":
        output_reference = raw.get("output_url", "")
        output = ProviderOutputV1(
            reference=output_reference,
            kind="image" if output_reference.startswith("data:image/") else "file",
        )
        return ProviderResultV1(
            handle=handle,
            outputs=(output,),
            cost=ProviderCostV1(
                success=True,
                cost_micros=legacy_cost,
                source="legacy",
            ),
        )
    if state in {"FAILED", "CANCELLED"}:
        error_phase = phase if phase in ERROR_PHASES else "poll"
        return ProviderResultV1(
            handle=handle,
            cost=ProviderCostV1.not_chargeable(),
            error=ProviderExecutionErrorV1(
                phase=error_phase,
                category="provider",
                retryable=False,
                acceptance="unknown",
                message=raw.get("error") or "legacy provider execution failed",
            ),
        )
    return ProviderResultV1(handle=handle, cost=ProviderCostV1.not_chargeable())


__all__ = [
    "EXECUTION_SCHEMA_V1",
    "HANDLE_SCHEMA_V1",
    "RESULT_SCHEMA_V1",
    "ERROR_PHASES",
    "ERROR_CATEGORIES",
    "ACCEPTANCE_CERTAINTIES",
    "COST_SOURCES",
    "OUTPUT_KINDS",
    "INLINE_IMAGE_MEDIA_TYPES",
    "MAX_INLINE_IMAGE_BYTES",
    "ProviderRequestV1",
    "ProviderHandleV1",
    "ProviderOutputV1",
    "ProviderCostV1",
    "ProviderExecutionErrorV1",
    "ProviderExecutionException",
    "ProviderResultV1",
    "ProviderExecutor",
    "ProviderExecutorRegistry",
    "validate_output_reference",
    "should_fail_over",
    "decode_legacy_execution",
]
