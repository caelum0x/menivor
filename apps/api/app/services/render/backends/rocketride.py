"""RocketRide runtime backend for the unified ReelForge render envelope.

The public render request selects only ``local`` or ``managed``. Runtime URI,
credential, and the editor-authored ``.pipe`` path come from operator config;
callers cannot inject any of them through the render spec. Both targets execute
the same file and must return the same versioned ReelForge output receipt.

The official RocketRide client is async while ``RenderBackend`` is synchronous.
``OfficialRocketRideDriver`` owns that boundary and remains replaceable with a
deterministic driver. It imports the optional SDK lazily, connects for one SDK
operation, and always disconnects. No SDK exception text, token, URI, or
credential is copied into an envelope or public error.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Coroutine, Protocol, TypeVar, runtime_checkable
from urllib.parse import urlsplit

from app.services.render.backends.base import (
    BackendError,
    RenderBackend,
    Transport,
    register_backend,
)
from app.services.render.envelope import (
    CANCELLED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    IN_QUEUE,
    RenderJob,
    transition,
)

RECEIPT_VERSION = "reelforge.render.receipt.v1"
_TARGETS = frozenset({"local", "managed"})
_QUEUED_STATES = frozenset({"CREATED", "PENDING", "QUEUED", "STARTING", "NOT_STARTED"})
_RUNNING_STATES = frozenset({"RUNNING", "PROCESSING", "IN_PROGRESS", "EXECUTING"})
_COMPLETED_STATES = frozenset({"COMPLETED", "COMPLETE", "SUCCEEDED", "SUCCESS", "FINISHED", "DONE"})
_FAILED_STATES = frozenset({"FAILED", "FAILURE", "ERROR", "TIMED_OUT", "TIMEOUT", "CRASHED"})
_CANCELLED_STATES = frozenset({"CANCELLED", "CANCELED", "ABORTED", "TERMINATED"})
_CONTROL_KEYS = frozenset({"rocketride_target"})
_T = TypeVar("_T")


@dataclass(frozen=True)
class RocketRideTarget:
    """Operator-owned connection profile; never serialized into a job."""

    name: str
    uri: str
    credential: str
    connect_timeout_seconds: float


@dataclass(frozen=True)
class RocketRideReceipt:
    """The only terminal-success payload ReelForge accepts from a pipeline."""

    output_refs: tuple[str, ...]
    actual_cost_micros: int


@runtime_checkable
class RocketRideDriver(Protocol):
    """Injectable seam around the optional official async Python SDK."""

    def submit(
        self,
        *,
        target: RocketRideTarget,
        pipeline_path: Path,
        payload: dict[str, Any],
        ttl_seconds: int,
        pipeline_trace_level: str,
    ) -> str: ...

    def status(self, *, target: RocketRideTarget, token: str) -> Any: ...

    def terminate(self, *, target: RocketRideTarget, token: str) -> None: ...


class OfficialRocketRideDriver:
    """Lazy adapter for the official ``rocketride`` Python package."""

    def _client(self, target: RocketRideTarget):
        try:
            from rocketride import RocketRideClient
        except ImportError as exc:
            raise BackendError(
                "rocketride",
                "official Python SDK is not installed; install the optional "
                "`rocketride` package before enabling this backend",
            ) from exc
        return RocketRideClient(uri=target.uri, auth=target.credential)

    async def _with_client(self, target: RocketRideTarget, operation):
        client = self._client(target)
        try:
            await client.connect(timeout=target.connect_timeout_seconds)
            return await operation(client)
        finally:
            try:
                await client.disconnect()
            except Exception:
                # Disconnect is cleanup. It must not replace the operation's
                # result or leak SDK details into the public render envelope.
                pass

    def submit(
        self,
        *,
        target: RocketRideTarget,
        pipeline_path: Path,
        payload: dict[str, Any],
        ttl_seconds: int,
        pipeline_trace_level: str,
    ) -> str:
        async def operation(client):
            use_kwargs: dict[str, Any] = {
                "filepath": str(pipeline_path),
                "ttl": ttl_seconds,
            }
            # Some official SDK releases expose this optional spelling while
            # others omit it. The default config leaves it empty.
            if pipeline_trace_level:
                use_kwargs["pipelineTraceLevel"] = pipeline_trace_level
            use_result = await client.use(**use_kwargs)
            use_body = _mapping(use_result)
            token = str(use_body.get("token") or "")
            if not _safe_token(token):
                raise BackendError("rocketride", "pipeline start returned no valid task token")
            try:
                await client.send(
                    token,
                    json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    objinfo={"name": "reelforge-render-input.json"},
                    mimetype="application/json",
                )
            except Exception:
                try:
                    await client.terminate(token)
                except Exception:
                    pass
                raise
            return token

        try:
            return _run_async(lambda: self._with_client(target, operation))
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(
                "rocketride", "SDK submit failed for the configured target", retryable=True
            ) from exc

    def status(self, *, target: RocketRideTarget, token: str) -> Any:
        async def operation(client):
            return await client.get_task_status(token)

        try:
            return _run_async(lambda: self._with_client(target, operation))
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(
                "rocketride", "SDK status failed for the configured target", retryable=True
            ) from exc

    def terminate(self, *, target: RocketRideTarget, token: str) -> None:
        async def operation(client):
            await client.terminate(token)

        try:
            _run_async(lambda: self._with_client(target, operation))
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(
                "rocketride", "SDK cancellation failed for the configured target", retryable=True
            ) from exc


class RocketRideBackend(RenderBackend):
    name = "rocketride"

    def __init__(self, *, driver: RocketRideDriver | None = None, config: dict | None = None) -> None:
        self._driver = driver or OfficialRocketRideDriver()
        self._config = dict(config) if config is not None else None

    def _cfg(self) -> dict:
        if self._config is not None:
            return dict(self._config)
        from app.config import config

        return dict(getattr(config, "rocketride", {}) or {})

    def _target(self, name: str) -> RocketRideTarget:
        target_name = str(name or "").strip().lower()
        if target_name not in _TARGETS:
            raise BackendError(self.name, "rocketride_target must be local or managed")
        cfg = self._cfg()
        uri = str(cfg.get(f"{target_name}_uri") or "").strip()
        credential = str(cfg.get(f"{target_name}_api_key") or "")
        if not _safe_uri(uri):
            raise BackendError(self.name, f"{target_name} target URI is not configured correctly")
        if target_name == "managed" and not credential:
            raise BackendError(self.name, "managed target credential is not configured")
        try:
            timeout_seconds = float(cfg.get("connect_timeout_seconds") or 60)
        except (TypeError, ValueError) as exc:
            raise BackendError(self.name, "connect_timeout_seconds must be numeric") from exc
        if not 1 <= timeout_seconds <= 3600:
            raise BackendError(self.name, "connect_timeout_seconds must be between 1 and 3600")
        return RocketRideTarget(target_name, uri, credential, timeout_seconds)

    def _pipeline_path(self) -> Path:
        cfg = self._cfg()
        from app.config import config

        raw_root = str(cfg.get("pipeline_root") or "pipelines/rocketride").strip()
        raw_file = str(cfg.get("pipeline_file") or "").strip()
        root = Path(raw_root)
        if not root.is_absolute():
            root = Path(config.root_dir) / root
        root = root.resolve()
        candidate = Path(raw_file)
        if not raw_file or candidate.is_absolute() or candidate.suffix.lower() != ".pipe":
            raise BackendError(
                self.name, "pipeline_file must name an editor-authored .pipe under pipeline_root"
            )
        pipeline = (root / candidate).resolve()
        if not pipeline.is_relative_to(root) or not pipeline.is_file():
            raise BackendError(
                self.name, "configured editor-authored .pipe is missing or outside pipeline_root"
            )
        return pipeline

    def submit(self, spec: dict, *, transport: Transport) -> RenderJob:
        req = dict(spec) if isinstance(spec, dict) else {}
        target = self._target(req.get("rocketride_target"))
        pipeline_path = self._pipeline_path()
        payload = {key: value for key, value in req.items() if key not in _CONTROL_KEYS}
        cfg = self._cfg()
        try:
            ttl_seconds = int(cfg.get("ttl_seconds") or 3600)
        except (TypeError, ValueError) as exc:
            raise BackendError(self.name, "ttl_seconds must be an integer") from exc
        if not 60 <= ttl_seconds <= 86_400:
            raise BackendError(self.name, "ttl_seconds must be between 60 and 86400")
        trace_level = str(cfg.get("pipeline_trace_level") or "").strip()
        token = self._driver.submit(
            target=target,
            pipeline_path=pipeline_path,
            payload=payload,
            ttl_seconds=ttl_seconds,
            pipeline_trace_level=trace_level,
        )
        if not _safe_token(token):
            raise BackendError(self.name, "driver returned no valid task token")
        return RenderJob(
            id=str(req.get("job_id") or token),
            backend=self.name,
            workflow_version=str(req.get("workflow_version") or pipeline_path.stem),
            state=IN_QUEUE,
            provider_ref=token,
            poll_cursor=target.name,
            attempts=1,
            meta={"rocketride_target": target.name},
        )

    def poll(self, job: RenderJob, *, transport: Transport) -> RenderJob:
        if job.is_terminal:
            return job
        target = self._target(job.poll_cursor)
        if not _safe_token(job.provider_ref):
            return transition(job, FAILED, error="rocketride task token is unavailable")
        status = _mapping(self._driver.status(target=target, token=job.provider_ref))
        raw_state = str(status.get("state") or "").strip().upper()
        progress = _progress(status)

        if raw_state in _QUEUED_STATES:
            return transition(job, IN_QUEUE, progress=progress)
        if raw_state in _RUNNING_STATES:
            return transition(job, IN_PROGRESS, progress=progress)
        if raw_state in _FAILED_STATES:
            return transition(job, FAILED, error="rocketride pipeline reported failure")
        if raw_state in _CANCELLED_STATES:
            return transition(job, CANCELLED)
        if raw_state not in _COMPLETED_STATES:
            return transition(job, FAILED, error="rocketride returned an unsupported status")

        receipt = _receipt(status)
        if receipt is None:
            # A terminal state without the pipeline-authored receipt cannot be
            # billed safely. FAILED makes the executor release the full hold.
            return transition(
                job,
                FAILED,
                error="rocketride completed without a valid ReelForge output receipt",
            )
        completed = transition(
            job,
            COMPLETED,
            progress=1.0,
            output_refs=receipt.output_refs,
            cost_micros=receipt.actual_cost_micros,
        )
        return replace(
            completed,
            meta={
                **job.meta,
                "rocketride_target": target.name,
                "receipt_version": RECEIPT_VERSION,
                "actual_cost_reported": True,
            },
        )

    def cancel(self, job: RenderJob, *, transport: Transport) -> RenderJob:
        if job.is_terminal:
            return job
        target = self._target(job.poll_cursor)
        if _safe_token(job.provider_ref):
            self._driver.terminate(target=target, token=job.provider_ref)
        return transition(job, CANCELLED)

    def warm(self, model: str, *, transport: Transport) -> bool:
        target_name = str(model or "").strip().lower()
        try:
            self._target(target_name)
            self._pipeline_path()
        except BackendError:
            return False
        return True


def _mapping(value: Any) -> dict[str, Any]:
    """Accept documented mappings and model objects with ``model_dump`` only."""
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            body = dump()
        except Exception:
            return {}
        return dict(body) if isinstance(body, dict) else {}
    return {}


def _receipt(status: dict[str, Any]) -> RocketRideReceipt | None:
    candidates: list[Any] = [status.get("receipt")]
    result = _mapping(status.get("result"))
    if result:
        candidates.extend((result.get("receipt"), result))
    for raw in candidates:
        body = _mapping(raw)
        if body.get("version") != RECEIPT_VERSION:
            continue
        refs = body.get("output_refs")
        cost = body.get("actual_cost_micros")
        if (
            not isinstance(refs, list)
            or not 1 <= len(refs) <= 16
            or isinstance(cost, bool)
            or not isinstance(cost, int)
            or cost < 0
        ):
            continue
        normalized: list[str] = []
        for ref in refs:
            if not isinstance(ref, str):
                break
            clean = ref.strip()
            if not clean or len(clean) > 2048 or any(ch in clean for ch in ("\n", "\r", "\x00")):
                break
            normalized.append(clean)
        else:
            return RocketRideReceipt(tuple(normalized), cost)
    return None


def _progress(status: dict[str, Any]) -> float | None:
    completed = status.get("completedCount", status.get("completed_count"))
    total = status.get("totalCount", status.get("total_count"))
    if isinstance(completed, bool) or isinstance(total, bool):
        return None
    if not isinstance(completed, (int, float)) or not isinstance(total, (int, float)):
        return None
    if total <= 0 or completed < 0:
        return None
    return max(0.0, min(1.0, float(completed) / float(total)))


def _safe_uri(uri: str) -> bool:
    if not uri or len(uri) > 2048 or any(ch in uri for ch in ("\n", "\r", "\x00")):
        return False
    parsed = urlsplit(uri)
    return parsed.scheme.lower() in {"http", "https", "ws", "wss"} and bool(parsed.hostname)


def _safe_token(token: str) -> bool:
    return bool(token) and len(token) <= 200 and not any(ch in token for ch in ("\n", "\r", "\x00"))


def _run_async(factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run an SDK coroutine from sync code, including inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    values: list[_T] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            values.append(asyncio.run(factory()))
        except BaseException as exc:  # propagate on the calling thread
            errors.append(exc)

    thread = threading.Thread(target=runner, name="rocketride-sdk-bridge", daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return values[0]


register_backend(RocketRideBackend())
