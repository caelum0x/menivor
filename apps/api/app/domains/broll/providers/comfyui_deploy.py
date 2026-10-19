"""ComfyUI-Deploy AI B-roll generation provider (text/image -> motion clip).

Drives a ComfyUI workflow deployed as a serverless GPU endpoint via
`comfyui-deploy <https://github.com/BennyKok/comfyui-deploy>`_ ("a Vercel for
generative workflow infra") and implements the
:class:`~app.domains.broll.providers.base.BrollGenProvider` Protocol
(``name = "comfyui"``), so alternative AI-video backends stay interchangeable at
the registry level — exactly like HeyGen <-> LatentSync on the avatar side.

Contract (verified against comfyui-deploy's ``registerCreateRunRoute`` /
``registerGetOutputRoute`` and its ``workflow_run_status`` enum):

1. **Create run** — ``POST {base_url}/api/run`` with
   ``Authorization: Bearer {api_key}`` and JSON body
   ``{"deployment_id": str, "inputs": {str: str | number}}``. Response:
   ``{"run_id": str}``. ``inputs`` map to the deployed workflow's external-input
   nodes (ExternalText / ExternalImage / ExternalNumber).
2. **Poll** — ``GET {base_url}/api/run?run_id={id}`` (same Bearer auth) until the
   run ``status`` is terminal. Statuses: ``not-started`` / ``running`` /
   ``uploading`` (pending) -> ``success`` | ``failed`` (terminal). On success the
   body carries ``outputs: [{"data": {...}}]`` where a video/image node's data
   holds the rendered file url.
3. Download the output url to a local temp mp4 and return
   ``{'clip_path', 'duration', 'provider_job_id'}`` (+ best-effort worker
   ``clip_url``). The job-scoped R2 upload is the *service* layer's job
   (``broll._upload_broll_clip`` under ``jobs/<job_id>/broll/<uuid>.mp4``), so
   this provider stays job-agnostic and never needs a ``job_id``.

All external I/O is wrapped so failures return ``None`` rather than crashing the
pipeline (a B-roll failure never fails a reel job). Config is read defensively
via ``getattr(config, "comfyui", {})`` (``base_url``, ``api_key``,
``deployment_id`` for t2v, optional ``deployment_id_i2v``, ``timeout_s``) so this
module imports cleanly even if that wiring lands later.
"""

from __future__ import annotations

import os
import tempfile

import requests
from loguru import logger

from app.config import config
from app.domains.broll.providers.base import register_broll_provider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S: float = 1800.0  # hard cap: 30 minutes
_POLL_INTERVAL_S: float = 5.0
_HTTP_TIMEOUT_S: int = 60
_DOWNLOAD_TIMEOUT_S: int = 300

# comfyui-deploy workflow_run_status enum (web/src/db/schema.ts).
_STATUS_SUCCESS = "success"
_STATUS_FAILED = "failed"
_STATUS_PENDING = {"not-started", "running", "uploading"}

# Generation modes.
_MODE_T2V = "t2v"
_MODE_I2V = "i2v"

# Keys a ComfyUI output node's ``data`` blob may use for the rendered media url.
# comfyui-deploy stores save-node outputs under images/gifs/files; a custom video
# node may use a flat ``url``/``video`` key. We scan all of them.
_OUTPUT_LIST_KEYS: tuple[str, ...] = ("images", "gifs", "files", "videos")
_OUTPUT_URL_KEYS: tuple[str, ...] = ("url", "video_url", "video", "output_url")
_OUTPUT_DURATION_KEYS: tuple[str, ...] = ("duration", "duration_s", "video_duration")

# Default names for the deployed workflow's external-input nodes. A workflow can
# use different names; override per call via ``extra_inputs`` (which wins).
_INPUT_PROMPT = "prompt"
_INPUT_IMAGE = "image"
_INPUT_WIDTH = "width"
_INPUT_HEIGHT = "height"
_INPUT_LENGTH = "length"  # number of frames
_INPUT_SEED = "seed"

_DEFAULT_FPS: int = 16


def _comfyui_config() -> dict:
    """Return the ``[comfyui]`` config section defensively.

    Read via ``getattr`` so this module imports cleanly even before the config
    wiring lands, and coerce to a plain dict so a non-mapping value degrades to
    ``{}`` instead of raising.
    """
    section = getattr(config, "comfyui", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


class ComfyDeployError(RuntimeError):
    """Raised for non-recoverable comfyui-deploy responses (run failed)."""


class ComfyDeployClient:
    """Thin comfyui-deploy REST client (create-run + poll-output)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        cfg = _comfyui_config()
        self.api_key: str = api_key if api_key is not None else cfg.get("api_key", "")
        raw_base = base_url if base_url is not None else cfg.get("base_url", "")
        # Normalise: strip trailing slash so ``{base}/api/run`` is well-formed.
        self.base_url: str = str(raw_base or "").rstrip("/")

    # -- urls ---------------------------------------------------------------
    def _run_url(self) -> str:
        if not self.base_url:
            raise ComfyDeployError("comfyui base_url is not configured")
        return f"{self.base_url}/api/run"

    # -- headers ------------------------------------------------------------
    def _headers(
        self,
        content_type: str | None = "application/json",
        correlation_id: str = "",
    ) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    # -- submit -------------------------------------------------------------
    def run(self, deployment_id: str, inputs: dict, correlation_id: str = "") -> str:
        """Queue a workflow run and return the comfyui-deploy ``run_id``."""
        if not deployment_id:
            raise ComfyDeployError("comfyui deployment_id is required to run")
        resp = requests.post(
            self._run_url(),
            headers=self._headers(correlation_id=correlation_id),
            json={"deployment_id": deployment_id, "inputs": inputs},
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        run_id = body.get("run_id", "") or ""
        if not run_id:
            raise ComfyDeployError(f"comfyui run returned no run_id: {str(body)[:200]}")
        logger.info(f"comfyui run queued, run_id={run_id}")
        return run_id

    # -- poll ---------------------------------------------------------------
    def wait(
        self,
        run_id: str,
        *,
        interval: float = _POLL_INTERVAL_S,
        timeout: float = _DEFAULT_TIMEOUT_S,
        correlation_id: str = "",
    ) -> dict:
        """Poll ``GET /api/run?run_id`` until the run reaches a terminal state.

        Returns the full run dict on ``success``. Raises :class:`ComfyDeployError`
        on ``failed`` and :class:`TimeoutError` once the hard cap is exceeded.
        Transient HTTP errors while polling are tolerated until the deadline.
        """
        import time

        deadline = time.monotonic() + timeout
        url = self._run_url()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"comfyui render timed out after {timeout:.0f}s (run_id={run_id})"
                )
            try:
                resp = requests.get(
                    url,
                    headers=self._headers(
                        content_type=None, correlation_id=correlation_id
                    ),
                    params={"run_id": run_id},
                    timeout=_HTTP_TIMEOUT_S,
                )
                resp.raise_for_status()
                body = resp.json() or {}
            except Exception as exc:  # noqa: BLE001 - transient poll error
                logger.warning(f"comfyui status poll error (retrying): {exc}")
                time.sleep(interval)
                continue

            status = body.get("status", "")
            if status == _STATUS_SUCCESS:
                logger.success(f"comfyui render complete, run_id={run_id}")
                return body
            if status == _STATUS_FAILED:
                reason = body.get("error") or "unknown"
                raise ComfyDeployError(
                    f"comfyui render failed (run_id={run_id}): {str(reason)[:200]}"
                )
            if status and status not in _STATUS_PENDING:
                logger.debug(
                    f"comfyui unexpected status '{status}', continuing to poll"
                )
            time.sleep(interval)


class ComfyUIProvider:
    """``BrollGenProvider`` backed by :class:`ComfyDeployClient`.

    Text->video (``t2v``) and image->video (``i2v``) motion B-roll. Which
    deployed workflow runs is selected by an explicit ``workflow_id`` (a
    comfyui-deploy ``deployment_id``) or, failing that, the config default for
    the requested ``mode``.
    """

    name: str = "comfyui"

    def __init__(self) -> None:
        cfg = _comfyui_config()
        self._api_key: str = cfg.get("api_key", "")
        self._base_url: str = str(cfg.get("base_url", "") or "").rstrip("/")
        self._deployment_t2v: str = str(cfg.get("deployment_id", "") or "")
        self._deployment_i2v: str = str(
            cfg.get("deployment_id_i2v", "") or self._deployment_t2v
        )
        self._client: ComfyDeployClient = ComfyDeployClient(
            self._api_key, self._base_url
        )

    def is_enabled(self) -> bool:
        return bool(self._api_key and self._base_url and self._deployment_t2v)

    def list_workflows(self) -> list[dict]:
        """comfyui-deploy exposes no per-key workflow catalog on this endpoint.

        Motion presets live in ReelForge's own preset table, so return an empty
        list (mirrors the graceful-degradation contract of the Protocol).
        """
        return []

    def _resolve_deployment(self, mode: str, workflow_id: str | None) -> str:
        """Pick the comfyui-deploy deployment id for this generation.

        Explicit ``workflow_id`` wins; otherwise fall back to the mode default.
        """
        from app.domains.broll.workflows import approved_workflow_ids

        if workflow_id and workflow_id in approved_workflow_ids(self.name):
            return workflow_id
        if workflow_id:
            logger.warning("ignored unapproved comfyui deployment selector")
        return self._deployment_i2v if mode == _MODE_I2V else self._deployment_t2v

    @staticmethod
    def _build_inputs(
        *,
        prompt: str,
        mode: str,
        image_url: str | None,
        width: int,
        height: int,
        duration_s: float,
        seed: int | None,
        extra_inputs: dict | None,
    ) -> dict:
        """Assemble the comfyui-deploy ``inputs`` map (values are str | number).

        Frame count is derived from ``duration_s`` at a fixed fps. Caller-supplied
        ``extra_inputs`` are merged last so a workflow with differently named
        external inputs (or extra knobs like LoRA weight / motion strength) can
        override any default.
        """
        frames = max(1, int(round(duration_s * _DEFAULT_FPS)))
        inputs: dict = {
            _INPUT_PROMPT: prompt,
            _INPUT_WIDTH: int(width),
            _INPUT_HEIGHT: int(height),
            _INPUT_LENGTH: frames,
        }
        if seed is not None:
            inputs[_INPUT_SEED] = int(seed)
        if mode == _MODE_I2V and image_url:
            inputs[_INPUT_IMAGE] = image_url
        if extra_inputs:
            inputs.update(extra_inputs)
        return inputs

    def generate_clip(
        self,
        prompt: str,
        *,
        mode: str = _MODE_T2V,
        image_url: str | None = None,
        width: int = 1080,
        height: int = 1920,
        duration_s: float = 5.0,
        workflow_id: str | None = None,
        seed: int | None = None,
        extra_inputs: dict | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        correlation_id: str = "",
    ) -> dict | None:
        """Generate an AI motion clip; returns the result dict or ``None``.

        See :class:`~app.domains.broll.providers.base.BrollGenProvider` for the
        contract. Submits to comfyui-deploy, polls to completion, downloads the
        rendered clip to a local temp mp4, and returns
        ``{'clip_path','duration','provider_job_id'}`` (+ best-effort
        ``clip_url``). Returns ``None`` on any failure/timeout.
        """
        prompt = (prompt or "").strip()
        if not self.is_enabled():
            logger.error(
                "comfyui provider is not enabled "
                "(missing config.comfyui api_key/base_url/deployment_id)"
            )
            return None
        if not prompt:
            logger.error("comfyui generate_clip requires a non-empty prompt")
            return None
        if mode == _MODE_I2V and not image_url:
            logger.error("comfyui i2v generation requires an image_url")
            return None

        # Enforce the immutable comfy-workflow-schema pin AT DISPATCH: validate
        # the submitted graph against the pinned input contract (fail closed on a
        # contract breach) and resolve the FNV-1a workflow version to stamp onto
        # this run's provenance, so a changed node commit yields a new version.
        from app.domains.broll import workflows as _wf

        frames = max(1, int(round(duration_s * _DEFAULT_FPS)))
        pin_errors = _wf.validate_dispatch_inputs(
            mode, frames=frames, has_image=bool(image_url)
        )
        if pin_errors:
            logger.error(
                "comfyui dispatch rejected by pinned workflow contract: "
                + "; ".join(pin_errors)
            )
            return None
        workflow_pin = _wf.pin_workflow(mode)
        if workflow_pin:
            logger.info(
                f"comfyui dispatch pinned to workflow '{workflow_pin['slug']}' "
                f"(graph_hash={workflow_pin['pin']})"
            )

        deployment_id = self._resolve_deployment(mode, workflow_id)
        if not deployment_id:
            logger.error(
                f"comfyui generate_clip: no deployment configured for mode '{mode}'"
            )
            return None

        inputs = self._build_inputs(
            prompt=prompt,
            mode=mode,
            image_url=image_url,
            width=width,
            height=height,
            duration_s=duration_s,
            seed=seed,
            extra_inputs=extra_inputs,
        )

        run = self._render_with_retry(
            deployment_id=deployment_id,
            inputs=inputs,
            timeout_s=timeout_s,
            correlation_id=correlation_id,
        )
        if run is None:
            return None

        run_id = str(run.get("id") or run.get("run_id") or "") or ""
        clip_url = self._extract_output_url(run)
        if not clip_url:
            logger.error(
                f"comfyui run produced no downloadable video url (run_id={run_id})"
            )
            return None

        local_path = self._download_to_temp(clip_url, run_id)
        if local_path is None:
            logger.error("comfyui render output could not be downloaded")
            return None

        result: dict = {
            "clip_path": local_path,
            "duration": self._resolve_duration(run, duration_s),
            "provider_job_id": run_id,
            "clip_url": clip_url,
        }
        if workflow_pin:
            # Immutable version identity travels with the output for provenance.
            result["workflow_slug"] = workflow_pin["slug"]
            result["workflow_pin"] = workflow_pin["pin"]
        return result

    # -- internals ----------------------------------------------------------
    def _render_with_retry(
        self,
        *,
        deployment_id: str,
        inputs: dict,
        timeout_s: float,
        correlation_id: str = "",
    ) -> dict | None:
        """Submit + wait; retry once on a transient render failure."""
        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + one retry
            try:
                if correlation_id:
                    run_id = self._client.run(
                        deployment_id, inputs, correlation_id=correlation_id
                    )
                    return self._client.wait(
                        run_id,
                        timeout=timeout_s,
                        correlation_id=correlation_id,
                    )
                # Preserve the original adapter call shape for embedders that
                # wrap these methods while correlation is not available.
                run_id = self._client.run(deployment_id, inputs)
                return self._client.wait(run_id, timeout=timeout_s)
            except TimeoutError as exc:
                logger.error(f"comfyui render timed out: {exc}")
                return None  # do not retry a full 30-min timeout
            except ComfyDeployError as exc:
                last_exc = exc
                logger.warning(
                    f"comfyui render failed (attempt {attempt + 1}/2): {exc}"
                )
            except Exception as exc:  # noqa: BLE001 - HTTP/network failure
                last_exc = exc
                logger.warning(f"comfyui render error (attempt {attempt + 1}/2): {exc}")
        logger.error(f"comfyui render exhausted retries: {last_exc}")
        return None

    @classmethod
    def _extract_output_url(cls, run: dict) -> str | None:
        """Find the rendered media url inside a run's ``outputs`` list.

        Each output is ``{"data": {...}}``; a save/video node stores its file(s)
        under ``images``/``gifs``/``files``/``videos`` (list of ``{url|filename}``)
        or a flat ``url``/``video`` key. We prefer video extensions but accept the
        first usable url so an unexpected node shape still yields a clip.
        """
        outputs = run.get("outputs")
        if not isinstance(outputs, list):
            return None

        first_url: str | None = None
        for output in outputs:
            data = output.get("data") if isinstance(output, dict) else None
            if not isinstance(data, dict):
                continue
            for url in cls._iter_data_urls(data):
                if url.lower().split("?", 1)[0].endswith((".mp4", ".webm", ".mov")):
                    return url  # a real video output — take it immediately
                if first_url is None:
                    first_url = url
        return first_url

    @classmethod
    def _iter_data_urls(cls, data: dict):
        """Yield every http(s) url found in an output ``data`` blob."""
        for key in _OUTPUT_LIST_KEYS:
            items = data.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        url = item.get("url")
                        if cls._is_http_url(url):
                            yield url
                    elif cls._is_http_url(item):
                        yield item
        for key in _OUTPUT_URL_KEYS:
            url = data.get(key)
            if cls._is_http_url(url):
                yield url

    @staticmethod
    def _is_http_url(value: object) -> bool:
        return isinstance(value, str) and (
            value.startswith("http://") or value.startswith("https://")
        )

    @classmethod
    def _resolve_duration(cls, run: dict, requested: float) -> float:
        """Return a worker-reported duration when present, else the requested one."""
        outputs = run.get("outputs")
        if isinstance(outputs, list):
            for output in outputs:
                data = output.get("data") if isinstance(output, dict) else None
                if not isinstance(data, dict):
                    continue
                for key in _OUTPUT_DURATION_KEYS:
                    raw = data.get(key)
                    try:
                        if raw is not None and float(raw) > 0:
                            return float(raw)
                    except (TypeError, ValueError):
                        continue
        return float(requested)

    @staticmethod
    def _download_to_temp(video_url: str, run_id: str) -> str | None:
        """Download the rendered clip url to a local temp mp4."""
        try:
            resp = requests.get(video_url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S)
            resp.raise_for_status()
            suffix = f"_{run_id}.mp4" if run_id else ".mp4"
            fd, local_path = tempfile.mkstemp(prefix="comfyui_broll", suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
            logger.info(f"comfyui broll clip downloaded to {local_path}")
            return local_path
        except Exception as exc:  # noqa: BLE001 - network/disk failure
            logger.error(
                f"failed to download comfyui broll clip (run_id={run_id}): {exc}"
            )
            return None


# Self-register at import so ``get_broll_provider('comfyui')`` resolves.
register_broll_provider(ComfyUIProvider())
