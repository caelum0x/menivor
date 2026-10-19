"""RunPod serverless GPU backend (async queue/poll/cancel).

Real RunPod serverless API (https://docs.runpod.io/serverless/endpoints/job-operations):

* submit — ``POST {base}/{endpoint_id}/run``      body ``{"input": <spec>}`` → ``{id, status}``
* poll   — ``POST {base}/{endpoint_id}/status/{id}`` → ``{status, output, ...}``
* cancel — ``POST {base}/{endpoint_id}/cancel/{id}``

Because RunPod hosts ``runpod-workers/worker-comfyui``, this same backend drives
ComfyUI-on-RunPod: the ComfyUI graph is just the ``input`` payload. All status
vocabularies are normalized through the envelope. Config (endpoint id + api key)
is resolved from ``config.app`` — never hardcoded; the network is the injectable
transport seam.
"""

from __future__ import annotations

from app.services.render.backends.base import (
    BackendError,
    RenderBackend,
    Transport,
    ok,
    register_backend,
    safe_json,
)
from app.services.render.envelope import (
    COMPLETED,
    FAILED,
    IN_QUEUE,
    RenderJob,
    normalize_state,
    transition,
)

_DEFAULT_BASE = "https://api.runpod.ai/v2"

# RunPod uses the generic vocabulary the envelope already knows, plus these.
_STATE_MAP = {
    "IN_QUEUE": IN_QUEUE,
    "IN_PROGRESS": "IN_PROGRESS",
    "COMPLETED": COMPLETED,
    "FAILED": FAILED,
    "CANCELLED": "CANCELLED",
}


class RunPodBackend(RenderBackend):
    name = "runpod"

    def __init__(self, endpoint_id: str | None = None, api_key: str | None = None, base: str | None = None):
        self._endpoint_id = endpoint_id
        self._api_key = api_key
        self._base = base or _DEFAULT_BASE

    # -- config (lazy so import never requires config) ---------------------- #
    def _cfg(self) -> tuple[str, str, str]:
        from app.config import config

        endpoint = self._endpoint_id or str(config.app.get("runpod_endpoint_id", "") or "")
        api_key = self._api_key or str(config.app.get("runpod_api_key", "") or "")
        if not endpoint or not api_key:
            raise BackendError(self.name, "runpod_endpoint_id / runpod_api_key not configured")
        return endpoint, api_key, self._base

    def _headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # -- verbs -------------------------------------------------------------- #
    def submit(self, spec: dict, *, transport: Transport) -> RenderJob:
        endpoint, api_key, base = self._cfg()
        resp = transport.request(
            "POST", f"{base}/{endpoint}/run", headers=self._headers(api_key), json={"input": spec}
        )
        if not ok(resp):
            raise BackendError(
                self.name, f"submit failed (HTTP {resp.status_code}): {safe_json(resp)}",
                retryable=int(getattr(resp, "status_code", 0)) >= 500,
            )
        body = safe_json(resp)
        ref = str(body.get("id") or "")
        if not ref:
            raise BackendError(self.name, f"submit returned no job id: {body}")
        state = normalize_state(body.get("status", "IN_QUEUE"), _STATE_MAP)
        job = RenderJob(
            id=spec.get("job_id") or ref,
            backend=self.name,
            workflow_version=str(spec.get("workflow_version", "") or ""),
            state=IN_QUEUE,
            provider_ref=ref,
            attempts=1,
        )
        return transition(job, state, provider_ref=ref)

    def poll(self, job: RenderJob, *, transport: Transport) -> RenderJob:
        if job.is_terminal:
            return job
        endpoint, api_key, base = self._cfg()
        resp = transport.request(
            "POST", f"{base}/{endpoint}/status/{job.provider_ref}", headers=self._headers(api_key)
        )
        if not ok(resp):
            raise BackendError(
                self.name, f"poll failed (HTTP {resp.status_code}): {safe_json(resp)}",
                retryable=int(getattr(resp, "status_code", 0)) >= 500,
            )
        body = safe_json(resp)
        state = normalize_state(body.get("status", ""), _STATE_MAP)
        outputs = _extract_outputs(body.get("output"), job_id=job.id) if state == COMPLETED else ()
        error = "" if state != FAILED else str(body.get("error") or body.get("output") or "failed")
        return transition(
            job, state,
            progress=1.0 if state == COMPLETED else None,
            output_refs=outputs if outputs else None,
            error=error,
        )

    def cancel(self, job: RenderJob, *, transport: Transport) -> RenderJob:
        if job.is_terminal:
            return job
        endpoint, api_key, base = self._cfg()
        transport.request(
            "POST", f"{base}/{endpoint}/cancel/{job.provider_ref}", headers=self._headers(api_key)
        )
        return transition(job, "CANCELLED")

    def warm(self, model: str, *, transport: Transport) -> bool:
        # RunPod keeps workers warm via min-workers config; nothing to prefetch here.
        return True


def _item_ref(item, *, job_id: str, index: int) -> str | None:
    """One worker output item -> a URL / R2 key, re-hosting inline base64 data."""
    if not item:
        return None
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in ("url", "video_url", "output_url", "s3_url", "key", "r2_key"):
        if item.get(key):
            return str(item[key])
    data = item.get("data")
    if isinstance(data, str) and data:
        import base64
        import binascii

        from app.services.render.outputs import rehost_bytes

        payload = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
        try:
            raw = base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            return None
        filename = str(item.get("filename") or f"output_{index}.mp4")
        return rehost_bytes(job_id, raw, filename)
    return None


def _extract_outputs(output, *, job_id: str = "") -> tuple[str, ...]:
    """Pull output URLs/keys from a variety of worker output shapes.

    Inline base64 items (``worker-comfyui`` without an S3 bucket) are uploaded to
    a private R2 key so the stored ref is always a playable key/URL, never a
    stringified dict.
    """
    if not output:
        return ()
    if isinstance(output, str):
        return (output,)
    if isinstance(output, dict):
        for key in ("url", "video_url", "output_url", "s3_url", "key", "r2_key"):
            if output.get(key):
                return (str(output[key]),)
        # worker-comfyui returns {"images"/"videos": [{"url"/"data": ...}]}
        for key in ("videos", "images", "outputs"):
            items = output.get(key)
            if isinstance(items, list):
                refs = [
                    ref for idx, item in enumerate(items)
                    if (ref := _item_ref(item, job_id=job_id, index=idx))
                ]
                if refs:
                    return tuple(refs)
    if isinstance(output, list):
        return tuple(
            ref for idx, item in enumerate(output)
            if (ref := _item_ref(item, job_id=job_id, index=idx))
        )
    return ()
    if isinstance(output, str):
        return (output,)
    if isinstance(output, dict):
        for key in ("url", "video_url", "output_url", "s3_url", "key", "r2_key"):
            if output.get(key):
                return (str(output[key]),)
        # worker-comfyui returns {"images"/"videos": [{"url"/"data": ...}]}
        for key in ("videos", "images", "outputs"):
            items = output.get(key)
            if isinstance(items, list):
                refs = [str(i.get("url") or i.get("key") or i) for i in items if i]
                if refs:
                    return tuple(refs)
    if isinstance(output, list):
        return tuple(str(x) for x in output if x)
    return ()


register_backend(RunPodBackend())
