"""HeyGen v2 audio-driven talking-head client + provider (§2.4).

HeyGen renders a lip-synced avatar clip from an EXTERNAL audio input — we never
use HeyGen's own TTS. The audio that drives the render is the SAME ElevenLabs
mp3 whose ``/with-timestamps`` alignment is the pipeline's single timing
authority (§8), so the returned render duration is validated against the
authoritative audio duration within ±0.25s.

Auth uses the ``X-Api-Key`` header (NOT a bearer token). All external I/O is
wrapped so failures return ``None``/``[]`` rather than crashing the pipeline.
"""

from __future__ import annotations

import os
import tempfile
import time

import requests
from loguru import logger

from app.config import config
from app.services.avatar.base import register_avatar_provider
from app.services import webhooks  # reuse the SSRF guard (§security)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DURATION_TOLERANCE_S: float = 0.25
_DEFAULT_TIMEOUT_S: float = 1800.0  # HeyGen hard cap: 30 minutes

# §5 Stage-3: render the avatar over a solid GREEN-SCREEN so the downstream
# compose stage has a consistent chroma key colour (compose keys 0x00FF00).
# HeyGen v2 expects a background as {"type": "color", "value": "#RRGGBB"}.
_GREENSCREEN_HEX: str = "#00FF00"
_GREENSCREEN_BACKGROUND: dict[str, str] = {"type": "color", "value": _GREENSCREEN_HEX}
_POLL_INTERVAL_S: float = 8.0
_HTTP_TIMEOUT_S: int = 60
_DOWNLOAD_TIMEOUT_S: int = 300

# Audio MIME types HeyGen accepts for the audio-driven voice input.
_ALLOWED_AUDIO_MIME: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}

# Image MIME types HeyGen accepts for a talking-photo (custom avatar from a
# creator's uploaded selfie). ``upload_image`` uploads the raw bytes with one of
# these ``Content-Type`` values (mirrors the audio upload contract).
_ALLOWED_IMAGE_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# Map a file extension -> the HeyGen image MIME the provider convenience should
# upload it with, so callers may pass a bare local path without a MIME.
_IMAGE_EXT_MIME: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

# Character kinds the video-generation call understands (§ custom-avatar): a
# HeyGen catalog/instant ``avatar`` or a creator-uploaded ``talking_photo``.
_CHARACTER_KIND_AVATAR: str = "avatar"
_CHARACTER_KIND_TALKING_PHOTO: str = "talking_photo"
_CHARACTER_KINDS: frozenset[str] = frozenset(
    {_CHARACTER_KIND_AVATAR, _CHARACTER_KIND_TALKING_PHOTO}
)

# Terminal + transient poll statuses returned by video_status.get.
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"
_STATUS_PENDING = {"pending", "waiting", "processing"}


def _heygen_config() -> dict:
    """Return the ``[heygen]`` config section defensively.

    The config section is added by the config layer (§3); read it via
    ``getattr`` so this module imports cleanly even if that wiring lands later.
    """
    section = getattr(config, "heygen", None)
    if section is None:
        return {}
    try:
        return dict(section)
    except Exception:  # noqa: BLE001 - non-mapping guard
        return {}


def _guess_image_mime(path: str) -> str:
    """Infer a HeyGen image MIME from a file extension (defaults to jpeg)."""
    _, ext = os.path.splitext(path.lower())
    return _IMAGE_EXT_MIME.get(ext, "image/jpeg")


class HeyGenError(RuntimeError):
    """Raised for non-recoverable HeyGen API responses (render failed)."""


class HeyGenClient:
    """Thin HeyGen v2 REST client (audio-driven avatar videos)."""

    UPLOAD: str = "https://upload.heygen.com/v1/asset"
    GEN: str = "https://api.heygen.com/v2/video/generate"
    STATUS: str = "https://api.heygen.com/v1/video_status.get"
    AVATARS: str = "https://api.heygen.com/v2/avatars"
    TALKING_PHOTO: str = "https://api.heygen.com/v2/talking_photo"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key: str = api_key if api_key is not None else _heygen_config().get("api_key", "")

    # -- headers ------------------------------------------------------------
    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"X-Api-Key": self.api_key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    # -- upload -------------------------------------------------------------
    def upload_audio(self, path: str, mime: str = "audio/wav") -> str:
        """Upload raw audio bytes and return the HeyGen ``asset_id``.

        HeyGen's upload endpoint takes the raw file body (NOT multipart) with
        the file's ``Content-Type``. Only mp3/wav are accepted.
        """
        if mime not in _ALLOWED_AUDIO_MIME:
            raise ValueError(
                f"unsupported audio mime '{mime}'; allowed: {sorted(_ALLOWED_AUDIO_MIME)}"
            )
        if not os.path.isfile(path):
            raise FileNotFoundError(f"audio file not found: {path}")

        with open(path, "rb") as fh:
            data = fh.read()

        resp = requests.post(
            self.UPLOAD,
            headers=self._headers(content_type=mime),
            data=data,
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json()
        asset_id = (body.get("data") or {}).get("id", "")
        if not asset_id:
            raise HeyGenError(f"heygen upload returned no asset id: {str(body)[:200]}")
        logger.info(f"heygen audio uploaded, asset_id={asset_id}")
        return asset_id

    # -- talking-photo (custom avatar from a photo) -------------------------
    def upload_image(self, path: str, mime: str = "image/jpeg") -> str:
        """Upload a raw image and return the HeyGen asset id (or url).

        Mirrors :meth:`upload_audio`: HeyGen's upload endpoint takes the raw
        file body (NOT multipart) with the file's ``Content-Type``. The returned
        asset reference is then handed to :meth:`create_talking_photo`. Only
        jpeg/png/webp are accepted.
        """
        if mime not in _ALLOWED_IMAGE_MIME:
            raise ValueError(
                f"unsupported image mime '{mime}'; allowed: {sorted(_ALLOWED_IMAGE_MIME)}"
            )
        if not os.path.isfile(path):
            raise FileNotFoundError(f"image file not found: {path}")

        with open(path, "rb") as fh:
            data = fh.read()
        if not data:
            raise HeyGenError(f"image file is empty: {path}")

        resp = requests.post(
            self.UPLOAD,
            headers=self._headers(content_type=mime),
            data=data,
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        node = body.get("data") or {}
        # HeyGen's asset response carries the id; fall back to the hosted url so
        # ``create_talking_photo`` can reference the image either way.
        asset_ref = str(node.get("id") or node.get("url") or "").strip()
        if not asset_ref:
            raise HeyGenError(f"heygen image upload returned no asset id: {str(body)[:200]}")
        logger.info(f"heygen image uploaded, asset_ref={asset_ref}")
        return asset_ref

    def create_talking_photo(self, image_asset_or_url: str) -> str:
        """Create a talking-photo avatar and return its ``talking_photo_id``.

        Takes the reference returned by :meth:`upload_image` — either a HeyGen
        asset id or a hosted image URL — and calls HeyGen's talking-photo
        creation endpoint. The returned ``talking_photo_id`` is what drives video
        generation via ``character={'type':'talking_photo', ...}``.

        If HeyGen accepts the image but does not mint a distinct id (some flows
        let the uploaded image act as the talking photo directly), the supplied
        reference is returned as the id. HTTP failures still raise.
        """
        ref = (image_asset_or_url or "").strip()
        if not ref:
            raise ValueError("create_talking_photo requires an image asset id or url")

        if ref.startswith("http://") or ref.startswith("https://"):
            payload: dict[str, str] = {"image_url": ref}
        else:
            payload = {"image_asset_id": ref}

        resp = requests.post(
            self.TALKING_PHOTO,
            headers=self._headers(),
            json=payload,
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        if body.get("error"):
            raise HeyGenError(f"heygen talking_photo error: {str(body['error'])[:200]}")

        node = body.get("data") or {}
        talking_photo_id = str(
            node.get("talking_photo_id") or node.get("id") or ""
        ).strip()
        if not talking_photo_id:
            # HeyGen accepted the image but returned no distinct id: treat the
            # uploaded reference itself as the talking-photo id (documented
            # "image acts as the talking_photo" case).
            logger.info(
                "heygen talking_photo creation returned no distinct id; "
                "using the uploaded image reference as the talking_photo_id"
            )
            return ref
        logger.info(f"heygen talking_photo created, talking_photo_id={talking_photo_id}")
        return talking_photo_id

    # -- generate -----------------------------------------------------------
    def create_avatar_video(
        self,
        *,
        character: dict,
        voice: dict,
        background: dict | None = None,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
        """Create an audio-driven avatar video, returning the ``video_id``.

        ``voice`` MUST be an EXTERNAL audio input: ``{'type': 'audio', ...}``
        carrying EXACTLY ONE of ``audio_url`` / ``audio_asset_id`` (boundary
        validation per §2.4). HeyGen TTS voice types are rejected.

        The render is FORCED onto a solid green-screen background (§5 Stage-3)
        so the compose stage's chroma key always sees the same key colour. A
        caller MAY still override this by passing an explicit ``background``.
        """
        self._validate_audio_voice(voice)

        video_input: dict = {
            "character": character,
            "voice": voice,
            "background": background if background is not None else dict(_GREENSCREEN_BACKGROUND),
        }

        payload = {
            "video_inputs": [video_input],
            "dimension": {"width": width, "height": height},
        }
        resp = requests.post(
            self.GEN,
            headers=self._headers(),
            json=payload,
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("error"):
            raise HeyGenError(f"heygen generate error: {str(body['error'])[:200]}")
        video_id = (body.get("data") or {}).get("video_id", "")
        if not video_id:
            raise HeyGenError(f"heygen generate returned no video_id: {str(body)[:200]}")
        logger.info(f"heygen video queued, video_id={video_id}")
        return video_id

    @staticmethod
    def _validate_audio_voice(voice: dict) -> None:
        if not isinstance(voice, dict) or voice.get("type") != "audio":
            raise ValueError("voice must be an external audio input: {'type': 'audio', ...}")
        has_url = bool(voice.get("audio_url"))
        has_asset = bool(voice.get("audio_asset_id"))
        if has_url == has_asset:  # both or neither
            raise ValueError(
                "voice requires EXACTLY ONE of 'audio_url' or 'audio_asset_id'"
            )

    # -- poll ---------------------------------------------------------------
    def wait(
        self,
        video_id: str,
        *,
        interval: float = _POLL_INTERVAL_S,
        timeout: float = _DEFAULT_TIMEOUT_S,
    ) -> dict:
        """Poll ``video_status.get`` until completion.

        Returns the terminal ``data`` dict on ``completed``. Raises
        ``HeyGenError`` on ``failed`` and ``TimeoutError`` once the 30-min hard
        cap is exceeded. Transient HTTP errors while polling are tolerated
        until the deadline.
        """
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"heygen render timed out after {timeout:.0f}s (video_id={video_id})"
                )
            try:
                resp = requests.get(
                    self.STATUS,
                    headers=self._headers(content_type=None),
                    params={"video_id": video_id},
                    timeout=_HTTP_TIMEOUT_S,
                )
                resp.raise_for_status()
                data = (resp.json() or {}).get("data") or {}
            except Exception as exc:  # noqa: BLE001 - transient poll error
                logger.warning(f"heygen status poll error (retrying): {exc}")
                time.sleep(interval)
                continue

            status = data.get("status", "")
            if status == _STATUS_COMPLETED:
                logger.success(f"heygen render complete, video_id={video_id}")
                return data
            if status == _STATUS_FAILED:
                reason = data.get("error") or data.get("msg") or "unknown"
                raise HeyGenError(f"heygen render failed (video_id={video_id}): {reason}")

            if status and status not in _STATUS_PENDING:
                logger.debug(f"heygen unexpected status '{status}', continuing to poll")
            time.sleep(interval)

    # -- avatars ------------------------------------------------------------
    def list_avatars(self) -> list[dict]:
        """Return HeyGen's avatar catalog (raises on HTTP error)."""
        resp = requests.get(
            self.AVATARS,
            headers=self._headers(content_type=None),
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        avatars = data.get("avatars")
        if isinstance(avatars, list):
            return avatars
        # Some responses return the list directly under data.
        return data if isinstance(data, list) else []


class HeyGenProvider:
    """``TalkingHeadProvider`` implementation backed by :class:`HeyGenClient`."""

    name: str = "heygen"

    def __init__(self) -> None:
        self._api_key: str = _heygen_config().get("api_key", "")
        self._client: HeyGenClient = HeyGenClient(self._api_key)

    def is_enabled(self) -> bool:
        return bool(self._api_key)

    def list_avatars(self) -> list[dict]:
        try:
            return self._client.list_avatars()
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.error(f"heygen list_avatars failed: {exc}")
            return []

    def create_talking_photo(self, image_path: str, *, mime: str | None = None) -> str | None:
        """Turn a local photo into a HeyGen talking-photo avatar.

        Uploads the image as an asset and creates the talking-photo, returning
        its ``talking_photo_id`` (persisted as an ``AvatarPreset``'s
        ``provider_avatar_id`` so the avatar appears in ``GET /v1/avatars``).
        ``mime`` is inferred from the file extension when omitted. Degrades to
        ``None`` on any failure (Protocol contract: never raise on external I/O).
        """
        if not self.is_enabled():
            logger.error("heygen provider is not enabled (missing api_key)")
            return None
        if not image_path:
            logger.error("heygen create_talking_photo requires an image path")
            return None

        resolved_mime = mime or _guess_image_mime(image_path)
        try:
            asset_ref = self._client.upload_image(image_path, mime=resolved_mime)
            talking_photo_id = self._client.create_talking_photo(asset_ref)
        except Exception as exc:  # noqa: BLE001 - external I/O -> graceful None
            logger.error(f"heygen create_talking_photo failed: {exc}")
            return None

        if not talking_photo_id:
            logger.error("heygen create_talking_photo produced no talking_photo_id")
            return None
        logger.success(f"heygen talking photo ready, talking_photo_id={talking_photo_id}")
        return talking_photo_id

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
        character_kind: str = _CHARACTER_KIND_AVATAR,
    ) -> dict | None:
        """Render a lip-synced avatar clip from an external R2 audio URL.

        Uses ``voice={'type':'audio','audio_url': audio_url}`` to skip the
        upload hop. ``character_kind`` selects the driven subject: the default
        ``'avatar'`` builds a ``{'type':'avatar','avatar_id': ...}`` character,
        while ``'talking_photo'`` builds a
        ``{'type':'talking_photo','talking_photo_id': ...}`` character (a custom
        avatar created from a creator's uploaded photo). In both cases
        ``avatar_id`` carries the provider id.

        Polls to completion, downloads the short-lived signed output URL to a
        local temp file, re-hosts it on R2, and validates the render duration
        against ``expected_duration_s`` (§8, ±0.25s).

        Returns ``{'avatar_video','duration','provider_video_id'}`` (plus
        best-effort ``avatar_url``/``avatar_key`` from the re-host) or ``None``.
        """
        if not self.is_enabled():
            logger.error("heygen provider is not enabled (missing api_key)")
            return None
        if not audio_url:
            logger.error("heygen generate_avatar requires a public audio_url")
            return None
        if not avatar_id:
            logger.error("heygen generate_avatar requires an avatar_id")
            return None

        character = self._build_character(avatar_id, character_kind)
        voice = {"type": "audio", "audio_url": audio_url}

        data = self._render_with_retry(
            character=character,
            voice=voice,
            background=background,
            width=width,
            height=height,
            timeout_s=timeout_s,
        )
        if data is None:
            return None

        video_id = data.get("video_id", "") or ""
        video_url = data.get("video_url", "") or ""
        # ``None`` when HeyGen's completed-status payload omits/uncoercibly
        # reports ``duration`` — kept distinct from ``expected_duration_s`` so
        # the §8 drift gate never compares the expected value against itself.
        duration = self._coerce_duration(data.get("duration"))
        if not video_url:
            logger.error(f"heygen render completed without a video_url (video_id={video_id})")
            return None

        self._validate_duration(duration, expected_duration_s)

        local_path = self._download_to_temp(video_url, video_id)
        if local_path is None:
            return None

        result: dict = {
            "avatar_video": local_path,
            "duration": duration,
            "provider_video_id": video_id,
        }
        rehosted = self._rehost(local_path, video_id)
        if rehosted:
            result.update(rehosted)
        return result

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _build_character(avatar_id: str, character_kind: str) -> dict:
        """Build the HeyGen v2 ``character`` payload for the requested kind.

        ``'talking_photo'`` drives a creator-uploaded photo avatar; anything
        else (the default) drives a catalog/instant avatar. An unrecognised kind
        is coerced to ``'avatar'`` with a warning rather than sending an invalid
        character type to HeyGen.
        """
        kind = character_kind if character_kind in _CHARACTER_KINDS else _CHARACTER_KIND_AVATAR
        if kind != character_kind:
            logger.warning(
                f"unknown character_kind '{character_kind}', "
                f"falling back to '{_CHARACTER_KIND_AVATAR}'"
            )
        if kind == _CHARACTER_KIND_TALKING_PHOTO:
            return {"type": "talking_photo", "talking_photo_id": avatar_id}
        return {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"}

    def _render_with_retry(
        self,
        *,
        character: dict,
        voice: dict,
        background: dict | None,
        width: int,
        height: int,
        timeout_s: float,
    ) -> dict | None:
        """Create + wait; retry once on a transient render ``failed``."""
        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + one retry
            try:
                video_id = self._client.create_avatar_video(
                    character=character,
                    voice=voice,
                    background=background,
                    width=width,
                    height=height,
                )
                return self._client.wait(video_id, timeout=timeout_s)
            except TimeoutError as exc:
                logger.error(f"heygen render timed out: {exc}")
                return None  # do not retry a full 30-min timeout
            except HeyGenError as exc:
                last_exc = exc
                logger.warning(f"heygen render failed (attempt {attempt + 1}/2): {exc}")
            except Exception as exc:  # noqa: BLE001 - HTTP/network failure
                last_exc = exc
                logger.warning(f"heygen render error (attempt {attempt + 1}/2): {exc}")
        logger.error(f"heygen render exhausted retries: {last_exc}")
        return None

    @staticmethod
    def _coerce_duration(raw: object) -> float | None:
        """Parse HeyGen's reported render ``duration`` to a float, or ``None``.

        Returns ``None`` when HeyGen omitted the field or reported a
        non-numeric value, so callers can distinguish an *unverifiable* render
        from a genuine numeric report and never treat the expected audio
        duration as if HeyGen had confirmed it (§8). Fabricating the expected
        value here would make the downstream drift gate compare a value against
        itself and pass unconditionally.
        """
        if raw is None:
            return None
        try:
            return float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_duration(actual: float | None, expected: float | None) -> None:
        if expected is None:
            return
        if actual is None or actual <= 0:
            # HeyGen gave us no usable duration, so the §8 tolerance gate
            # cannot run. Warn loudly instead of silently passing — a truncated
            # render would otherwise slip through the drift gate undetected.
            logger.warning(
                "heygen render duration could not be verified against §8 "
                f"tolerance: status payload carried no usable 'duration' field "
                f"(expected={expected:.3f}s)"
            )
            return
        delta = abs(actual - expected)
        if delta > _DURATION_TOLERANCE_S:
            logger.warning(
                "heygen render duration drift beyond tolerance: "
                f"expected={expected:.3f}s actual={actual:.3f}s "
                f"delta={delta:.3f}s (tol=±{_DURATION_TOLERANCE_S}s)"
            )

    @staticmethod
    def _download_to_temp(video_url: str, video_id: str) -> str | None:
        """Download the signed HeyGen output URL to a local temp mp4.

        SSRF hardening: ``video_url`` is taken verbatim from HeyGen's
        status-poll response, so it is treated as UNTRUSTED. Before fetching we
        reuse the webhook SSRF guard to (1) enforce an ``http``/``https`` scheme,
        (2) refuse loopback / link-local / RFC-1918 / reserved targets —
        including the ``169.254.169.254`` cloud-metadata endpoint — and blocked
        hostnames, and (3) DNS-pin the vetted address to close the rebinding
        TOCTOU. Redirects are disabled (``allow_redirects=False``) so a crafted
        3xx cannot bounce the fetch onto an unvalidated internal host.
        """
        url_error, pinned_ip = webhooks._validate_and_resolve(video_url)
        if url_error is not None:
            logger.error(
                f"refusing to download heygen avatar (video_id={video_id}): {url_error}"
            )
            return None

        session = requests.Session()
        try:
            adapter_cls = webhooks._PinnedHTTPAdapter
            if pinned_ip and adapter_cls is not None:
                adapter = adapter_cls(pinned_ip)
                session.mount("http://", adapter)
                session.mount("https://", adapter)

            resp = session.get(
                video_url,
                stream=True,
                timeout=_DOWNLOAD_TIMEOUT_S,
                allow_redirects=False,
            )
            if 300 <= resp.status_code < 400:
                logger.error(
                    "refusing to follow heygen download redirect "
                    f"(video_id={video_id}): status={resp.status_code}"
                )
                return None
            resp.raise_for_status()

            suffix = f"_{video_id}.mp4" if video_id else ".mp4"
            fd, local_path = tempfile.mkstemp(prefix="heygen_avatar", suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
            logger.info(f"heygen avatar downloaded to {local_path}")
            return local_path
        except Exception as exc:  # noqa: BLE001 - network/disk failure
            logger.error(f"failed to download heygen avatar (video_id={video_id}): {exc}")
            return None
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

    @staticmethod
    def _rehost(local_path: str, video_id: str) -> dict:
        """Re-host the rendered clip on R2 (signed HeyGen URLs expire fast).

        Best-effort: returns ``{'avatar_key','avatar_url'}`` on success, or an
        empty dict if storage is unavailable (the local path still lets the
        compose stage proceed).
        """
        try:
            from app.services.storage.r2 import r2_client

            key = f"avatars/{video_id or os.path.basename(local_path)}.mp4"
            url = r2_client.upload_file(local_path, key, "video/mp4")
            logger.info(f"heygen avatar re-hosted to R2: {key}")
            return {"avatar_key": key, "avatar_url": url}
        except Exception as exc:  # noqa: BLE001 - storage optional at this layer
            logger.warning(f"failed to re-host heygen avatar on R2 (continuing): {exc}")
            return {}


# Self-register at import so ``get_avatar_provider('heygen')`` resolves.
register_avatar_provider(HeyGenProvider())
