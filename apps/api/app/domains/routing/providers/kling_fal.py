"""Kling video generation via fal.ai — a REAL cloud model adapter.

This is not a seam-abstracted stub: it imports ``requests`` and speaks the actual
fal.ai **queue REST API** (the same protocol the ``fal_client`` SDK wraps), so it
runs live with a real ``FAL_KEY``. Per the 2026 research, Kling on fal.ai is the
cheapest high-quality video model ($0.084/s vs ~2x on Replicate).

Real end-to-end flow:

  1. **submit**   ``POST https://queue.fal.run/{model}``  (``Authorization: Key …``)
                  body = Kling arguments (prompt, duration, aspect_ratio, image_url…).
                  → ``{request_id, status_url, response_url, cancel_url}``.
  2. **poll**     ``GET {status_url}`` until ``COMPLETED`` (IN_QUEUE→IN_PROGRESS→COMPLETED),
                  surfacing ``queue_position``.
  3. **result**   ``GET {response_url}`` → ``{"video": {"url": "…mp4", "file_size": N}}``.
  4. **download**  stream the produced MP4 to disk.

Real error taxonomy + retry: 401/403 auth (fatal), 422 validation/content-policy
(fatal), 429 rate-limit (honor ``Retry-After``, back off), and transient polling
failures (exponential backoff + jitter). Ambiguous submission failures are never
blindly retried because the first POST may already have created billable work. A
``requests.Session`` is used (injectable for tests, which swap the transport — the
library + protocol are real, only the socket is faked).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

_QUEUE_BASE = "https://queue.fal.run"
# Direct fal endpoint namespaces the catalog may route (MH0: Seedance 2.0 is
# published under ``bytedance/`` on fal, not ``fal-ai/``).
FAL_PATH_PREFIXES: tuple[str, ...] = ("fal-ai/", "bytedance/")

# fal.ai model ids for Kling (text→video and image→video, current lines).
KLING_MODELS = {
    "kling-t2v": "fal-ai/kling-video/v1.6/standard/text-to-video",
    "kling-i2v": "fal-ai/kling-video/v1.6/standard/image-to-video",
    "kling-pro-t2v": "fal-ai/kling-video/v2/master/text-to-video",
    "kling-pro-i2v": "fal-ai/kling-video/v2/master/image-to-video",
}
# Kling billing on fal.ai (micro-USD per second of output).
_PRICE_MICROS_PER_SECOND = {
    "kling-t2v": 84_000,
    "kling-i2v": 84_000,
    "kling-pro-t2v": 280_000,
    "kling-pro-i2v": 280_000,
}


ACCEPTANCE_DEFINITE_NO = "definitely_not_accepted"
ACCEPTANCE_UNKNOWN = "unknown"
_ACCEPTANCE_VALUES = {ACCEPTANCE_DEFINITE_NO, ACCEPTANCE_UNKNOWN}


class KlingError(RuntimeError):
    """A Kling/fal.ai generation error."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "provider",
        retryable: bool = False,
        status: int = 0,
        acceptance: str = ACCEPTANCE_DEFINITE_NO,
    ) -> None:
        if acceptance not in _ACCEPTANCE_VALUES:
            raise ValueError(f"invalid provider acceptance certainty: {acceptance!r}")
        self.kind = kind  # auth | validation | rate_limit | transient | provider
        self.retryable = retryable
        self.status = status
        self.acceptance = acceptance
        super().__init__(message)

    @property
    def may_have_been_accepted(self) -> bool:
        return self.acceptance == ACCEPTANCE_UNKNOWN


@dataclass
class KlingJob:
    """A submitted fal.ai queue job."""

    request_id: str
    status_url: str
    response_url: str
    cancel_url: str = ""
    state: str = "IN_QUEUE"  # IN_QUEUE | IN_PROGRESS | COMPLETED | FAILED | CANCELLED
    queue_position: int = 0
    failure: str = ""
    output: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in ("COMPLETED", "FAILED", "CANCELLED")

    @property
    def video_url(self) -> str:
        v = self.output.get("video") if isinstance(self.output, dict) else None
        if isinstance(v, dict):
            return str(v.get("url", "") or "")
        return ""


class KlingFalAdapter:
    """Real Kling adapter over the fal.ai queue API."""

    provider_key = "kling"

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "kling-t2v",
        session: Any = None,
        timeout_s: float = 60.0,
        max_retries: int = 4,
        poll_interval_s: float = 2.0,
        max_poll_s: float = 600.0,
        sleep=time.sleep,
    ) -> None:
        self._api_key = api_key or os.getenv("FAL_KEY", "")
        # Accept either a short alias in KLING_MODELS or a direct fal model path
        # ("fal-ai/…"), so the catalog can route any real fal video model.
        if model in KLING_MODELS:
            self._model = model
            self._model_id = KLING_MODELS[model]
        elif model.startswith(FAL_PATH_PREFIXES):
            self._model = model
            self._model_id = model
        else:
            raise KlingError(
                f"unknown Kling model {model!r}; use a direct fal path ({', '.join(FAL_PATH_PREFIXES)}) "
                f"or one of {list(KLING_MODELS)}",
                kind="validation",
            )
        self._session = session  # a requests.Session; created lazily if None
        self._timeout = timeout_s
        self._max_retries = max_retries
        self._poll_interval = poll_interval_s
        self._max_poll_s = max_poll_s
        self._sleep = sleep

    # -- transport ---------------------------------------------------------- #
    def _sess(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        if not self._api_key:
            raise KlingError("FAL_KEY not configured", kind="auth")
        return {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, url: str, *, json: dict | None = None) -> dict:
        """One HTTP call with the real error taxonomy + transient retry/backoff."""
        import requests  # real library; imported here so module import never fails

        is_submit = method.upper() == "POST"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._sess().request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json,
                    timeout=self._timeout,
                )
            except requests.exceptions.Timeout as exc:
                if not is_submit and attempt <= self._max_retries:
                    self._backoff(attempt)
                    continue
                raise KlingError(
                    f"fal.ai timeout after {attempt} attempts: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc
            except requests.exceptions.ConnectionError as exc:
                if not is_submit and attempt <= self._max_retries:
                    self._backoff(attempt)
                    continue
                raise KlingError(
                    f"fal.ai connection error: {exc}",
                    kind="transient",
                    retryable=True,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                ) from exc

            status = resp.status_code
            if 200 <= status < 300:
                return self._json(resp)
            if status in (401, 403):
                raise KlingError(
                    f"fal.ai auth failed ({status}) — check FAL_KEY",
                    kind="auth",
                    status=status,
                )
            if status == 422:
                raise KlingError(
                    f"fal.ai rejected the request (422): {self._err_detail(resp)}",
                    kind="validation",
                    status=422,
                )
            if status == 429:
                if attempt <= self._max_retries:
                    self._backoff(attempt, retry_after=resp.headers.get("Retry-After"))
                    continue
                raise KlingError(
                    "fal.ai rate limit exceeded",
                    kind="rate_limit",
                    retryable=True,
                    status=429,
                )
            if status == 408 or status >= 500:
                if not is_submit and attempt <= self._max_retries:
                    self._backoff(attempt)
                    continue
                raise KlingError(
                    f"fal.ai server error {status}",
                    kind="transient",
                    retryable=True,
                    status=status,
                    acceptance=(
                        ACCEPTANCE_UNKNOWN if is_submit else ACCEPTANCE_DEFINITE_NO
                    ),
                )
            raise KlingError(
                f"fal.ai unexpected status {status}: {self._err_detail(resp)}",
                kind="provider",
                status=status,
            )

    def _backoff(self, attempt: int, *, retry_after: Any = None) -> None:
        if retry_after:
            try:
                self._sleep(min(30.0, float(retry_after)))
                return
            except (TypeError, ValueError):
                pass
        # Exponential backoff with a deterministic-ish jitter from the attempt.
        delay = min(30.0, (2 ** (attempt - 1)) * self._poll_interval)
        jitter = (attempt % 3) * 0.25
        self._sleep(delay + jitter)

    @staticmethod
    def _json(resp) -> dict:
        try:
            body = resp.json()
        except Exception as exc:  # pragma: no cover - malformed upstream body
            raise KlingError(
                f"fal.ai returned a non-JSON body: {exc}", kind="provider"
            ) from exc
        return body if isinstance(body, dict) else {"data": body}

    @staticmethod
    def _err_detail(resp) -> str:
        try:
            body = resp.json()
            if isinstance(body, dict):
                return str(body.get("detail") or body.get("error") or body)[:300]
        except Exception:
            pass
        return (getattr(resp, "text", "") or "")[:300]

    # -- public API --------------------------------------------------------- #
    def submit(
        self,
        *,
        prompt: str,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
        extra: dict | None = None,
        image_urls: Sequence[str] = (),
    ) -> KlingJob:
        """Submit a Kling generation to the fal.ai queue; return the queued job.

        ``image_url`` is the single first frame (image-to-video). ``image_urls`` is
        the reference list for reference-to-video endpoints (Seedance 2.0 r2v), which
        the prompt names as @Image1, @Image2 ... in list order.
        """
        refs = [u for u in image_urls if u]
        if not prompt and not image_url and not refs:
            raise KlingError("a prompt or image_url is required", kind="validation")
        args: dict = {
            "prompt": prompt,
            "duration": str(int(seconds)),
            "aspect_ratio": aspect_ratio,
        }
        if refs:
            args["image_urls"] = refs
        elif image_url:
            args["image_url"] = image_url
        if extra:
            args.update(extra)

        body = self._call("POST", f"{_QUEUE_BASE}/{self._model_id}", json=args)
        request_id = str(body.get("request_id") or "")
        if not request_id:
            raise KlingError(
                f"fal.ai submit returned no request_id: {body}",
                kind="provider",
                acceptance=ACCEPTANCE_UNKNOWN,
            )
        return KlingJob(
            request_id=request_id,
            status_url=str(
                body.get("status_url")
                or f"{_QUEUE_BASE}/{self._model_id}/requests/{request_id}/status"
            ),
            response_url=str(
                body.get("response_url")
                or f"{_QUEUE_BASE}/{self._model_id}/requests/{request_id}"
            ),
            cancel_url=str(body.get("cancel_url") or ""),
        )

    def poll(self, job: KlingJob) -> KlingJob:
        """Advance ``job`` one step: read the queue status; fetch the result if done."""
        if job.is_terminal:
            return job
        status = self._call("GET", job.status_url)
        state = str(status.get("status", "IN_PROGRESS") or "IN_PROGRESS").upper()
        if state == "CANCELED":
            state = "CANCELLED"
        job.state = (
            state
            if state in ("IN_QUEUE", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED")
            else "IN_PROGRESS"
        )
        job.queue_position = int(status.get("queue_position", 0) or 0)
        if job.state == "COMPLETED":
            job.output = self._call("GET", job.response_url)
            if not job.video_url:
                raise KlingError(
                    f"completed but no video url in result: {job.output}",
                    kind="provider",
                )
        elif job.state in ("FAILED", "CANCELLED"):
            detail = (
                status.get("error") or status.get("detail") or status.get("message")
            )
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("detail") or detail
            job.failure = str(
                detail
                or status.get("reason")
                or f"fal.ai generation {job.state.lower()}"
            )
        return job

    def cancel(self, job: KlingJob) -> bool:
        if not job.cancel_url or job.is_terminal:
            return False
        try:
            self._call("PUT", job.cancel_url)
            return True
        except KlingError:
            return False

    def wait(self, job: KlingJob) -> KlingJob:
        """Poll until the job is terminal or the poll budget is exhausted."""
        waited = 0.0
        while not job.is_terminal:
            self.poll(job)
            if job.is_terminal:
                break
            if waited >= self._max_poll_s:
                raise KlingError(
                    f"generation did not complete within {self._max_poll_s}s",
                    kind="transient",
                    retryable=True,
                )
            self._sleep(self._poll_interval)
            waited += self._poll_interval
        return job

    def download(self, job: KlingJob, dest_path: str) -> str:
        """Stream the produced MP4 to ``dest_path`` (real streaming download)."""
        url = job.video_url
        if not url:
            raise KlingError(
                "no video url to download (job not completed?)", kind="validation"
            )
        try:
            with self._sess().get(url, stream=True, timeout=self._timeout) as resp:
                if resp.status_code != 200:
                    raise KlingError(
                        f"download failed (HTTP {resp.status_code})",
                        kind="provider",
                        status=resp.status_code,
                    )
                with open(dest_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            fh.write(chunk)
        except OSError as exc:
            raise KlingError(f"cannot write output: {exc}", kind="provider") from exc
        return dest_path

    def generate(
        self,
        *,
        prompt: str,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
        dest_path: str = "",
        extra: dict | None = None,
    ) -> dict:
        """End-to-end: submit → wait → (optionally) download. Returns a result dict."""
        job = self.submit(
            prompt=prompt,
            seconds=seconds,
            aspect_ratio=aspect_ratio,
            image_url=image_url,
            extra=extra,
        )
        self.wait(job)
        result = {
            "request_id": job.request_id,
            "video_url": job.video_url,
            "cost_micros": self.cost_micros(seconds),
        }
        if dest_path:
            result["local_path"] = self.download(job, dest_path)
        return result

    def cost_micros(self, seconds: int) -> int:
        """Integer micro-USD cost for ``seconds`` of output at this model's rate.

        (The gateway meters from the catalog price; this is a fallback for direct
        callers — direct fal paths default to the standard Kling rate.)"""
        rate = _PRICE_MICROS_PER_SECOND.get(self._model, 84_000)
        return int(max(1, int(seconds))) * rate
