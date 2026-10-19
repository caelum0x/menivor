"""LatentSync RunPod Serverless talking-head provider (Tier-B, §2.3/§2.4).

A ~20x-cheaper, self-hosted lip-sync alternative to HeyGen (§2.4). It drives a
`LatentSync <https://github.com/bytedance/LatentSync>`_ worker deployed on
`RunPod Serverless <https://docs.runpod.io/serverless/endpoints/get-started>`_
and implements the SAME :class:`~app.services.avatar.base.TalkingHeadProvider`
Protocol as :class:`~app.services.avatar.heygen.HeyGenProvider`
(``name = "latentsync"``), so the two are interchangeable at the registry level.

Flow (mirrors the HeyGen provider):

1. POST the audio URL (a public R2 URL from the pipeline) + an avatar reference
   image + render params to ``POST /v2/{endpoint_id}/run`` (async).
2. Poll ``GET /v2/{endpoint_id}/status/{job_id}`` until ``COMPLETED``/``FAILED``.
3. The worker returns an output **video URL** or **base64** payload; download /
   decode it to a local temp mp4 and re-host it on R2 via ``storage.r2``.
4. Validate the output duration against the single audio-duration authority
   (§8, ±0.25s) and return
   ``{'avatar_video', 'duration', 'provider_video_id'}`` (+ best-effort
   ``avatar_key`` / ``avatar_url``).

Auth uses ``Authorization: Bearer {api_key}`` (RunPod's scheme — NOT HeyGen's
``X-Api-Key``). All external I/O is wrapped so failures return ``None`` / ``[]``
rather than crashing the pipeline. Config is read defensively via
``getattr(config, "runpod", {})`` (``endpoint_id``, ``api_key``, ``timeout_s``,
optional ``avatar_image_url``) so this module imports cleanly even if that
wiring lands later.
"""

from __future__ import annotations

import base64
import binascii
import os
import tempfile
import time

import requests
from loguru import logger

from app.config import config
from app.services.avatar.base import register_avatar_provider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DURATION_TOLERANCE_S: float = 0.25
_DEFAULT_TIMEOUT_S: float = 1800.0  # hard cap: 30 minutes
_POLL_INTERVAL_S: float = 5.0
_HTTP_TIMEOUT_S: int = 60
_DOWNLOAD_TIMEOUT_S: int = 300

_API_BASE: str = "https://api.runpod.ai/v2"

# RunPod Serverless job statuses.
_STATUS_COMPLETED = "COMPLETED"
_STATUS_FAILED = "FAILED"
_STATUS_CANCELLED = "CANCELLED"
_STATUS_TIMED_OUT = "TIMED_OUT"
_STATUS_TERMINAL_FAIL = {_STATUS_FAILED, _STATUS_CANCELLED, _STATUS_TIMED_OUT}
_STATUS_PENDING = {"IN_QUEUE", "IN_PROGRESS", "RUNNING"}

# Keys the worker output may use for the rendered video URL / base64 blob.
_OUTPUT_URL_KEYS: tuple[str, ...] = (
    "video_url",
    "output_url",
    "url",
    "video",
    "result_url",
)
_OUTPUT_B64_KEYS: tuple[str, ...] = (
    "video_base64",
    "video_b64",
    "output_base64",
    "base64",
    "data",
)
_OUTPUT_DURATION_KEYS: tuple[str, ...] = ("duration", "duration_s", "video_duration")


def _runpod_config() -> dict:
    """Return the ``[runpod]`` config section defensively.

    The section is added by the config layer (§3); read it via ``getattr`` so
    this module imports cleanly even if that wiring lands later, and coerce to a
    plain dict so non-mapping values degrade to ``{}`` instead of raising.
    """
    section = getattr(config, "runpod", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


class RunPodError(RuntimeError):
    """Raised for non-recoverable RunPod responses (render failed/cancelled)."""


class LatentSyncClient:
    """Thin RunPod Serverless REST client for a LatentSync lip-sync worker."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint_id: str | None = None,
    ) -> None:
        cfg = _runpod_config()
        self.api_key: str = api_key if api_key is not None else cfg.get("api_key", "")
        self.endpoint_id: str = (
            endpoint_id if endpoint_id is not None else cfg.get("endpoint_id", "")
        )

    # -- urls ---------------------------------------------------------------
    def _endpoint_base(self) -> str:
        if not self.endpoint_id:
            raise RunPodError("runpod endpoint_id is not configured")
        return f"{_API_BASE}/{self.endpoint_id}"

    # -- headers ------------------------------------------------------------
    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    # -- submit -------------------------------------------------------------
    def run(self, worker_input: dict) -> str:
        """Submit an async job (``POST /run``) and return the RunPod ``id``."""
        resp = requests.post(
            f"{self._endpoint_base()}/run",
            headers=self._headers(),
            json={"input": worker_input},
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        job_id = body.get("id", "") or ""
        if not job_id:
            raise RunPodError(f"runpod run returned no job id: {str(body)[:200]}")
        # A synchronous-ish endpoint may already report a terminal status.
        status = body.get("status", "")
        if status in _STATUS_TERMINAL_FAIL:
            raise RunPodError(f"runpod job {job_id} failed immediately: {status}")
        logger.info(f"latentsync job queued, id={job_id}")
        return job_id

    # -- poll ---------------------------------------------------------------
    def wait(
        self,
        job_id: str,
        *,
        interval: float = _POLL_INTERVAL_S,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> dict:
        """Poll ``GET /status/{id}`` until the job reaches a terminal state.

        Returns the worker ``output`` dict on ``COMPLETED``. Raises
        :class:`RunPodError` on ``FAILED``/``CANCELLED``/``TIMED_OUT`` and
        :class:`TimeoutError` once the hard cap is exceeded. Transient HTTP
        errors while polling are tolerated until the deadline.
        """
        deadline = time.monotonic() + timeout
        status_url = f"{self._endpoint_base()}/status/{job_id}"
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"latentsync render timed out after {timeout:.0f}s (id={job_id})"
                )
            try:
                resp = requests.get(
                    status_url,
                    headers=self._headers(content_type=None),
                    timeout=_HTTP_TIMEOUT_S,
                )
                resp.raise_for_status()
                body = resp.json() or {}
            except Exception as exc:  # noqa: BLE001 - transient poll error
                logger.warning(f"latentsync status poll error (retrying): {exc}")
                time.sleep(interval)
                continue

            status = body.get("status", "")
            if status == _STATUS_COMPLETED:
                logger.success(f"latentsync render complete, id={job_id}")
                output = body.get("output")
                return output if isinstance(output, dict) else {"output": output}
            if status in _STATUS_TERMINAL_FAIL:
                reason = body.get("error") or body.get("output") or "unknown"
                raise RunPodError(
                    f"latentsync render {status.lower()} (id={job_id}): {str(reason)[:200]}"
                )

            if status and status not in _STATUS_PENDING:
                logger.debug(f"latentsync unexpected status '{status}', continuing to poll")
            time.sleep(interval)

    # -- avatars ------------------------------------------------------------
    def health(self) -> dict:
        """Return the endpoint health payload (raises on HTTP error)."""
        resp = requests.get(
            f"{self._endpoint_base()}/health",
            headers=self._headers(content_type=None),
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json() or {}


class LatentSyncProvider:
    """``TalkingHeadProvider`` implementation backed by :class:`LatentSyncClient`.

    Tier-B, self-hosted lip-sync. Interchangeable with
    :class:`~app.services.avatar.heygen.HeyGenProvider` — same Protocol, same
    return shape, same ±0.25s duration validation (§8).
    """

    name: str = "latentsync"

    def __init__(self) -> None:
        cfg = _runpod_config()
        self._api_key: str = cfg.get("api_key", "")
        self._endpoint_id: str = cfg.get("endpoint_id", "")
        self._default_avatar_image: str = str(cfg.get("avatar_image_url", "") or "")
        self._client: LatentSyncClient = LatentSyncClient(
            self._api_key, self._endpoint_id
        )

    def is_enabled(self) -> bool:
        return bool(self._api_key and self._endpoint_id)

    def list_avatars(self) -> list[dict]:
        """LatentSync is reference-image driven; it has no server-side catalog.

        Presets live in ReelForge's ``avatar_presets`` table, so return an empty
        list here (mirrors the graceful-degradation contract of the Protocol).
        """
        return []

    def _resolve_avatar_image(self, avatar_id: str) -> str:
        """Resolve the reference image URL LatentSync animates.

        ``avatar_id`` may itself be a URL (preferred — an R2/https reference
        image) or empty, in which case the configured default is used.
        """
        candidate = (avatar_id or "").strip()
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return candidate
        return self._default_avatar_image

    def generate_avatar(
        self,
        audio_url: str,
        avatar_id: str,
        *,
        width: int = 1080,
        height: int = 1920,
        background: dict | None = None,
        expected_duration_s: float | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        character_kind: str = "avatar",
    ) -> dict | None:
        """Render a lip-synced avatar clip from an external R2 audio URL.

        ``character_kind`` is part of the shared :class:`TalkingHeadProvider`
        contract but has no meaning here: LatentSync is reference-image driven
        and does not model HeyGen's ``avatar`` vs ``talking_photo`` character
        types, so the argument is accepted and intentionally ignored.

        Submits ``{audio_url, avatar_image, width, height, ...}`` to the RunPod
        worker, polls to completion, materialises the worker's video URL or
        base64 output to a local temp file, re-hosts it on R2, and validates the
        render duration against ``expected_duration_s`` (§8, ±0.25s).

        Returns ``{'avatar_video','duration','provider_video_id'}`` (plus
        best-effort ``avatar_url``/``avatar_key`` from the re-host) or ``None``
        on failure/timeout.
        """
        if not self.is_enabled():
            logger.error(
                "latentsync provider is not enabled (missing runpod api_key/endpoint_id)"
            )
            return None
        if not audio_url:
            logger.error("latentsync generate_avatar requires a public audio_url")
            return None

        avatar_image = self._resolve_avatar_image(avatar_id)
        if not avatar_image:
            logger.error(
                "latentsync generate_avatar requires an avatar reference image "
                "(pass a URL as avatar_id or set config.runpod.avatar_image_url)"
            )
            return None

        worker_input: dict = {
            "audio_url": audio_url,
            "avatar_image": avatar_image,
            "avatar_id": avatar_id,
            "width": width,
            "height": height,
        }
        if background is not None:
            worker_input["background"] = background

        output = self._render_with_retry(worker_input=worker_input, timeout_s=timeout_s)
        if output is None:
            return None

        job_id = str(output.get("id") or output.get("job_id") or "") or ""
        # Keep the worker-reported duration (or None) distinct from the value we
        # surface, so the §8 check never compares the expected value against
        # itself when the worker omits a duration (that would be a silent no-op).
        reported_duration = self._coerce_duration(self._extract_duration(output))
        duration = (
            reported_duration
            if reported_duration is not None
            else (float(expected_duration_s) if expected_duration_s is not None else 0.0)
        )

        local_path = self._materialize_output(output, job_id)
        if local_path is None:
            logger.error("latentsync render produced no usable video output")
            return None

        self._validate_duration(reported_duration, expected_duration_s)

        result: dict = {
            "avatar_video": local_path,
            "duration": duration,
            "provider_video_id": job_id,
        }
        rehosted = self._rehost(local_path, job_id)
        if rehosted:
            result.update(rehosted)
        return result

    # -- internals ----------------------------------------------------------
    def _render_with_retry(
        self,
        *,
        worker_input: dict,
        timeout_s: float,
    ) -> dict | None:
        """Submit + wait; retry once on a transient render failure."""
        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + one retry
            try:
                job_id = self._client.run(worker_input)
                return self._client.wait(job_id, timeout=timeout_s)
            except TimeoutError as exc:
                logger.error(f"latentsync render timed out: {exc}")
                return None  # do not retry a full 30-min timeout
            except RunPodError as exc:
                last_exc = exc
                logger.warning(f"latentsync render failed (attempt {attempt + 1}/2): {exc}")
            except Exception as exc:  # noqa: BLE001 - HTTP/network failure
                last_exc = exc
                logger.warning(f"latentsync render error (attempt {attempt + 1}/2): {exc}")
        logger.error(f"latentsync render exhausted retries: {last_exc}")
        return None

    @staticmethod
    def _extract_duration(output: dict) -> object:
        for key in _OUTPUT_DURATION_KEYS:
            if output.get(key) is not None:
                return output.get(key)
        return None

    @staticmethod
    def _coerce_duration(raw: object) -> float | None:
        """Parse the worker-reported duration to a float, or ``None``.

        Returns ``None`` when the worker omitted the duration or reported a
        non-numeric value, so callers can distinguish an unverifiable render
        from a genuine numeric report and never treat the expected value as if
        the worker had confirmed it (§8).
        """
        if raw is None:
            return None
        try:
            return float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_duration(reported: float | None, expected: float | None) -> None:
        if expected is None:
            return
        if reported is None or reported <= 0:
            # The worker gave us nothing to check against, so the §8 tolerance
            # gate cannot run. Warn loudly instead of silently passing — a
            # truncated render would otherwise slip through unnoticed.
            logger.warning(
                "latentsync render duration could not be verified against §8 "
                f"tolerance: worker output carried no usable duration field "
                f"(expected={expected:.3f}s); using expected as a best-effort "
                "estimate"
            )
            return
        delta = abs(reported - expected)
        if delta > _DURATION_TOLERANCE_S:
            logger.warning(
                "latentsync render duration drift beyond tolerance: "
                f"expected={expected:.3f}s actual={reported:.3f}s "
                f"delta={delta:.3f}s (tol=±{_DURATION_TOLERANCE_S}s)"
            )

    # -- output materialization --------------------------------------------
    @classmethod
    def _materialize_output(cls, output: dict, job_id: str) -> str | None:
        """Turn the worker output into a local temp mp4.

        The worker may return either a downloadable video URL or a base64 blob
        (possibly nested under an ``output`` key). URL is preferred; base64 is
        the fallback.
        """
        candidates: list[dict] = [output]
        nested = output.get("output")
        if isinstance(nested, dict):
            candidates.append(nested)

        for node in candidates:
            for key in _OUTPUT_URL_KEYS:
                url = node.get(key)
                if isinstance(url, str) and (
                    url.startswith("http://") or url.startswith("https://")
                ):
                    path = cls._download_to_temp(url, job_id)
                    if path is not None:
                        return path

        for node in candidates:
            for key in _OUTPUT_B64_KEYS:
                blob = node.get(key)
                if isinstance(blob, str) and blob:
                    path = cls._decode_b64_to_temp(blob, job_id)
                    if path is not None:
                        return path

        logger.error(
            f"latentsync output missing a video url/base64 field (id={job_id}): "
            f"{sorted(output)[:10]}"
        )
        return None

    @staticmethod
    def _download_to_temp(video_url: str, job_id: str) -> str | None:
        """Download the worker's output URL to a local temp mp4."""
        try:
            resp = requests.get(video_url, stream=True, timeout=_DOWNLOAD_TIMEOUT_S)
            resp.raise_for_status()
            suffix = f"_{job_id}.mp4" if job_id else ".mp4"
            fd, local_path = tempfile.mkstemp(prefix="latentsync_avatar", suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
            logger.info(f"latentsync avatar downloaded to {local_path}")
            return local_path
        except Exception as exc:  # noqa: BLE001 - network/disk failure
            logger.error(f"failed to download latentsync avatar (id={job_id}): {exc}")
            return None

    @staticmethod
    def _decode_b64_to_temp(blob: str, job_id: str) -> str | None:
        """Decode a base64 (optionally data-URI) video blob to a local temp mp4."""
        try:
            payload = blob.split(",", 1)[1] if blob.startswith("data:") else blob
            raw = base64.b64decode(payload, validate=False)
            if not raw:
                raise ValueError("decoded base64 video is empty")
            suffix = f"_{job_id}.mp4" if job_id else ".mp4"
            fd, local_path = tempfile.mkstemp(prefix="latentsync_avatar", suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            logger.info(f"latentsync avatar decoded to {local_path}")
            return local_path
        except (binascii.Error, ValueError, OSError) as exc:
            logger.error(f"failed to decode latentsync base64 avatar (id={job_id}): {exc}")
            return None

    @staticmethod
    def _rehost(local_path: str, job_id: str) -> dict:
        """Re-host the rendered clip on R2 for a stable, permanent URL.

        Best-effort: returns ``{'avatar_key','avatar_url'}`` on success, or an
        empty dict if storage is unavailable (the local path still lets the
        compose stage proceed).
        """
        try:
            from app.services.storage.r2 import r2_client

            key = f"avatars/{job_id or os.path.basename(local_path)}.mp4"
            url = r2_client.upload_file(local_path, key, "video/mp4")
            logger.info(f"latentsync avatar re-hosted to R2: {key}")
            return {"avatar_key": key, "avatar_url": url}
        except Exception as exc:  # noqa: BLE001 - storage optional at this layer
            logger.warning(f"failed to re-host latentsync avatar on R2 (continuing): {exc}")
            return {}


# Self-register at import so ``get_avatar_provider('latentsync')`` resolves.
register_avatar_provider(LatentSyncProvider())
