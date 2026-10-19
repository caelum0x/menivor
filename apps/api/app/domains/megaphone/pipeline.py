"""Render briefs through Menivor's public API and publish them to media.menivor.com.

Dogfood rule: generation goes through the same HTTPS API a customer uses
(``x-api-key`` of the internal comp account): capture -> upload -> ``POST
/jobs`` -> ``POST /dub/videos``. Only publishing (copying the finished MP4 to
the public marketing bucket and writing the manifest) uses server-side R2
credentials, because customers download, we republish.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import requests
from loguru import logger

from app.domains.megaphone import codeclip, endcard
from app.domains.megaphone import manifest as mf
from app.domains.megaphone.briefs import Brief

DEFAULT_API_BASE = "https://api.menivor.com/api/v1"
USER_AGENT = "menivor-megaphone/1.0 (+https://menivor.com/made-with-menivor)"
MANIFEST_KEY = "megaphone/manifest.json"
MEDIA_CACHE = "public, max-age=31536000, immutable"
MANIFEST_CACHE = "public, max-age=600"
STATE_COMPLETE = 1
STATE_FAILED = -1


class MegaphoneError(RuntimeError):
    pass


def idempotency_key(brief: Brief) -> str:
    """Same brief + same look replays the job; a changed script or footage look re-renders."""
    look = f"codeclip-v{codeclip.VERSION}" if brief.footage_builder == "codeclip" else brief.footage_builder
    digest = hashlib.sha256(f"{brief.script}|{look}|{','.join(brief.footage_keys)}".encode()).hexdigest()[:10]
    return f"megaphone-{brief.id}-{digest}"


@dataclass
class ApiClient:
    """Thin client for the public Menivor API (internal comp account)."""

    api_key: str
    base: str = DEFAULT_API_BASE
    session: requests.Session = field(default_factory=requests.Session)
    sleep: Callable[[float], None] = time.sleep

    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
        return {"x-api-key": self.api_key, "User-Agent": USER_AGENT, **(extra or {})}

    def _call(self, method: str, path: str, *, body: Any = None, headers: Optional[Mapping[str, str]] = None,
              ok: tuple[int, ...] = (200,)) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(4):
            try:
                resp = self.session.request(method, f"{self.base}{path}", json=body,
                                            headers=self._headers(headers), timeout=60)
            except requests.RequestException as exc:
                last = exc
            else:
                if resp.status_code in ok:
                    payload = resp.json()
                    return payload.get("data", payload) if isinstance(payload, dict) else {}
                if resp.status_code not in (502, 503, 504, 429):
                    raise MegaphoneError(f"{method} {path} -> {resp.status_code}: {resp.text[:300]}")
                last = MegaphoneError(f"{method} {path} -> {resp.status_code}")
            self.sleep(15 * (attempt + 1))
        raise MegaphoneError(f"{method} {path} failed after retries: {last}")

    def me(self) -> dict[str, Any]:
        return self._call("GET", "/me")

    # -- footage ---------------------------------------------------------- #
    def capture(self, url: str, duration_s: int = 40, timeout_s: int = 600) -> str:
        """Record ``url`` (9:16) with Menivor Capture; returns the footage key."""
        data = self._call("POST", "/capture", body={
            "url": url, "kind": "website", "formats": ["9:16"], "duration_s": duration_s, "cursor": True,
        })
        cid = str(data.get("id") or "")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            data = self._call("GET", f"/capture/{cid}")
            status = data.get("status")
            if status == "succeeded":
                for output in data.get("outputs") or []:
                    if output.get("aspect") == "9:16" and output.get("key"):
                        return str(output["key"])
                raise MegaphoneError(f"capture {cid} finished without a 9:16 output")
            if status in ("failed", "canceled"):
                raise MegaphoneError(f"capture {cid} {status}: {data.get('error')}")
            self.sleep(10)
        raise MegaphoneError(f"capture {cid} timed out")

    def upload(self, path: str, content_type: str = "video/mp4") -> str:
        """Upload a local file via presign + PUT + register; returns the owned key."""
        size = os.path.getsize(path)
        data = self._call("POST", "/uploads/presign", body={
            "filename": os.path.basename(path), "content_type": content_type, "size": size,
        })
        with open(path, "rb") as fh:
            put = self.session.put(data["upload_url"], data=fh,
                                   headers={"Content-Type": content_type, **(data.get("headers") or {})},
                                   timeout=300)
        if put.status_code not in (200, 201, 204):
            raise MegaphoneError(f"upload PUT -> {put.status_code}")
        self._call("POST", "/uploads/register", body={"key": data["key"], "kind": "video"})
        return str(data["key"])

    # -- render ----------------------------------------------------------- #
    def create_reel(self, brief: Brief, *, screen_key: str = "", outro_key: str = "") -> str:
        params: dict[str, Any] = {
            "video_subject": brief.title[:200],
            "video_script": brief.script,
            "voice_name": "elevenlabs:pNInz6obpgDQGcFmaJgB",  # mapped to a free voice when premium is off
            "avatar_id": "",
            "avatar_provider": "heygen",
            "caption_style": "karaoke_yellow",
            "layout": "captions_only",
            "aspect": "9:16",
            "language": brief.language,
            "target_duration_s": 30,
            "platforms": [],
            "screen_recording_key": screen_key,
            "background_id": "" if screen_key else brief.background_id,
        }
        if outro_key:
            params["broll_outro_key"] = outro_key
        data = self._call("POST", "/jobs", body={
            "params": params, "voice_id": "pNInz6obpgDQGcFmaJgB", "caption_style": "karaoke_yellow", "variants": 1,
        }, headers={"Idempotency-Key": idempotency_key(brief)})
        return str(data["job_id"])

    def wait_reel(self, job_id: str, timeout_s: int = 1800) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            data = self._call("GET", f"/jobs/{job_id}")
            state = int(data.get("state") or 0)
            if state == STATE_COMPLETE:
                if not data.get("result_url"):
                    raise MegaphoneError(f"job {job_id} complete but no clean result (comp access missing?)")
                return data
            if state == STATE_FAILED:
                raise MegaphoneError(f"job {job_id} failed: {data.get('error')}")
            self.sleep(15)
        raise MegaphoneError(f"job {job_id} timed out")

    def dub(self, video_key: str, target: str, voice: str, source: str = "en", timeout_s: int = 1800) -> dict[str, Any]:
        data = self._call("POST", "/dub/videos", body={
            "video_key": video_key, "source_language": source, "target_language": target,
            "voice_engine": "edge", "voice": voice,
        })
        dub_id = str(data["dub_id"])
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            data = self._call("GET", f"/dub/videos/{dub_id}")
            if data.get("state") == "complete" and data.get("video_url"):
                return data
            if data.get("state") == "failed":
                raise MegaphoneError(f"dub {dub_id} failed: {data.get('error')}")
            self.sleep(20)
        raise MegaphoneError(f"dub {dub_id} timed out")


def download(url: str, path: str) -> str:
    with requests.get(url, stream=True, timeout=300, headers={"User-Agent": USER_AGENT}) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    if os.path.getsize(path) < 10_000:
        raise MegaphoneError(f"download too small: {url[:80]}")
    return path


def probe(path: str) -> tuple[float, int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", path], check=True, capture_output=True, text=True, timeout=60,
    ).stdout
    info = json.loads(out)
    stream = (info.get("streams") or [{}])[0]
    return float(info["format"]["duration"]), int(stream.get("width") or 0), int(stream.get("height") or 0)


def poster(video: str, out: str, at_s: float = 2.5) -> str:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at_s), "-i", video,
                    "-frames:v", "1", "-q:v", "3", "-vf", "scale=720:-2", out], check=True, timeout=60)
    return out


# --------------------------------------------------------------------------- #
# Publishing (public marketing bucket)
# --------------------------------------------------------------------------- #
class Publisher:
    def __init__(self, client: Any = None) -> None:
        if client is None:
            from app.platform.storage.r2 import get_public_media_client

            client = get_public_media_client()
        self._client = client

    @property
    def base(self) -> str:
        return str(self._client._public_base_url).rstrip("/")

    def put(self, path: str, key: str, content_type: str, cache: str = MEDIA_CACHE) -> str:
        with open(path, "rb") as fh:
            self._client._s3.put_object(Bucket=self._client._bucket, Key=key, Body=fh,
                                        ContentType=content_type, CacheControl=cache)
        return f"{self.base}/{key}"

    def put_json(self, key: str, payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
        self._client._s3.put_object(Bucket=self._client._bucket, Key=key, Body=body,
                                    ContentType="application/json; charset=utf-8", CacheControl=MANIFEST_CACHE)
        return f"{self.base}/{key}"

    def load_manifest(self) -> dict[str, Any]:
        try:
            obj = self._client._s3.get_object(Bucket=self._client._bucket, Key=MANIFEST_KEY)
            return json.loads(obj["Body"].read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - first run, or unreadable: start fresh
            logger.info(f"megaphone: no readable manifest yet ({type(exc).__name__})")
            return mf.empty()

    def write_manifest(self, manifest: Mapping[str, Any]) -> None:
        self.put_json(MANIFEST_KEY, manifest)
        for product in mf.PRODUCTS:
            self.put_json(f"megaphone/{product}.json", mf.for_product(manifest, product))


# --------------------------------------------------------------------------- #
# One brief end to end
# --------------------------------------------------------------------------- #
def footage_key(api: ApiClient, brief: Brief, work: str) -> str:
    if brief.footage_keys:
        return brief.footage_keys[0]
    if brief.footage_builder == "codeclip":
        return api.upload(codeclip.render(os.path.join(work, "code.mp4")))
    if brief.capture_url:
        try:
            return api.capture(brief.capture_url)
        except MegaphoneError as exc:
            logger.warning(f"megaphone: capture failed for {brief.id}, using stock background: {exc}")
    return ""


def render_brief(api: ApiClient, publisher: Publisher, brief: Brief, outro_keys: dict[str, str],
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"megaphone-{brief.product}-") as work:
        if brief.product not in outro_keys:
            outro_keys[brief.product] = api.upload(endcard.render(brief.product, os.path.join(work, "card.mp4")))
        screen = footage_key(api, brief, work)
        job_id = api.create_reel(brief, screen_key=screen, outro_key=outro_keys[brief.product])
        job = api.wait_reel(job_id)
        local = download(job["result_url"], os.path.join(work, "reel.mp4"))
        duration, width, height = probe(local)
        jpg = poster(local, os.path.join(work, "poster.jpg"))
        prefix = f"megaphone/{brief.product}/{brief.id}"
        video_url = publisher.put(local, f"{prefix}.mp4", "video/mp4")
        poster_url = publisher.put(jpg, f"{prefix}.jpg", "image/jpeg")
        dubs: list[dict[str, str]] = []
        if brief.dub_to:
            try:
                dub = api.dub(str(job.get("result_key") or f"jobs/{job_id}/final.mp4"), brief.dub_to, brief.dub_voice)
                dub_local = download(dub["video_url"], os.path.join(work, f"dub-{brief.dub_to}.mp4"))
                dubs.append({"language": brief.dub_to,
                             "video_url": publisher.put(dub_local, f"{prefix}.{brief.dub_to}.mp4", "video/mp4")})
            except MegaphoneError as exc:
                logger.warning(f"megaphone: dub failed for {brief.id}: {exc}")
        logger.info(f"megaphone: published {brief.id} ({duration:.1f}s) job={job_id}")
        return {
            "job_id": job_id,
            "entry": mf.entry(brief, video_url=video_url, poster_url=poster_url, duration_s=duration,
                              uploaded_at=now(), width=width or 1080, height=height or 1920, dubs=dubs),
        }
