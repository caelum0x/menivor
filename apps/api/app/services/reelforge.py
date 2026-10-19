"""ReelForge stage functions + params DTO (INTEGRATION_CONTRACT.md §2.8).

This module is intentionally *thin*: it owns the frozen :class:`ReelForgeParams`
data-transfer object and the six pure stage transforms that make up the
canonical DAG ``script → tts → {avatar ∥ captions} → compose → upload``.

Each stage function is a pure transform over the shared, JSON-serializable
``JobContext`` dict (see §6.2). It reuses the real MPT/ReelForge services rather
than reimplementing them:

- :func:`app.services.script.ugc.generate_ugc_script`
- :func:`app.services.voice.tts` + :func:`app.services.voice.get_audio_duration`
- :func:`app.services.avatar.get_avatar_provider`
- :func:`app.services.captions.words.group_words_into_phrases`
- :func:`app.services.captions.ass_karaoke.write_ass`
- :func:`app.services.captions.presets.get_caption_style`
- :func:`app.services.music.get_music_path`
- :func:`app.services.compose.compose_ffmpeg.compose_avatar_over_screen`
- :func:`app.services.preview.generate_poster` + :func:`app.services.preview.generate_preview_clip`
- :func:`app.services.upload_post.cross_post_video`
- :func:`app.services.webhooks.deliver_webhook`
- :mod:`app.services.storage.r2` for object storage.

All imports of those services are performed lazily *inside* the functions so
importing this module never drags in boto3, ffmpeg, litellm or the network
stack — keeping it safe to import from Celery task registration, the API layer
and unit tests alike.

Timing authority (§8): ``stage_tts`` computes the single authoritative
``audio_duration`` from the ElevenLabs alignment (via
``voice.get_audio_duration(sub_maker)``) and flattens ``sub_maker.words`` to a
plain ``list[[text, start, end]]``. Both the caption timeline and the avatar
duration validation are derived from that one number/array — never independently.

Error model: external-I/O failures inside the reused services already return
``None``/error-envelopes. A stage raises :class:`ReelForgeStageError` (a
``RuntimeError`` subclass) when a required upstream artifact is missing so the
Celery task wrapper can catch it, mark the job failed (first-failure guard) and
stop the chain — it never lets a raw provider exception escape unlabelled.
"""

from __future__ import annotations

import functools
import os
import subprocess
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import Any

from loguru import logger

__all__ = [
    "ReelForgeParams",
    "ReelForgeStageError",
    "stage_avatar",
    "stage_captions",
    "stage_compose",
    "stage_script",
    "stage_tts",
    "stage_upload",
]

# §5 Stage-3 / §8: the avatar render duration must agree with the authoritative
# audio_duration within this tolerance. CTO spec: abs(avatar_duration -
# audio_duration) must be < 0.15s, else the stage FAILS (retryable) — not merely
# warns. On drift we log, record a warning JobEvent for telemetry, THEN raise a
# ``ReelForgeStageError`` so the Celery task retries the render.
_AVATAR_DRIFT_TOLERANCE_S: float = 0.15

# §5d ToS / AI-disclosure. Platform ToS (YouTube, TikTok, Instagram) require
# creators to flag AI/synthetic media. YouTube has a dedicated
# ``containsSyntheticMedia`` field (set in ``upload_post``); the other platforms
# only receive the shared caption, so we append this human-readable note there
# when ``params.tos_disclosure`` is enabled.
_AI_DISCLOSURE_NOTE: str = "This video was created with AI."

# §6 Creator Studio previews: after a successful compose we produce two
# lightweight derivatives (a poster JPEG + a short teaser MP4) for the studio
# gallery. These are best-effort — a preview failure must NEVER fail the job —
# so their keys are empty strings when generation/upload could not complete.
_PREVIEW_POSTER_AT_S: float = 1.0    # timestamp to grab the poster frame from
_PREVIEW_CLIP_DURATION_S: float = 5.0  # length of the hover-preview teaser clip

# Brand Watermark: when a job resolves to an enabled brand logo, the compose
# stage overlays it at this corner/opacity by default. Applying the watermark is
# ALWAYS best-effort — any failure (no DB, missing brand, R2 download error)
# logs a warning and composes WITHOUT it, never failing the job.
_DEFAULT_WATERMARK_POSITION: str = "bottom_right"
_DEFAULT_WATERMARK_OPACITY: float = 0.85

# Bring Your Own Voiceover: map an uploaded narration's file extension to a MIME
# content type for the R2 re-host (the avatar provider needs a public URL with a
# sensible type). Unknown/blank extensions fall back to ``audio/mpeg``.
_AUDIO_CONTENT_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}
_DEFAULT_AUDIO_CONTENT_TYPE: str = "audio/mpeg"

# Custom Avatar from a Photo: the avatar provider's ``generate_avatar`` accepts a
# ``character_kind`` selecting the driven subject — a HeyGen catalog/instant
# ``avatar`` (the default) or a creator-uploaded ``talking_photo`` (a selfie
# turned into a talking-photo avatar). The kind is derived SOLELY from the
# persisted :class:`AvatarPreset`'s ``config.kind`` (never client params), so a
# stock render can never be spoofed into a talking-photo render and vice versa.
_CHARACTER_KIND_AVATAR: str = "avatar"
_CHARACTER_KIND_TALKING_PHOTO: str = "talking_photo"


# --------------------------------------------------------------------------- #
# Params DTO (§2.8 — exact fields, order and defaults)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ReelForgeParams:
    """Immutable job parameters for a single ReelForge avatar reel."""

    video_subject: str
    video_script: str = ""                    # optional manual script; else LLM-generated
    translate_source_script: str = ""         # dubbing: translate this into `language` instead of generating
    voice_name: str = ""                      # "elevenlabs:<voice_id>"
    voice_rate: float = 1.0
    avatar_id: str = ""
    avatar_provider: str = "heygen"
    caption_style: str = "karaoke_yellow"     # id resolved via captions.presets.get_caption_style
    layout: str = "pip"                       # pip | hook_intro | split
    aspect: str = "9:16"
    language: str = "auto"
    target_duration_s: int = 30
    platforms: tuple[str, ...] = ()           # empty => skip upload stage
    youtube_privacy_status: str = "private"
    screen_recording_key: str = ""            # R2 key of the uploaded screen recording (optional)
    background_id: str = ""                    # curated background-library id; materialized into a looping companion track when no screen_recording_key (content.background_library)
    variants: int = 1                         # §5a batch size (1..3); fan-out happens at the API layer
    tos_disclosure: bool = False              # §5d mark output as AI/synthetic media on cross-post
    music_id: str = ""                        # background-music track id (music.get_music_path); "" => none
    music_prompt: str = ""                     # AI-BGM text prompt; non-empty => generate a custom track ("" => none)
    bgm_provider: str = ""                     # AI-BGM provider: "elevenlabs" | "sonilo" ("" => first enabled)
    webhook_url: str = ""                      # optional job-completion callback URL ("" => skip)
    webhook_secret: str = ""                   # optional HMAC-SHA256 signing key for the webhook body
    # Brand Watermark per-job overrides. A per-user UserBrand (logo_key +
    # position + opacity + enabled) is applied by default; these let a single job
    # override or disable it. ``None``/'' means "fall back to the user brand
    # default" for that field, so an unset override is invisible.
    watermark_key: str = ""                     # override logo R2 key ("" => use the user brand's)
    watermark_position: str = ""                # override corner ("" => use brand/default)
    watermark_opacity: float | None = None      # override opacity (None => use brand/default)
    watermark_enabled: bool | None = None       # per-job toggle (None => use brand.enabled; False disables)
    # AI B-roll cutaways (optional creative overlay). A chosen stock clip is
    # spliced as a brief, MUTED intro (before the hook) and/or outro (after)
    # around the composed reel; the main reel keeps its full audio + captions.
    # Each key is client-supplied, so it is validated against the caller's own
    # job by the same ownership guard used for screen_recording_key/watermark_key.
    # Applying b-roll is ALWAYS best-effort — a failure never fails the job.
    broll_intro_key: str = ""                    # R2 key of a muted intro cutaway ("" => none)
    broll_outro_key: str = ""                    # R2 key of a muted outro cutaway ("" => none)
    # Bring Your Own Voiceover (BYOV). When set, the creator's OWN uploaded
    # narration audio (this R2 key) becomes the reel's narration instead of TTS /
    # voice-clone. ``stage_tts`` then skips ElevenLabs entirely: it downloads this
    # audio, transcribes it with faster-whisper (``transcribe.transcribe_to_words``)
    # for the §8 single-authority WORD timings, and re-hosts the audio so the
    # avatar has a public URL. The key is client-supplied, so it is validated by
    # the same BOLA guard used for ``screen_recording_key`` / ``watermark_key``.
    voiceover_key: str = ""                       # R2 key of the user's uploaded narration ("" => use TTS)
    # Auto-tighten (Submagic-style "Remove Silences" retention pre-step). When
    # True the raw SCREEN RECORDING (and its own native audio track) is run
    # through the pure-FFmpeg ``app.services.editing.tighten`` pass to remove dead
    # air (silent AND static stretches) BEFORE the existing compose smart-handling
    # (freezedetect trim + setpts speed-ramp-to-script). The pass is best-effort
    # and degrade-safe (it never raises and returns the original untouched on any
    # problem) and NEVER touches the voiceover/caption timeline — the final reel
    # duration is still governed downstream by the script/TTS, so the caption
    # drift gate is unaffected. Defaults to False (byte-for-byte the current path).
    auto_tighten: bool = False
    # Editing-polish suite (opt-in, default-off, degrade-safe pre-compose passes;
    # no migration — each is persisted in ``Job.params`` via this DTO). They run
    # ONLY on the background SCREEN recording / AVATAR clip, never on the
    # voiceover/caption timeline (the ElevenLabs/whisper WORD timings remain the
    # single source of truth), so the golden caption-drift gate (<=50ms) is
    # unaffected with any flag on. All three are best-effort and degrade to the
    # ORIGINAL clip on any failure, so an enabled flag can never fail the job.
    #
    # ``auto_zoom`` — scene-driven "punch-in" zooms baked into the screen
    #   recording (``app.services.editing.auto_zoom``). Duration-preserving.
    auto_zoom: bool = False
    # ``camera_motion`` — synthetic "fake camera motion" preset baked into the
    #   screen recording (``app.services.editing.motion``): one of ``none`` (the
    #   default no-op), ``ken_burns``, ``push_in``, ``pull_out`` or ``whip_pan``.
    #   Duration-preserving (an overlay transform, never a cut).
    camera_motion: str = "none"
    # ``remove_bg`` — neural background matting of the AVATAR clip
    #   (``app.services.editing.matte``, OPTIONAL rembg dep). Composites the
    #   cut-out over solid chroma green so the existing compose chromakey keys it
    #   spill-free. Degrades to the raw chromakey path when rembg is absent.
    remove_bg: bool = False
    # Higgsfield-class Effects Mix (compose-stage VFX render). ``effects`` is a
    # validated, deduped, capped tuple of reviewed VFX preset ids
    # (``app.domains.catalog.presets``) rendered into the compose filtergraph
    # between ``[comp]`` and the caption burn (``app.services.compose.vfx``), so
    # effects sit UNDER the karaoke captions. ``vfx_intensity`` (0..100) scales
    # the selected camera-motion + VFX fragments. Filter-class effects render as
    # pure FFmpeg filters now; overlay-class effects (explosion/rain…) are cleanly
    # deferred to the overlay pipeline. Tuple (not list) to keep the frozen
    # dataclass immutable, mirroring ``platforms``. Defaults are the no-op path.
    effects: tuple[str, ...] = ()
    vfx_intensity: int = 50
    # Opening-hook angle for a GENERATED script (``app.domains.experiments.
    # hook_styles``): one of ``pov`` | ``question`` | ``nobody_tells_you`` |
    # ``stat`` | ``story``; "" => the model picks freely. A multi-variant run
    # assigns each variant a different style so the N reels are guaranteed to
    # open differently (1 body / N hooks). Ignored when a manual/translated
    # script is supplied — that script's own first line is the hook.
    hook_style: str = ""
    # One-click reel style (``app.domains.styles.catalog``): "" => none. The job
    # API folds the style's layout/caption/background/hook defaults into these
    # params; compose builds the style's visual track (split-screen, meme band,
    # anime scenes, before/after ...) when no footage was uploaded.
    style: str = ""
    # The pasted page a link run was written from ("" => none). Only used to
    # fetch the page's own preview image (SSRF-safe) for a style's visuals.
    source_url: str = ""


class ReelForgeStageError(RuntimeError):
    """Raised when a stage cannot produce its required artifact.

    Carries the ``stage`` name so the Celery wrapper can record it against the
    job (``JobRepository.mark_failed``) without re-parsing the message.
    """

    def __init__(self, stage: str, message: str) -> None:
        self.stage = stage
        super().__init__(f"[{stage}] {message}")


# --------------------------------------------------------------------------- #
# Internal helpers (lazy — no module-level heavy imports)
# --------------------------------------------------------------------------- #
def _workdir(job_id: str) -> str:
    """Return (creating if needed) a per-job scratch directory under storage/."""
    from app.utils import utils

    safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in ("-", "_")) or "job"
    return utils.task_dir(os.path.join("reelforge", safe))


def _r2():
    """Return the process-wide R2 client (lazy singleton)."""
    from app.services.storage.r2 import get_r2_client

    return get_r2_client()


def _download_from_r2(key: str, dest_path: str, expires: int = 900) -> str:
    """Download an R2 object to ``dest_path`` and return the local path.

    Uses a short-lived presigned GET URL (no dependency on public bucket
    access) streamed to disk. Raises on failure so the caller can convert it
    into a typed stage error with context.
    """
    import requests

    url = _r2().presign_get(key, expires=expires)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
    return dest_path


def _key_job_ref(key: str) -> str | None:
    """Return the ``<job_id>`` a ``jobs/<job_id>/...`` R2 key belongs to, else None.

    Per-job artifacts live under the ``jobs/<job_id>/`` prefix (audio.mp3,
    avatar.mp4, captions.ass, final.mp4, poster.jpg, ...). Any other prefix
    (notably ``uploads/<uuid4>`` client uploads) is not a per-job artifact and
    is returned as ``None`` so the ownership guard leaves it alone.
    """
    parts = str(key or "").strip().lstrip("/").split("/")
    if len(parts) >= 2 and parts[0] == "jobs" and parts[1]:
        return parts[1]
    return None


def _assert_owned_r2_key(job_id: str, key: str) -> None:
    """Guard a *user-supplied* R2 key against cross-tenant access (IDOR/BOLA).

    ``ReelForgeParams.screen_recording_key`` and ``ReelForgeParams.watermark_key``
    are set verbatim by the client, so a caller could otherwise reference another
    creator's per-job artifact (``jobs/<victim_job_id>/final.mp4`` etc.) and have
    the server presign+download it. This mirrors the brand controller's
    ``_verify_logo_ownership`` BOLA guard: a key that resolves into the
    ``jobs/<ref>/`` namespace is only allowed when ``<ref>`` is *this* job or
    another job owned by the SAME user; every non-``jobs/`` prefix is a
    user-scoped, non-enumerable upload namespace and is permitted.

    Fails **closed**: if a cross-job reference cannot be verified against its
    owner (no DB, missing rows, transient error), the key is rejected. Raises
    :class:`PermissionError` on violation; callers convert it into the
    appropriate typed error / best-effort skip.
    """
    ref = _key_job_ref(key)
    if ref is None or ref == job_id:
        return

    owner: str | None = None
    ref_owner: str | None = None
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            repo = JobRepository(session)
            this_job = repo.get(job_id)
            ref_job = repo.get(ref)
            owner = None if this_job is None else str(this_job.user_id)
            ref_owner = None if ref_job is None else str(ref_job.user_id)
    except Exception as exc:  # noqa: BLE001 - fail closed on any lookup error
        logger.warning(
            f"[{job_id}] could not verify ownership of R2 key {key!r}: {exc}"
        )

    if owner is not None and ref_owner is not None and owner == ref_owner:
        return

    raise PermissionError(
        f"R2 key {key!r} does not belong to the owner of job {job_id!r}"
    )


def _ensure_local(path: str, fallback_key: str, dest_path: str) -> str:
    """Return a usable local path.

    Prefer an already-present local ``path`` (same-worker fast path per §6.2);
    otherwise re-materialize it from its R2 ``fallback_key`` (distributed
    worker path). Raises if neither is available.
    """
    if path and os.path.isfile(path):
        return path
    if fallback_key:
        logger.info(f"re-hydrating {fallback_key!r} from R2 -> {dest_path}")
        return _download_from_r2(fallback_key, dest_path)
    raise FileNotFoundError(
        f"no local file at {path!r} and no R2 key to recover it"
    )


def _with_disclosure(text: str) -> str:
    """Append the AI/synthetic-media disclosure note to ``text`` (idempotent).

    Used for platforms that only receive the shared caption/description (§5d).
    Returns the note alone when ``text`` is empty and leaves the text untouched
    if the note is already present (case-insensitive), so re-publishing does not
    stack duplicate disclosures.
    """
    body = (text or "").strip()
    if _AI_DISCLOSURE_NOTE.lower() in body.lower():
        return body
    return f"{body} {_AI_DISCLOSURE_NOTE}".strip()


def _resolution(aspect: str) -> tuple[int, int]:
    """Map the params aspect string to a (width, height) resolution."""
    from app.models.schema import VideoAspect

    try:
        return VideoAspect(aspect).to_resolution()
    except (ValueError, KeyError):
        logger.warning(f"unknown aspect {aspect!r}; defaulting to portrait 1080x1920")
        return 1080, 1920


# Avatar-less "captions-only" layout id (mirrors
# ``compose_ffmpeg.CAPTIONS_ONLY_LAYOUT``). When a job requests this layout the
# avatar stage is skipped (no HeyGen), the narration is the screen recording's
# OWN audio, and compose burns captions straight over the recording — so a reel
# can be produced with only the core backend (FFmpeg + local captioning).
_CAPTIONS_ONLY_LAYOUT: str = "captions_only"


def _is_captions_only(params: ReelForgeParams) -> bool:
    """Return whether this job uses the avatar-less captions-only path."""
    return str(getattr(params, "layout", "") or "") == _CAPTIONS_ONLY_LAYOUT


def _is_faceless_tts(params: ReelForgeParams) -> bool:
    """Whether this is a faceless story reel: TTS narration over stock footage.

    A ``captions_only`` job with no uploaded narration (``voiceover_key``), no
    uploaded footage (``screen_recording_key``) and a chosen ``voice_name``. The
    script is generated (or typed), narrated with the regular TTS path, and
    composed over the curated background (``background_id``) with no avatar.
    """
    return (
        _is_captions_only(params)
        and not str(getattr(params, "voiceover_key", "") or "")
        and not str(getattr(params, "screen_recording_key", "") or "")
        and bool(str(getattr(params, "voice_name", "") or "").strip())
    )


# --------------------------------------------------------------------------- #
# Stage 1 — script
# --------------------------------------------------------------------------- #
def _persist_script(job_id: str, script: str) -> None:
    """Best-effort persist of the finalized script onto the Job row.

    Multi-language dubbing re-runs the pipeline per target language by
    *translating this stored script*, so recording it against the job is what
    makes a finished reel dubbable later. Persistence is deliberately
    failure-tolerant: no configured database, an as-yet-uncommitted job row, or a
    transient DB error must NEVER fail the script stage. Any error (including the
    optional DB imports being unavailable) is swallowed with a warning.
    """
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            JobRepository(session).set_script(job_id, script)
    except Exception as exc:  # noqa: BLE001 - script persistence is best-effort
        logger.warning(f"[{job_id}] could not persist script (non-fatal): {exc}")


def _resolve_hook_style(job_id: str, params: ReelForgeParams) -> str:
    """The job's canonical hook style; an unknown value degrades to none.

    The API rejects unknown styles up front; this guard only protects a job row
    persisted before validation existed from failing its script stage.
    """
    from app.domains.experiments.hook_styles import HookStyleError, normalize_hook_style

    try:
        return normalize_hook_style(getattr(params, "hook_style", ""))
    except HookStyleError as exc:
        logger.warning(f"[{job_id}] ignoring hook style: {exc}")
        return ""


def _judged_script(job_id: str, params: ReelForgeParams, script: str, *, angle: str = "") -> str:
    """Best hook first (M1.3): the generated script with the judged top hook.

    Five candidate hooks (the writer's own plus four alternatives in the same
    angle) are scored by an LLM judge; the winner opens the script. Any failure
    keeps the script as written. The verdict is recorded as a JobEvent.
    """
    from app.services.script.hook_judge import best_hook_script

    judged, verdict = best_hook_script(
        script, subject=params.video_subject, language=params.language, angle=angle
    )
    if verdict is not None:
        try:
            from app.telemetry import events as telemetry_events

            telemetry_events.record_event(
                job_id,
                "script",
                "hook_judge",
                message=f"winner={verdict.winner} score={verdict.scores[verdict.winner]} via {verdict.source}",
                payload=verdict.as_dict(),
            )
        except Exception as exc:  # noqa: BLE001 - telemetry never fails a render
            logger.warning(f"[{job_id}] hook judge event failed: {exc}")
    return judged


def stage_script(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Produce the spoken script and persist it to the Job (best-effort).

    Three mutually exclusive sources, in priority order:

    1. **Dubbing** — when ``params.translate_source_script`` is set, the source
       reel's script is *translated* into ``params.language`` via
       ``translate.translate_script`` (ElevenLabs-multilingual dubbing re-run)
       instead of generating a fresh one. A ``None`` translation (empty input,
       unsupported language, or repeated LLM failure) fails the stage cleanly.
    2. **Manual** — the caller-supplied ``params.video_script`` is used verbatim.
    3. **Generated** — otherwise one is generated via
       ``script.ugc.generate_ugc_script``.

    The resolved script is then persisted onto the Job row (so a finished reel
    can later be dubbed) — best-effort, never fatal. Returns ``{'script': str}``.
    """
    translate_source = (params.translate_source_script or "").strip()
    if translate_source:
        from app.services.translate import translate_script

        translated = translate_script(translate_source, params.language)
        if not translated:
            raise ReelForgeStageError(
                "script",
                f"translation to {params.language!r} returned no script",
            )
        script_text = str(translated).strip()
        logger.success(
            f"[{job_id}] script translated -> {params.language} ({len(script_text)} chars)"
        )
        _persist_script(job_id, script_text)
        return {"script": script_text}

    manual = (params.video_script or "").strip()
    if manual:
        logger.info(f"[{job_id}] using caller-provided script ({len(manual)} chars)")
        _persist_script(job_id, manual)
        return {"script": manual}

    # Captions-only reels derive their captions from the screen recording's own
    # audio (faster-whisper), so a generated narration script is neither used nor
    # required. Skip LLM generation entirely — that is what lets a captions-only
    # reel run with only the core backend when no LLM/script provider is
    # configured. An empty script simply means the caption text comes from the
    # transcription (or a typed script, when one is supplied above).
    # A faceless story reel (captions_only + TTS voice, no uploaded audio or
    # footage) is narrated by TTS, so it DOES need a generated script.
    if _is_captions_only(params) and not _is_faceless_tts(params):
        logger.info(f"[{job_id}] captions-only reel: skipping LLM script generation")
        return {"script": ""}

    hook_style = _resolve_hook_style(job_id, params)
    if hook_style:
        from app.domains.experiments.hook_styles import generate_styled_script

        result = generate_styled_script(
            video_subject=params.video_subject,
            language=params.language,
            target_duration_s=params.target_duration_s,
            hook_style=hook_style,
        )
    else:
        from app.services.script.ugc import generate_ugc_script

        result = generate_ugc_script(
            video_subject=params.video_subject,
            language=params.language,
            target_duration_s=params.target_duration_s,
        )
    if not result or not result.get("full_text"):
        raise ReelForgeStageError("script", "LLM returned no usable UGC script")

    script_text = _judged_script(
        job_id, params, str(result["full_text"]).strip(), angle=hook_style
    )
    logger.success(
        f"[{job_id}] script ready ({len(script_text)} chars"
        + (f", hook_style={hook_style} via {result.get('hook_source')}" if hook_style else "")
        + ")"
    )
    _persist_script(job_id, script_text)
    return {"script": script_text}


# --------------------------------------------------------------------------- #
# Stage 2 — tts (SINGLE TIMING AUTHORITY, §8)
# --------------------------------------------------------------------------- #
def _audio_content_type(key_or_path: str) -> str:
    """Return an audio MIME type for a narration key/path (best-effort)."""
    suffix = os.path.splitext(str(key_or_path or ""))[1].lower()
    return _AUDIO_CONTENT_TYPES.get(suffix, _DEFAULT_AUDIO_CONTENT_TYPE)


def _byov_words_to_ctx(words: Any) -> list[list[Any]]:
    """Flatten ``WordTiming``-shaped items to JSON tuples ``[text, start, end]``.

    Mirrors the flattening the TTS path applies to ``sub_maker.words`` so the
    ``JobContext`` stays JSON-serializable and ``stage_captions`` consumes an
    identical shape regardless of the timing source (§8). Malformed items are
    skipped rather than crashing the stage.
    """
    flat: list[list[Any]] = []
    for word in words or []:
        try:
            flat.append([str(word[0]), float(word[1]), float(word[2])])
        except (IndexError, TypeError, ValueError):
            continue
    return flat


def _byov_transcribe(job_id: str, local_audio: str, language: str, work: str) -> list[list[Any]]:
    """Best-effort BYOV word timings from the uploaded narration (§8 authority).

    Primary path: ``transcribe.transcribe_to_words`` (faster-whisper WORD
    timings). BEST-EFFORT — if transcription fails (model absent, decode error)
    we fall back to an SRT-derived approximation (``transcribe_to_srt`` +
    ``words_from_srt``) and, failing that, an EMPTY list. An empty list means the
    reel still renders (the audio drives the avatar/duration) but captions may be
    sparse; a transcription problem must never fail the BYOV stage.

    Returns the JSON-serializable ``list[[text, start, end]]`` shape.
    """
    from app.services import transcribe

    lang = (language or "").strip() or None
    try:
        words = transcribe.transcribe_to_words(local_audio, language=lang)
        return _byov_words_to_ctx(words)
    except Exception as exc:  # noqa: BLE001 - transcription is best-effort (§8)
        logger.warning(
            f"[{job_id}] BYOV word transcription failed; trying SRT fallback: {exc}"
        )

    try:
        srt_path = os.path.join(work, "voiceover.srt")
        transcribe.transcribe_to_srt(local_audio, srt_path)
        words = transcribe.words_from_srt(srt_path)
        logger.info(f"[{job_id}] BYOV captions via SRT fallback ({len(words)} words)")
        return _byov_words_to_ctx(words)
    except Exception as exc:  # noqa: BLE001 - SRT fallback is best-effort too
        logger.warning(
            f"[{job_id}] BYOV SRT fallback failed; captions will be empty "
            f"(reel still renders from the audio): {exc}"
        )
    return []


def _stage_tts_byov(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Bring Your Own Voiceover: use the creator's uploaded narration audio.

    Skips TTS / ElevenLabs entirely. SECURITY: ``params.voiceover_key`` is
    client-supplied, so it is validated through the same BOLA/IDOR guard used for
    ``screen_recording_key`` (``_assert_owned_r2_key``) — a key reaching into
    another creator's per-job artifacts is rejected as a typed stage error and is
    NEVER presigned/downloaded. The audio is then downloaded, its duration probed
    (``voice.get_audio_duration``) and transcribed with faster-whisper for the §8
    single-authority WORD timings, and re-hosted to R2 so the avatar has a public
    URL. Returns the SAME ``{'audio_key', 'audio_url', 'audio_duration', 'words'}``
    contract as the TTS path.
    """
    from app.services import voice

    work = _workdir(job_id)

    # Ownership guard (IDOR/BOLA): reject a key that reaches into another
    # creator's per-job artifacts before presigning+downloading it.
    try:
        _assert_owned_r2_key(job_id, params.voiceover_key)
    except PermissionError as exc:
        raise ReelForgeStageError("tts", str(exc)) from exc

    suffix = os.path.splitext(params.voiceover_key)[1].lower() or ".mp3"
    local_audio = os.path.join(work, f"voiceover{suffix}")
    try:
        _download_from_r2(params.voiceover_key, local_audio)
    except Exception as exc:  # noqa: BLE001 - surface a typed, catchable error
        raise ReelForgeStageError(
            "tts", f"could not download voiceover {params.voiceover_key!r}: {exc}"
        ) from exc
    if not os.path.isfile(local_audio):
        raise ReelForgeStageError(
            "tts", f"voiceover download produced no file for {params.voiceover_key!r}"
        )

    # §8: the uploaded audio is now the single timing authority. Its duration is
    # probed once (drives the avatar duration validation) and its faster-whisper
    # WORD timings drive the captions.
    audio_duration = float(voice.get_audio_duration(local_audio) or 0.0)
    if audio_duration <= 0.0:
        raise ReelForgeStageError(
            "tts", f"uploaded voiceover {params.voiceover_key!r} has no audible duration"
        )

    words = _byov_transcribe(job_id, local_audio, params.language, work)

    # Re-host the narration so the avatar provider (HeyGen) has a public URL —
    # exactly like the TTS path stores its mp3.
    audio_key = f"jobs/{job_id}/audio{suffix}"
    audio_url = _r2().upload_file(
        local_audio, audio_key, _audio_content_type(local_audio)
    )

    logger.success(
        f"[{job_id}] BYOV narration ready: duration={audio_duration:.3f}s "
        f"words={len(words)} (TTS skipped)"
    )
    return {
        "audio_key": audio_key,
        "audio_url": audio_url,
        "audio_duration": audio_duration,
        "words": words,
    }


# --------------------------------------------------------------------------- #
# Captions-only (avatar-less, no-provider) narration + timing
# --------------------------------------------------------------------------- #
def _ffmpeg_extract_audio(screen_path: str, out_mp3: str) -> str | None:
    """Extract the screen recording's audio track to ``out_mp3`` (best-effort).

    Returns the mp3 path when the recording HAS an audio stream that decodes,
    else ``None`` (a silent screen recording is a valid captions-only input — the
    reel then renders with a synthesized silent track and script-timed captions).
    """
    from app.utils import utils

    ffmpeg = utils.get_ffmpeg_binary()
    command = [
        ffmpeg, "-y", "-i", screen_path,
        "-vn", "-acodec", "libmp3lame", "-b:a", "192k", out_mp3,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001 - extraction is best-effort
        logger.warning(f"audio extraction crashed: {exc}")
        return None
    if result.returncode != 0 or not os.path.isfile(out_mp3) or os.path.getsize(out_mp3) == 0:
        logger.info("screen recording has no decodable audio track")
        return None
    return out_mp3


def _probe_media_duration(path: str) -> float:
    """Best-effort media duration (seconds) via the compose module's ffprobe."""
    try:
        from app.services.compose.compose_ffmpeg import _probe_video

        info = _probe_video(path)
        return float(getattr(info, "duration", 0.0) or 0.0) if info else 0.0
    except Exception as exc:  # noqa: BLE001 - probing is best-effort
        logger.warning(f"could not probe media duration for {path!r}: {exc}")
        return 0.0


def _make_silent_audio(out_mp3: str, duration_s: float) -> str | None:
    """Synthesize a silent stereo mp3 of ``duration_s`` seconds (best-effort)."""
    if duration_s <= 0:
        return None
    from app.utils import utils

    ffmpeg = utils.get_ffmpeg_binary()
    command = [
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{duration_s:.3f}", "-acodec", "libmp3lame", "-b:a", "192k", out_mp3,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001 - synthesis is best-effort
        logger.warning(f"silent-audio synthesis crashed: {exc}")
        return None
    if result.returncode != 0 or not os.path.isfile(out_mp3):
        logger.warning("silent-audio synthesis produced no file")
        return None
    return out_mp3


def _script_words_over_duration(script: str, duration_s: float) -> list[list[Any]]:
    """Distribute a typed script's words evenly across ``duration_s`` (fallback).

    Used when no spoken audio could be transcribed (whisper absent / silent
    recording) but the creator supplied a subject/script — the captions then still
    line up roughly with the reel instead of being empty. Approximate timings; the
    exact §8 authority is whisper (:func:`_byov_transcribe`) when audio exists.
    """
    tokens = str(script or "").split()
    if not tokens or duration_s <= 0:
        return []
    step = duration_s / len(tokens)
    words: list[list[Any]] = []
    for i, token in enumerate(tokens):
        start = round(step * i, 3)
        end = round(duration_s if i == len(tokens) - 1 else step * (i + 1), 3)
        words.append([token, start, max(end, start)])
    return words


def _stage_tts_captions_only(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Narration + timing for the avatar-less captions-only path (no providers).

    The uploaded screen recording's OWN audio becomes the reel's narration:

    1. Download the screen recording (BOLA-guarded like every client-supplied key).
    2. Extract its audio track. When present, transcribe it with faster-whisper for
       the §8 WORD timings (SRT/empty fallback inside :func:`_byov_transcribe`); on
       an empty transcript, fall back to the typed script distributed across the
       audio duration.
    3. When the recording is SILENT (no audio track), synthesize a silent track
       sized to the recording (or ``target_duration_s``) and time the typed script
       across it so captions still render.

    Returns the SAME ``{'audio_key', 'audio_url', 'audio_duration', 'words'}``
    contract as the TTS/BYOV paths. Never contacts ElevenLabs or HeyGen.
    """
    from app.services import voice

    work = _workdir(job_id)

    if not params.screen_recording_key:
        raise ReelForgeStageError(
            "tts", "captions-only reel requires an uploaded screen recording"
        )
    try:
        _assert_owned_r2_key(job_id, params.screen_recording_key)
    except PermissionError as exc:
        raise ReelForgeStageError("tts", str(exc)) from exc

    screen_path = os.path.join(work, "screen_src.mp4")
    try:
        _download_from_r2(params.screen_recording_key, screen_path)
    except Exception as exc:  # noqa: BLE001 - surface a typed, catchable error
        raise ReelForgeStageError(
            "tts",
            f"could not download screen recording "
            f"{params.screen_recording_key!r}: {exc}",
        ) from exc

    script_text = str(ctx.get("script") or params.video_script or "").strip()

    audio_path = _ffmpeg_extract_audio(screen_path, os.path.join(work, "audio.mp3"))
    words: list[list[Any]] = []
    audio_duration = 0.0

    if audio_path:
        audio_duration = float(voice.get_audio_duration(audio_path) or 0.0)
        if audio_duration <= 0.0:
            audio_duration = _probe_media_duration(audio_path)
        # Spoken-audio captions: faster-whisper WORD timings (best-effort).
        words = _byov_transcribe(job_id, audio_path, params.language, work)
        if not words and script_text:
            words = _script_words_over_duration(script_text, audio_duration)

    if not audio_path or audio_duration <= 0.0:
        # Silent recording (or unprobeable audio): synthesize a silent narration
        # track so compose has an audio input, and time the script across it.
        duration = float(params.target_duration_s or 0) or _probe_media_duration(
            screen_path
        )
        if duration <= 0.0:
            raise ReelForgeStageError(
                "tts",
                "captions-only reel needs either audio in the recording or a "
                "target duration to size a silent narration track",
            )
        audio_path = _make_silent_audio(os.path.join(work, "audio.mp3"), duration)
        if not audio_path:
            raise ReelForgeStageError(
                "tts", "could not prepare a narration track for the captions-only reel"
            )
        audio_duration = duration
        words = _script_words_over_duration(script_text, duration)

    audio_key = f"jobs/{job_id}/audio.mp3"
    audio_url = _r2().upload_file(audio_path, audio_key, "audio/mpeg")

    logger.success(
        f"[{job_id}] captions-only narration ready: duration={audio_duration:.3f}s "
        f"words={len(words)} (no avatar/TTS provider)"
    )
    return {
        "audio_key": audio_key,
        "audio_url": audio_url,
        "audio_duration": audio_duration,
        "words": words,
    }


def _submaker_words(sub_maker: Any) -> list[list[Any]]:
    """Word timings ``[[text, start_s, end_s], ...]`` from any TTS SubMaker.

    ElevenLabs' timestamp path fills ``sub_maker.words`` (objects with
    ``text/start/end`` in seconds). The free, keyless edge-tts path (edge_tts
    7.x, ``boundary="WordBoundary"``) instead records one ``cues`` entry per
    spoken word with ``timedelta`` bounds — without this fallback a faceless
    reel narrated by a free voice would render with no captions.
    """
    words: list[list[Any]] = []
    for word in getattr(sub_maker, "words", []) or []:
        try:
            words.append([str(word.text), float(word.start), float(word.end)])
        except (AttributeError, TypeError, ValueError):
            continue
    if words:
        return words
    for cue in getattr(sub_maker, "cues", []) or []:
        try:
            text = str(cue.content).strip()
            if text:
                words.append([text, cue.start.total_seconds(), cue.end.total_seconds()])
        except (AttributeError, TypeError, ValueError):
            continue
    return words


def _effective_voice_name(job_id: str, params: ReelForgeParams, ctx: dict | None = None) -> str:
    """The voice to synthesize with: premium falls back to a free edge-tts voice.

    An ``elevenlabs:`` voice is used only when ElevenLabs is configured AND the
    job holds a premium voice credit (or is wallet/operator funded): a standard
    credit never pays for ElevenLabs. Otherwise the job is narrated by a free
    Microsoft neural voice (edge-tts) for its language.
    """
    voice_name = str(params.voice_name or "")
    if not voice_name.startswith("elevenlabs:"):
        return voice_name
    try:
        from app.core.launch.formats import elevenlabs_configured, free_voice_for
        from app.domains.reels.premium import premium_voice_funded

        fallback = free_voice_for(params.language)
        if not elevenlabs_configured():
            logger.info(f"[{job_id}] ElevenLabs not configured: narrating with free voice {fallback}")
            return fallback
        if premium_voice_funded(job_id, ctx):
            return voice_name
    except Exception as exc:  # noqa: BLE001 - doubt never spends on a premium voice
        logger.warning(f"[{job_id}] voice funding check failed: {exc}")
        from app.core.launch.formats import free_voice_for

        return free_voice_for(params.language)
    logger.info(f"[{job_id}] no premium voice credit: narrating with free voice {fallback}")
    return fallback


def _narrate_with_fallback(
    job_id: str, params: ReelForgeParams, script_text: str, voice_name: str, voice_file: str
) -> Any:
    """Narrate via the M1.4 chain: Kokoro, then edge-tts, then paid ElevenLabs.

    A funded premium voice (``elevenlabs:`` after :func:`_effective_voice_name`)
    goes first; the free engines follow so an ElevenLabs outage degrades the
    voice instead of failing the reel. See ``app.services.tts.narration``.
    """
    from app.core.launch.formats import free_voice_for
    from app.services.tts.narration import NarrationUnavailable, narrate, plan_chain

    premium = voice_name if voice_name.startswith("elevenlabs:") else ""
    steps = plan_chain(
        voice_name,
        language=str(params.language or ""),
        free_voice=free_voice_for(params.language),
        premium_voice=premium,
        premium_first=bool(premium),
    )
    try:
        result = narrate(script_text, steps, voice_file, params.voice_rate)
    except NarrationUnavailable as exc:
        raise ReelForgeStageError("tts", str(exc)) from exc
    logger.info(f"[{job_id}] narration engine={result.engine} voice={result.voice_name}")
    return result


def stage_tts(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Synthesize narration and compute the authoritative timing.

    Two mutually exclusive sources:

    1. **Bring Your Own Voiceover** — when ``params.voiceover_key`` is set the
       creator's OWN uploaded narration audio is used verbatim (no TTS): its
       faster-whisper WORD timings become the §8 authority. See
       :func:`_stage_tts_byov`.
    2. **TTS (default)** — routes through ``voice.tts`` (which dispatches to
       ``elevenlabs_tts_with_timestamps`` for ``elevenlabs:`` voices), derives the
       one authoritative ``audio_duration`` from the returned ``SubMaker`` and
       flattens ``sub_maker.words`` to plain ``list[[text, start, end]]``.

    Either way the ``JobContext`` stays JSON-serializable, the mp3/audio is
    uploaded to R2 (HeyGen needs a public URL), and the return contract is
    ``{'audio_key', 'audio_url', 'audio_duration', 'words'}``.
    """
    if params.voiceover_key:
        return _stage_tts_byov(job_id, params, ctx)

    # Avatar-less captions-only path: no TTS provider. The narration IS the
    # uploaded screen recording's own audio track; its faster-whisper WORD timings
    # (or, as a fallback, the typed script distributed across the duration) drive
    # the §8 captions. See :func:`_stage_tts_captions_only`.
    #
    # Faceless story preset: captions_only with NO uploaded narration, NO uploaded
    # footage and a chosen voice falls through to the regular TTS path below — the
    # generated script is narrated by ``voice.tts`` and compose lays it over the
    # curated background (``background_id``). The avatar stage still skips.
    if _is_captions_only(params) and not _is_faceless_tts(params):
        return _stage_tts_captions_only(job_id, params, ctx)
    if _is_faceless_tts(params):
        logger.info(f"[{job_id}] faceless story reel: TTS narration over background footage")

    from app.services import voice

    script_text = str(ctx.get("script") or params.video_script or "").strip()
    if not script_text:
        raise ReelForgeStageError("tts", "no script text available for synthesis")
    if not params.voice_name:
        raise ReelForgeStageError("tts", "params.voice_name is required for tts")

    voice_name = _effective_voice_name(job_id, params, ctx)
    voice_file = os.path.join(_workdir(job_id), "audio.mp3")
    narration = _narrate_with_fallback(job_id, params, script_text, voice_name, voice_file)
    sub_maker = narration.sub_maker
    voice_name = narration.voice_name

    # §8: audio_duration is derived SOLELY from the SubMaker (ElevenLabs
    # alignment, or edge-tts WordBoundary cues on the keyless path) — the single
    # timing authority. We must NOT fall back to probing the file with
    # ffmpeg/MoviePy, as that would introduce a second timing source; fail fast
    # instead so the pipeline keeps one authority.
    audio_duration = float(voice.get_audio_duration(sub_maker) or 0.0)
    if audio_duration <= 0.0:
        raise ReelForgeStageError(
            "tts", "TTS alignment produced no character timing data"
        )

    # Flatten karaoke word timings to plain JSON tuples (never store SubMaker).
    words = _submaker_words(sub_maker)

    audio_key = f"jobs/{job_id}/audio.mp3"
    audio_url = _r2().upload_file(voice_file, audio_key, "audio/mpeg")

    logger.success(
        f"[{job_id}] tts ready: duration={audio_duration:.3f}s words={len(words)}"
    )
    return {
        "audio_key": audio_key,
        "audio_url": audio_url,
        "audio_duration": audio_duration,
        "words": words,
        # The voice actually used (after the premium/free decision and any
        # engine fallback), for the per-job cost actuals.
        "tts_voice": voice_name,
        "tts_engine": narration.engine,
        "tts_attempts": list(narration.attempts),
    }


# --------------------------------------------------------------------------- #
# Stage 3a — avatar (parallel with captions)
# --------------------------------------------------------------------------- #
def _resolve_avatar_character_kind(job_id: str, params: ReelForgeParams) -> str:
    """Resolve the HeyGen character kind for the chosen avatar (best-effort).

    ``params.avatar_id`` references an :class:`AvatarPreset` the creator picked
    from ``GET /v1/avatars``. A *custom avatar from a photo* is persisted with
    ``config.kind == 'talking_photo'`` (a creator-uploaded selfie turned into a
    HeyGen talking-photo), whereas a stock catalog/instant avatar carries the
    default ``'avatar'`` kind. This loads the persisted preset — scoped to the
    job owner OR the global (``user_id IS NULL``) presets, mirroring the
    ``GET /v1/avatars`` visibility filter — and derives the kind from that row.

    SECURITY: the kind is NEVER taken from client-supplied params; it is derived
    only from the preset the server stored, so a caller cannot flip a stock
    render into a talking-photo render (or vice versa) by forging a params field.

    Fails **safe**: no configured database, a missing/foreign/inactive preset, or
    any DB error yields the default ``'avatar'`` — a stock render is never
    mistaken for a talking photo. Returns ``'talking_photo'`` or ``'avatar'``.
    """
    avatar_id = (params.avatar_id or "").strip()
    if not avatar_id:
        return _CHARACTER_KIND_AVATAR

    try:
        from sqlalchemy import or_

        from app.models.db.base import get_session
        from app.models.db.models import AvatarPreset
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return _CHARACTER_KIND_AVATAR

            preset = (
                session.query(AvatarPreset)
                .filter(
                    AvatarPreset.is_active.is_(True),
                    or_(
                        AvatarPreset.user_id == job.user_id,
                        AvatarPreset.user_id.is_(None),
                    ),
                    or_(
                        AvatarPreset.provider_avatar_id == avatar_id,
                        AvatarPreset.id == avatar_id,
                    ),
                )
                .first()
            )
            if preset is None:
                return _CHARACTER_KIND_AVATAR

            config = preset.config if isinstance(preset.config, dict) else {}
            kind = str(config.get("kind") or "").strip().lower()
            if kind == _CHARACTER_KIND_TALKING_PHOTO:
                logger.info(
                    f"[{job_id}] avatar preset {avatar_id!r} is a talking photo"
                )
                return _CHARACTER_KIND_TALKING_PHOTO
            return _CHARACTER_KIND_AVATAR
    except Exception as exc:  # noqa: BLE001 - kind resolution is best-effort
        logger.warning(
            f"[{job_id}] could not resolve avatar preset kind for {avatar_id!r} "
            f"(defaulting to '{_CHARACTER_KIND_AVATAR}'): {exc}"
        )
        return _CHARACTER_KIND_AVATAR


def stage_avatar(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Render the lip-synced talking-head via the configured provider.

    Passes ``expected_duration_s=ctx['audio_duration']`` (§8 timing validation).
    Returns ``{'avatar_key', 'avatar_video', 'avatar_duration'}``.
    """
    # Avatar-less captions-only path: skip HeyGen entirely. The chord still runs
    # this stage (avatar ∥ captions), so it returns an EMPTY avatar partial and the
    # compose stage renders captions straight over the screen recording. This is
    # what lets a reel be produced with no avatar provider configured.
    if _is_captions_only(params):
        logger.info(f"[{job_id}] captions-only reel: skipping avatar stage")
        return {"avatar_key": "", "avatar_video": "", "avatar_duration": 0.0}

    # A standard credit never pays for a presenter provider: the job must hold
    # AI-video credits (or be wallet/operator funded) before any paid call.
    from app.domains.reels.premium import ai_video_funded

    if not ai_video_funded(job_id, ctx):
        raise ReelForgeStageError(
            "avatar", "AI presenter reels need AI-video credits; none are reserved for this job"
        )

    # MO1 licence gate: this stage is always paid (AI-video credits above), so a
    # presenter on non-commercial or unrecorded weights (LatentSync before the
    # MO12b fork) fails closed before any provider call.
    from app.domains.routing.license_class import is_model_sellable

    if not is_model_sellable(params.avatar_provider):
        raise ReelForgeStageError(
            "avatar",
            f"presenter provider {params.avatar_provider!r} is not licensed for paid output",
        )

    from app.services.avatar import get_avatar_provider

    audio_url = str(ctx.get("audio_url") or "")
    if not audio_url:
        raise ReelForgeStageError("avatar", "ctx is missing audio_url (run tts first)")
    if not params.avatar_id:
        raise ReelForgeStageError("avatar", "params.avatar_id is required")

    provider = get_avatar_provider(params.avatar_provider)
    if not provider.is_enabled():
        raise ReelForgeStageError(
            "avatar", f"provider {params.avatar_provider!r} is not configured"
        )

    # Custom Avatar from a Photo: derive the HeyGen character kind from the
    # PERSISTED preset (owner/global scoped) rather than trusting any client
    # field — a talking-photo preset drives a ``talking_photo`` character, every
    # stock preset the default ``avatar``. Best-effort: an unresolved preset
    # falls back to ``avatar`` so stock renders are entirely unchanged.
    character_kind = _resolve_avatar_character_kind(job_id, params)

    width, height = _resolution(params.aspect)
    result = provider.generate_avatar(
        audio_url,
        params.avatar_id,
        width=width,
        height=height,
        expected_duration_s=ctx.get("audio_duration"),
        character_kind=character_kind,
    )
    if not result or not result.get("avatar_video"):
        raise ReelForgeStageError("avatar", "provider returned no avatar video")

    avatar_video = str(result["avatar_video"])
    avatar_duration = float(result.get("duration") or ctx.get("audio_duration") or 0.0)

    # §5 Stage-3 / §8 drift gate: HeyGen lip-syncs the exact ElevenLabs mp3, so
    # its render duration MUST agree with the authoritative audio_duration within
    # ±_AVATAR_DRIFT_TOLERANCE_S. Beyond that the compose stage would desync, so
    # we record a warning JobEvent (auditable telemetry — this stage holds the
    # job_id) AND fail the stage so the Celery task retries the render.
    expected_duration = float(ctx.get("audio_duration") or 0.0)
    if expected_duration > 0.0 and avatar_duration > 0.0:
        delta = abs(avatar_duration - expected_duration)
        # Spec (§5 Stage-3 / §8): abs(delta) must be < tolerance, so the failure
        # condition is delta >= tolerance (a delta of exactly the tolerance
        # FAILS). Use ``>=`` to honor the documented "< 0.15s" contract.
        if delta >= _AVATAR_DRIFT_TOLERANCE_S:
            from app.telemetry import events as telemetry_events

            drift_msg = (
                f"avatar duration drift beyond tolerance: "
                f"expected={expected_duration:.3f}s actual={avatar_duration:.3f}s "
                f"delta={delta:.3f}s (tol=±{_AVATAR_DRIFT_TOLERANCE_S}s)"
            )
            logger.warning(f"[{job_id}] {drift_msg}")
            telemetry_events.record_event(
                job_id,
                "avatar",
                "warning",
                message=drift_msg,
                payload={
                    "expected": expected_duration,
                    "actual": avatar_duration,
                    "delta": delta,
                    "tolerance": _AVATAR_DRIFT_TOLERANCE_S,
                },
            )
            raise ReelForgeStageError("avatar", drift_msg)

    # The provider re-hosts to R2 itself; fall back to uploading here if not.
    # Assign avatar_key ONLY after a *successful* upload — otherwise ctx would
    # carry a key pointing at a nonexistent object and stage_compose's
    # _download_from_r2 would raise. On failure keep the local path and leave
    # avatar_key empty so _ensure_local re-uses the local avatar_video.
    avatar_key = str(result.get("avatar_key") or "")
    if not avatar_key:
        candidate_key = f"jobs/{job_id}/avatar.mp4"
        try:
            _r2().upload_file(avatar_video, candidate_key, "video/mp4")
            avatar_key = candidate_key
        except Exception as exc:  # noqa: BLE001 - re-host is best-effort here
            logger.warning(
                f"[{job_id}] avatar re-host failed; keeping local path only: {exc}"
            )

    logger.success(f"[{job_id}] avatar ready: duration={avatar_duration:.3f}s")
    return {
        "avatar_key": avatar_key,
        "avatar_video": avatar_video,
        "avatar_duration": avatar_duration,
    }


# --------------------------------------------------------------------------- #
# Stage 3b — captions (parallel with avatar)
# --------------------------------------------------------------------------- #
def stage_captions(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Build the ASS karaoke captions from the (single-authority) word timings.

    Groups ``ctx['words']`` into CapCut-style phrase lines and writes an ASS
    file. Returns ``{'ass_key', 'ass_path'}``.
    """
    from app.services.captions.ass_karaoke import write_ass
    from app.services.captions.presets import get_caption_style
    from app.services.captions.words import WordTiming, group_words_into_phrases

    raw_words = ctx.get("words") or []
    timings: list[WordTiming] = []
    for item in raw_words:
        try:
            text, start, end = item[0], float(item[1]), float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        timings.append(WordTiming(str(text), start, end))

    if not timings:
        # The avatar path always has TTS/BYOV words, so empty timings there is a
        # real upstream failure. The captions-only path may legitimately have no
        # transcribable speech and no typed script (a silent screen recording); in
        # that case the reel still renders (screen + audio) WITHOUT a caption burn
        # rather than failing the whole job.
        if _is_captions_only(params):
            logger.info(
                f"[{job_id}] captions-only reel has no word timings; "
                f"rendering without a caption burn"
            )
            return {"ass_key": "", "ass_path": ""}
        raise ReelForgeStageError("captions", "ctx['words'] is empty (run tts first)")

    # §6 caption presets: resolve the requested preset id to a frozen
    # KaraokeStyle (unknown/empty ids fall back to the default look), so the
    # burned-in captions honour the creator's chosen style instead of the bare
    # library default.
    style = get_caption_style(params.caption_style)

    phrases = group_words_into_phrases(timings)
    ass_path = os.path.join(_workdir(job_id), "captions.ass")
    write_ass(ass_path, phrases, style=style)

    # Assign ass_key ONLY after a *successful* upload (mirror the avatar stage).
    # Otherwise ctx would carry a key pointing at a nonexistent R2 object and, on
    # a different Celery worker, stage_compose's _ensure_local would presign+GET
    # that missing object and raise a raw requests.HTTPError instead of a typed
    # ReelForgeStageError. On failure keep only the local ass_path so re-hydration
    # either uses the local file (same worker) or fails as a typed stage error.
    ass_key = ""
    candidate_key = f"jobs/{job_id}/captions.ass"
    try:
        _r2().upload_file(ass_path, candidate_key, "text/plain; charset=utf-8")
        ass_key = candidate_key
    except Exception as exc:  # noqa: BLE001 - captions still usable locally
        logger.warning(f"[{job_id}] captions upload failed: {exc}")

    logger.success(f"[{job_id}] captions ready: {len(phrases)} phrase lines")
    return {"ass_key": ass_key, "ass_path": ass_path}


def _generate_derivatives(job_id: str, final_video: str, work: str) -> dict[str, str]:
    """Best-effort poster + short-preview generation for the studio gallery.

    Produces a poster JPEG and a short teaser MP4 from ``final_video`` and
    uploads both to R2, returning ``{'poster_key': ..., 'preview_key': ...}``.
    This is deliberately failure-tolerant (§6): ANY error (ffmpeg missing, a bad
    frame, an R2 outage) is swallowed and the corresponding key is left as an
    empty string so a preview problem can NEVER fail the job. Each artifact is
    handled independently so one failing does not suppress the other.
    """
    from app.services import preview

    result: dict[str, str] = {"poster_key": "", "preview_key": ""}

    poster_path = os.path.join(work, "poster.jpg")
    try:
        preview.generate_poster(final_video, poster_path, at_s=_PREVIEW_POSTER_AT_S)
        poster_key = f"jobs/{job_id}/poster.jpg"
        _r2().upload_file(poster_path, poster_key, "image/jpeg")
        result["poster_key"] = poster_key
    except Exception as exc:  # noqa: BLE001 - previews are best-effort (§6)
        logger.warning(f"[{job_id}] poster generation failed (non-fatal): {exc}")

    preview_path = os.path.join(work, "preview.mp4")
    try:
        preview.generate_preview_clip(
            final_video, preview_path, duration_s=_PREVIEW_CLIP_DURATION_S
        )
        preview_key = f"jobs/{job_id}/preview.mp4"
        _r2().upload_file(preview_path, preview_key, "video/mp4")
        result["preview_key"] = preview_key
    except Exception as exc:  # noqa: BLE001 - previews are best-effort (§6)
        logger.warning(f"[{job_id}] preview clip generation failed (non-fatal): {exc}")

    return result


# --------------------------------------------------------------------------- #
# Brand Watermark resolution (best-effort — never fails the job)
# --------------------------------------------------------------------------- #
def _clamp_opacity(value: float) -> float:
    """Clamp a watermark opacity into FFmpeg's valid ``[0.0, 1.0]`` range."""
    return max(0.0, min(1.0, float(value)))


def _load_user_brand(job_id: str) -> dict[str, Any] | None:
    """Best-effort load of the job owner's :class:`UserBrand` as a plain dict.

    Resolves the job's ``user_id`` then that user's brand-watermark singleton,
    returning ``{'logo_key', 'position', 'opacity', 'enabled'}`` detached from
    the session (so the caller can use it after the session closes). Deliberately
    failure-tolerant: no configured database, a missing job/brand, or a transient
    DB error yields ``None`` (compose proceeds without a watermark) — a watermark
    lookup must NEVER fail the job.
    """
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository, UserBrandRepository

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return None
            brand = UserBrandRepository(session).get(job.user_id)
            if brand is None:
                return None
            return {
                "logo_key": str(brand.logo_key or ""),
                "position": str(brand.position or _DEFAULT_WATERMARK_POSITION),
                "opacity": (
                    float(brand.opacity)
                    if brand.opacity is not None
                    else _DEFAULT_WATERMARK_OPACITY
                ),
                "enabled": bool(brand.enabled),
            }
    except Exception as exc:  # noqa: BLE001 - watermark lookup is best-effort
        logger.warning(f"[{job_id}] could not load user brand (non-fatal): {exc}")
        return None


def _resolve_watermark(
    job_id: str, params: ReelForgeParams
) -> tuple[str, str, float] | None:
    """Resolve the effective ``(logo_key, position, opacity)`` for a job.

    Precedence:

    1. An explicit per-job disable (``params.watermark_enabled is False``) wins —
       returns ``None`` (no watermark) regardless of any brand.
    2. A per-job ``params.watermark_key`` uses that logo directly, with the
       per-job position/opacity overrides (falling back to the defaults).
    3. Otherwise the job owner's :class:`UserBrand` is consulted; it applies only
       when *effectively enabled* (the brand's ``enabled`` flag unless the job
       forces it on via ``watermark_enabled=True``) and carries a non-empty
       ``logo_key``. Per-job position/opacity still override the brand's.

    Returns ``None`` when no watermark should be applied (the common case for a
    creator who never configured one).
    """
    if params.watermark_enabled is False:
        return None

    position_override = (params.watermark_position or "").strip()

    if params.watermark_key:
        logo_key = params.watermark_key
        position = position_override or _DEFAULT_WATERMARK_POSITION
        opacity = (
            _DEFAULT_WATERMARK_OPACITY
            if params.watermark_opacity is None
            else _clamp_opacity(params.watermark_opacity)
        )
        return logo_key, position, opacity

    brand = _load_user_brand(job_id)
    if not brand:
        return None

    effective_enabled = (
        brand["enabled"]
        if params.watermark_enabled is None
        else params.watermark_enabled
    )
    if not effective_enabled:
        return None

    logo_key = brand["logo_key"]
    if not logo_key:
        return None

    position = position_override or brand["position"] or _DEFAULT_WATERMARK_POSITION
    opacity = (
        _clamp_opacity(brand["opacity"])
        if params.watermark_opacity is None
        else _clamp_opacity(params.watermark_opacity)
    )
    return logo_key, position, opacity


def _prepare_watermark(job_id: str, params: ReelForgeParams, work: str) -> tuple[
    str | None, str, float
]:
    """Resolve + download the effective watermark logo (best-effort).

    Returns ``(watermark_path, position, opacity)`` where ``watermark_path`` is a
    local PNG path when a watermark applies and could be downloaded, else
    ``None`` (compose without an overlay). ANY failure — resolution, DB, or the
    R2 download — is swallowed with a warning so a watermark problem can NEVER
    fail the job (the compose then simply runs without the overlay).
    """
    try:
        resolved = _resolve_watermark(job_id, params)
    except Exception as exc:  # noqa: BLE001 - watermark resolution is best-effort
        logger.warning(f"[{job_id}] watermark resolution failed (non-fatal): {exc}")
        return None, _DEFAULT_WATERMARK_POSITION, _DEFAULT_WATERMARK_OPACITY

    if resolved is None:
        return None, _DEFAULT_WATERMARK_POSITION, _DEFAULT_WATERMARK_OPACITY

    logo_key, position, opacity = resolved
    try:
        # Ownership guard (IDOR/BOLA): a per-job watermark_key override is
        # client-supplied, so reject a key that reaches into another creator's
        # per-job artifacts before presigning+downloading it. On rejection this
        # falls through to the best-effort handler below (compose without it).
        _assert_owned_r2_key(job_id, logo_key)
        watermark_path = _download_from_r2(
            logo_key, os.path.join(work, "watermark.png")
        )
        logger.info(
            f"[{job_id}] watermark ready: pos={position} opacity={opacity:.3g}"
        )
        return watermark_path, position, opacity
    except Exception as exc:  # noqa: BLE001 - watermark download is best-effort
        logger.warning(
            f"[{job_id}] watermark logo {logo_key!r} download failed "
            f"(non-fatal); composing without it: {exc}"
        )
        return None, position, opacity


# --------------------------------------------------------------------------- #
# AI Background Music (best-effort — never fails the job)
# --------------------------------------------------------------------------- #
def _prepare_ai_music(
    job_id: str,
    params: ReelForgeParams,
    video_path: str,
    work: str,
    video_duration: float,
) -> tuple[str | None, str]:
    """Generate a custom AI background-music track from ``params.music_prompt``.

    Reuses MPT's vendored providers via :mod:`app.services.bgm_ai`: it resolves
    the chosen (or first enabled) provider, clamps the prompt to that provider's
    ``MAX_PROMPT_LENGTH`` and runs ``generate_bgm`` against ``video_path`` (the
    downloaded screen recording) so the resulting track is length/scene matched.
    The generated file is then re-hosted to R2 (best-effort) for auditability.

    Returns ``(music_path, music_key)`` where ``music_path`` is the local track
    to hand to compose (so its sidechain-duck applies) and ``music_key`` is the
    R2 key when the upload succeeded (else ``""``). ENTIRELY best-effort: any
    failure — no enabled provider, the provider's domain error, an unexpected
    exception, or an R2 outage — yields ``(None, "")`` and the reel composes
    WITHOUT music. An AI-music problem must NEVER fail the job.
    """
    # A standard credit never pays for ElevenLabs: its music provider is used
    # only when the job holds a premium credit for it.
    try:
        from app.domains.reels.premium import premium_music_funded, uses_elevenlabs_music

        if uses_elevenlabs_music(params) and not premium_music_funded(job_id):
            logger.info(f"[{job_id}] ElevenLabs music not funded: composing without AI music")
            return None, ""
    except Exception as exc:  # noqa: BLE001 - doubt never spends on ElevenLabs
        logger.warning(f"[{job_id}] AI music funding check failed: {exc}")
        return None, ""
    try:
        from app.services.bgm_ai import content_type_for, generate_ai_bgm

        music_path = generate_ai_bgm(
            video_path=video_path,
            output_dir=work,
            video_duration=video_duration,
            prompt=params.music_prompt,
            provider_name=params.bgm_provider,
        )
    except Exception as exc:  # noqa: BLE001 - AI music is strictly best-effort
        logger.warning(
            f"[{job_id}] AI music generation failed (non-fatal); "
            f"composing without music: {exc}"
        )
        return None, ""

    if not music_path:
        return None, ""

    music_key = ""
    try:
        suffix = os.path.splitext(music_path)[1] or ".mp3"
        candidate_key = f"jobs/{job_id}/ai-bgm{suffix}"
        _r2().upload_file(music_path, candidate_key, content_type_for(music_path))
        music_key = candidate_key
    except Exception as exc:  # noqa: BLE001 - re-host is best-effort
        logger.warning(
            f"[{job_id}] AI music upload failed (non-fatal); "
            f"still mixing the local track: {exc}"
        )

    logger.info(f"[{job_id}] AI background music prepared: {music_path}")
    return music_path, music_key


# --------------------------------------------------------------------------- #
# AI B-roll cutaways (best-effort — never fails the job)
# --------------------------------------------------------------------------- #
def _prepare_broll_clip(
    job_id: str, key: str, label: str, work: str
) -> str | None:
    """Resolve + download one client-supplied B-roll clip (best-effort).

    Returns a local path when ``key`` is set, passes the ownership guard and can
    be downloaded, else ``None`` (splice without this cutaway). SECURITY: the key
    is client-supplied, so it is validated through the SAME BOLA guard used for
    ``screen_recording_key`` / ``watermark_key`` (``_assert_owned_r2_key``); a key
    reaching into another creator's per-job artifacts is skipped. ANY failure —
    ownership violation, missing key, or the R2 download — is swallowed with a
    warning so a B-roll problem can NEVER fail the job.
    """
    clip_key = (key or "").strip()
    if not clip_key:
        return None
    try:
        # Ownership guard (IDOR/BOLA): reject a key that reaches into another
        # creator's per-job artifacts before presigning+downloading it.
        _assert_owned_r2_key(job_id, clip_key)
        dest_path = _download_from_r2(
            clip_key, os.path.join(work, f"broll_{label}.mp4")
        )
        logger.info(f"[{job_id}] b-roll {label} ready: {clip_key!r}")
        return dest_path
    except PermissionError as exc:
        logger.warning(
            f"[{job_id}] refusing cross-tenant b-roll {label} key "
            f"(non-fatal; skipping): {exc}"
        )
        return None
    except Exception as exc:  # noqa: BLE001 - b-roll download is best-effort
        logger.warning(
            f"[{job_id}] b-roll {label} key {clip_key!r} download failed "
            f"(non-fatal; splicing without it): {exc}"
        )
        return None


def _apply_broll(
    job_id: str,
    params: ReelForgeParams,
    main_path: str,
    aspect: Any,
    work: str,
) -> str:
    """Splice muted intro/outro B-roll cutaways around the composed reel.

    Resolves the client-supplied ``broll_intro_key`` / ``broll_outro_key`` (each
    through the ownership guard, best-effort) and, when at least one clip is
    available, calls :func:`compose.compose_ffmpeg.concat_with_broll` to produce a
    ``[intro?][reel][outro?]`` video. The cutaways are muted; the main reel keeps
    its full audio + captions.

    ENTIRELY best-effort: when neither key resolves, or the concat itself fails
    for any reason, the original ``main_path`` (the un-spliced reel) is returned
    unchanged. A B-roll/concat failure must NEVER fail the job.
    """
    if not (params.broll_intro_key or "").strip() and not (
        params.broll_outro_key or ""
    ).strip():
        return main_path

    intro_path = _prepare_broll_clip(job_id, params.broll_intro_key, "intro", work)
    outro_path = _prepare_broll_clip(job_id, params.broll_outro_key, "outro", work)
    if intro_path is None and outro_path is None:
        return main_path

    try:
        from app.services.compose.compose_ffmpeg import concat_with_broll

        output_file = os.path.join(work, "final_broll.mp4")
        spliced = concat_with_broll(
            main_path,
            output_file,
            intro_path=intro_path,
            outro_path=outro_path,
            aspect=aspect,
        )
        logger.success(
            f"[{job_id}] b-roll spliced "
            f"(intro={'yes' if intro_path else 'no'}, "
            f"outro={'yes' if outro_path else 'no'})"
        )
        return spliced or main_path
    except Exception as exc:  # noqa: BLE001 - b-roll concat is best-effort
        logger.warning(
            f"[{job_id}] b-roll concat failed (non-fatal; keeping the reel "
            f"without cutaways): {exc}"
        )
        return main_path


# --------------------------------------------------------------------------- #
# Auto-tighten (Submagic-style dead-air removal) — opt-in compose PRE-step
# --------------------------------------------------------------------------- #
def _apply_auto_tighten(
    job_id: str,
    params: ReelForgeParams,
    screen_path: str,
    work: str,
    audio_duration: float = 0.0,
) -> str:
    """Opt-in dead-air pre-cut of the screen recording (best-effort, pre-compose).

    When ``params.auto_tighten`` is set, the raw screen recording is run through
    the pure-FFmpeg :func:`app.services.editing.tighten` pass — which removes
    stretches that are simultaneously SILENT and STATIC ("dead air") — BEFORE the
    existing compose smart-handling (freezedetect trim + setpts speed-ramp). The
    voiceover/caption timeline is NEVER touched here, so the golden caption-drift
    gate is unaffected: the final reel duration is still governed downstream by
    the script/TTS speed-ramp.

    ``tighten`` is path-in / path-out and DEGRADE-SAFE — it always writes the
    output (a byte copy of the original when nothing removable is found) and never
    raises. On a real cut we hand the tightened file downstream; when nothing was
    applied (or the flag is off) the ORIGINAL ``screen_path`` is returned so the
    downstream bytes are identical to the current path. A ``JobEvent``
    (``removed_s`` / ``applied``) is recorded for telemetry, mirroring the other
    stage cost/telemetry rows. Returns the screen path to compose with.
    """
    if not getattr(params, "auto_tighten", False):
        return screen_path

    from app.services.editing import tighten

    tightened_path = os.path.join(work, "screen_tight.mp4")
    result = tighten(screen_path, tightened_path, mode="auto")

    from app.telemetry import events as telemetry_events

    telemetry_events.record_event(
        job_id,
        "compose",
        "tighten",
        message=(
            f"auto_tighten removed={result.get('removed_s')}s "
            f"applied={result.get('applied')}"
        ),
        payload={
            "removed_s": result.get("removed_s"),
            "applied": result.get("applied"),
            "original_s": result.get("original_s"),
            "tightened_s": result.get("tightened_s"),
        },
    )
    logger.info(
        f"[{job_id}] auto_tighten removed={result.get('removed_s')}s "
        f"applied={result.get('applied')}"
    )
    # TIMING-AUTHORITY GUARD: the composed reel is bounded by ``-shortest`` (=min
    # of screen/avatar/narration) and stage_compose does NOT hand compose a
    # target_duration_s, so no downstream speed-ramp re-fits the screen. If the
    # tightened screen ends up SHORTER than the authoritative narration, adopting
    # it would let ``-shortest`` clamp the reel below the TTS/script duration and
    # silently truncate the voiceover tail + its burned captions. In that case
    # keep the ORIGINAL screen recording so its length stays >= narration.
    if (
        result.get("applied")
        and audio_duration > 0
        and float(result.get("tightened_s") or 0.0) < audio_duration
    ):
        logger.info(
            f"[{job_id}] auto_tighten tightened_s={result.get('tightened_s')}s < "
            f"narration audio_duration={audio_duration}s; keeping ORIGINAL screen "
            f"to preserve script/TTS timing authority"
        )
        return screen_path
    return tightened_path if result.get("applied") else screen_path


# --------------------------------------------------------------------------- #
# Auto-zoom (scene-driven punch-in) — opt-in compose PRE-step (after tighten)
# --------------------------------------------------------------------------- #
def _apply_auto_zoom(
    job_id: str,
    params: ReelForgeParams,
    screen_path: str,
    work: str,
    audio_duration: float = 0.0,
) -> str:
    """Opt-in scene-driven punch-in zoom of the screen recording (best-effort).

    When ``params.auto_zoom`` is set, the screen recording is run through the
    pure-FFmpeg :func:`app.services.editing.auto_zoom` pass — which eases a smooth
    1.0 -> ~1.25x -> 1.0 zoom in on detected scene cuts — as the SECOND
    pre-compose step (order: tighten -> zoom -> motion). ``auto_zoom`` is
    DURATION-PRESERVING (``zoompan d=1`` emits one output frame per input frame
    with the audio stream-copied), so the reel stays exactly as long as the
    input and the voiceover/caption timeline is never touched — the golden
    caption-drift gate is unaffected.

    DEGRADE-SAFE: on no usable moments / any failure the ORIGINAL ``screen_path``
    flows through unchanged (``applied=False``), so the compose path is
    byte-for-byte the current one when the flag is off. A ``JobEvent`` records
    the zoom_count / applied result for telemetry. Returns the screen path to
    compose with.
    """
    if not getattr(params, "auto_zoom", False):
        return screen_path

    # Import the callable via the full submodule path: the ``auto_zoom`` submodule
    # is NOT re-exported as a function from the ``editing`` package (its unit tests
    # import the submodule under that name), so ``from app.services.editing import
    # auto_zoom`` would return the module, not the pass.
    from app.services.editing.auto_zoom import auto_zoom

    zoomed_path = os.path.join(work, "screen_zoom.mp4")
    result = auto_zoom(screen_path, zoomed_path)  # duration-preserving

    from app.telemetry import events as telemetry_events

    telemetry_events.record_event(
        job_id,
        "compose",
        "auto_zoom",
        message=(
            f"auto_zoom count={result.get('zoom_count')} "
            f"applied={result.get('applied')}"
        ),
        payload={
            k: result.get(k)
            for k in ("zoom_count", "applied", "original_s", "output_s")
        },
    )
    logger.info(
        f"[{job_id}] auto_zoom count={result.get('zoom_count')} "
        f"applied={result.get('applied')}"
    )
    # TIMING-AUTHORITY GUARD (defensive): auto_zoom preserves duration, so the
    # output stays >= the narration and this branch is not expected to trigger.
    # But should a render somehow end SHORTER than the authoritative narration,
    # adopting it would let compose's ``-shortest`` clamp the reel below the
    # TTS/script duration and truncate the voiceover tail — so keep the ORIGINAL.
    if (
        result.get("applied")
        and audio_duration > 0
        and float(result.get("output_s") or 0.0) < audio_duration
    ):
        logger.info(
            f"[{job_id}] auto_zoom output_s={result.get('output_s')}s < narration "
            f"audio_duration={audio_duration}s; keeping ORIGINAL screen to "
            f"preserve script/TTS timing authority"
        )
        return screen_path
    return zoomed_path if result.get("applied") else screen_path


# --------------------------------------------------------------------------- #
# Fake-camera motion — opt-in compose PRE-step (after tighten -> zoom)
# --------------------------------------------------------------------------- #
# Presets the legacy pre-compose editing pass (``app.services.editing.motion``)
# renders by baking a subtle scale+crop transform into the screen recording.
# These are the presets UNIQUE to that pass; the Higgsfield-class catalog moves
# (incl. ``whip_pan``) are rendered at the compose stage instead so no preset is
# applied twice. Mirrors ``editing.motion.MOTION_PRESETS`` minus ``whip_pan``.
_LEGACY_MOTION_PRESETS: frozenset[str] = frozenset({"ken_burns", "push_in", "pull_out"})


def _apply_motion(
    job_id: str,
    params: ReelForgeParams,
    screen_path: str,
    work: str,
    aspect: Any,
    audio_duration: float = 0.0,
) -> str:
    """Opt-in synthetic "fake camera motion" on the screen recording (best-effort).

    When ``params.camera_motion`` names an animated preset (``ken_burns`` /
    ``push_in`` / ``pull_out`` / ``whip_pan``) the screen recording is run through
    the pure-FFmpeg :func:`app.services.editing.motion` pass — a subtle
    ``scale``+``crop`` overlay transform — as the THIRD pre-compose step (order:
    tighten -> zoom -> motion). ``camera_motion='none'`` (the default) is a no-op
    and returns the ORIGINAL unchanged.

    Motion is DURATION-PRESERVING (only the video stream is filtered; the audio is
    stream-copied), so it can never make the screen shorter than the narration and
    never touches the voiceover/caption timeline — the golden caption-drift gate is
    unaffected. DEGRADE-SAFE: an unknown preset / any failure returns the ORIGINAL
    ``screen_path`` (``applied=False``). A ``JobEvent`` records the preset / applied
    result. Returns the screen path to compose with.
    """
    preset = str(getattr(params, "camera_motion", "none") or "none").strip().lower()
    if not preset or preset == "none":
        return screen_path
    # Ownership split (each preset renders EXACTLY once — no double application):
    # this legacy pre-compose pass owns only its three unique presets; every
    # Higgsfield-class catalog move (``dolly_in`` / ``crash_zoom_in`` /
    # ``orbit_360`` / ``whip_pan`` …) is rendered at the compose stage by
    # ``app.services.compose.vfx`` instead, so it is a no-op here.
    if preset not in _LEGACY_MOTION_PRESETS:
        return screen_path

    from app.services.editing import motion

    motion_path = os.path.join(work, "screen_motion.mp4")
    result = motion(screen_path, motion_path, preset, aspect=aspect)

    from app.telemetry import events as telemetry_events

    telemetry_events.record_event(
        job_id,
        "compose",
        "motion",
        message=(
            f"motion preset={result.get('preset')} applied={result.get('applied')}"
        ),
        payload={
            k: result.get(k)
            for k in ("preset", "applied", "original_s", "output_s")
        },
    )
    logger.info(
        f"[{job_id}] motion preset={result.get('preset')} "
        f"applied={result.get('applied')}"
    )
    # TIMING-AUTHORITY GUARD (defensive): motion preserves duration, so this is
    # not expected to trigger; if the render ever ended shorter than the narration
    # keep the ORIGINAL so ``-shortest`` cannot truncate the voiceover tail.
    if (
        result.get("applied")
        and audio_duration > 0
        and float(result.get("output_s") or 0.0) < audio_duration
    ):
        logger.info(
            f"[{job_id}] motion output_s={result.get('output_s')}s < narration "
            f"audio_duration={audio_duration}s; keeping ORIGINAL screen to "
            f"preserve script/TTS timing authority"
        )
        return screen_path
    return motion_path if result.get("applied") else screen_path


# --------------------------------------------------------------------------- #
# Background-removal matting — opt-in compose PRE-step on the AVATAR clip
# --------------------------------------------------------------------------- #
def _apply_matting(
    job_id: str,
    params: ReelForgeParams,
    avatar_path: str,
    work: str,
) -> str:
    """Opt-in neural background matting of the AVATAR clip (best-effort).

    When ``params.remove_bg`` is set, the avatar clip is run through the
    (optional, rembg-backed) :func:`app.services.editing.matte` pass in
    ``mode='replace'`` — compositing the neural cut-out over PERFECT solid chroma
    green (``0x00FF00``) so the EXISTING compose ``chromakey`` node keys it
    spill-free with ZERO compose changes. Unlike the screen passes this runs on
    the avatar, as the last pre-compose step in the tighten -> zoom -> motion ->
    matting order.

    DEGRADE-SAFE / DEFAULT-OFF: rembg (and its model) is an OPTIONAL import, so on
    a missing dep/model or ANY ffmpeg error ``matte`` returns the ORIGINAL avatar
    unchanged (``applied=False``) and compose simply falls back to the existing
    chromakey path on the raw avatar. Matting preserves the avatar's exact
    duration (same-fps re-encode + audio passthrough), so the avatar-drift and
    golden caption-drift gates are unaffected. A ``JobEvent`` records the mode /
    applied result. Returns the avatar path to compose with.
    """
    if not getattr(params, "remove_bg", False):
        return avatar_path

    from app.services.editing import matte

    matted_path = os.path.join(work, "avatar_matte.mp4")
    # 'replace' => a flawless chroma-green background that compose's existing
    # chromakey keys spill-free (no compose changes required).
    result = matte(avatar_path, matted_path, mode="replace", bg_key="0x00FF00")

    from app.telemetry import events as telemetry_events

    telemetry_events.record_event(
        job_id,
        "compose",
        "matte",
        message=(
            f"matte applied={result.get('applied')} mode={result.get('mode')}"
        ),
        payload={
            k: result.get(k)
            for k in ("applied", "mode", "original_s", "output_s")
        },
    )
    logger.info(
        f"[{job_id}] matte applied={result.get('applied')} "
        f"mode={result.get('mode')}"
    )
    return matted_path if result.get("applied") else avatar_path


# --------------------------------------------------------------------------- #
# Stage 4 — compose
# --------------------------------------------------------------------------- #
def _loop_background_to_duration(
    job_id: str, local: str, duration_s: float, work: str
) -> str:
    """Loop a too-short background clip out to ``duration_s`` (best-effort).

    Returns the path of a looped copy under ``work`` when the source is shorter
    than the requested duration, else the original path. Any probe/ffmpeg
    failure degrades to the original clip — a background problem must never
    fail the compose stage on its own.
    """
    try:
        from app.services.compose.compose_ffmpeg import _probe_video
        from app.utils import utils as _utils

        info = _probe_video(local)
        clip_duration = float(getattr(info, "duration", 0.0) or 0.0)
        if clip_duration <= 0 or clip_duration >= float(duration_s):
            return local
        loops = int(float(duration_s) // clip_duration) + 1
        looped = os.path.join(work, "background_looped.mp4")
        cmd = [
            _utils.get_ffmpeg_binary(),
            "-y",
            "-stream_loop",
            str(loops),
            "-i",
            local,
            "-t",
            f"{float(duration_s):.3f}",
            "-c",
            "copy",
            looped,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not os.path.isfile(looped) or os.path.getsize(looped) <= 0:
            logger.warning(
                f"[{job_id}] background loop-out failed (rc={result.returncode}); "
                "using the original clip"
            )
            return local
        logger.info(
            f"[{job_id}] background looped {clip_duration:.1f}s -> "
            f"{float(duration_s):.1f}s ({loops} loops)"
        )
        return looped
    except Exception as exc:  # noqa: BLE001 - best-effort, degrade to original
        logger.warning(f"[{job_id}] background loop-out failed (non-fatal): {exc}")
        return local


def _materialize_background(job_id: str, background_id: str, duration_s: int, work: str) -> str:
    """Resolve a curated background id → real footage → R2 key under this job.

    Uses ``content.background_library`` (stock fetch or first-party loop). Returns
    the ``jobs/<job_id>/background.mp4`` key on success, or ``""`` on any failure
    (the caller then raises the normal "screen recording required" error).
    """
    try:
        from app.domains.content import background_library as bglib

        clip = bglib.resolve(background_id)
        if clip is None:
            return ""
        paths = bglib.materialize(clip, task_id=job_id, duration_s=float(duration_s or 30))
        if not paths:
            return ""
        local = paths[0]
        if getattr(clip, "asset_path", ""):
            # Packaged loop: use the pre-encoded 1080x1920 / 2 s GOP copy (made
            # once per worker), so compose reads frames at the output size.
            from app.services.loops.prepared import prepared_loop

            local = prepared_loop(local)
        # Bundled first-party loops are short (a few seconds) and materialize
        # returns them as-is. Compose bounds the reel with ``-shortest`` (min of
        # screen/narration), so a background shorter than the requested duration
        # would silently truncate the narration tail + its captions. Loop it out
        # to the target duration here so the narration remains the timing
        # authority. Best-effort: on any failure the original clip is used.
        local = _loop_background_to_duration(
            job_id, local, float(duration_s or 30), work
        )
        key = f"jobs/{job_id}/background.mp4"
        _r2().upload_file(local, key, "video/mp4")
        return key
    except Exception as exc:  # best-effort — degrade to the clear compose error
        logger.warning(f"[{job_id}] background materialize failed for {background_id!r}: {exc}")
        return ""


def _materialize_style_scene(job_id: str, params: ReelForgeParams, ctx: dict, work: str) -> str:
    """Render a style's visual track locally; its path, or "" on failure.

    The track is an intermediate consumed by this same compose call, so it is
    NOT round-tripped through R2 (that upload + re-download of a ~1080x1920
    intermediate was pure wall-clock waste per variant).
    """
    try:
        from app.services.styles.pipeline import build_style_screen

        local = build_style_screen(job_id, params, ctx, work)
        if local and os.path.isfile(local) and os.path.getsize(local) > 0:
            return local
        return ""
    except Exception as exc:  # noqa: BLE001 - best-effort, classic path follows
        logger.warning(f"[{job_id}] style scene failed (non-fatal): {exc}")
        return ""


def _apply_screen_presteps(
    job_id: str, params: ReelForgeParams, ctx: dict, screen_path: str, work: str
) -> str:
    """Tighten -> zoom -> motion on the screen recording (each opt-in).

    Auto-tighten strips dead air; auto-zoom and the legacy camera presets are
    duration-preserving and never touch the voiceover/caption timeline. With
    every flag off the ORIGINAL ``screen_path`` flows through unchanged. Each
    pass that runs is one extra full encode, counted for the JobEvent.
    """
    from app.services.compose import encode_count

    audio_duration = float(ctx.get("audio_duration") or 0.0)
    steps = (
        lambda path: _apply_auto_tighten(job_id, params, path, work, audio_duration=audio_duration),
        lambda path: _apply_auto_zoom(job_id, params, path, work, audio_duration=audio_duration),
        lambda path: _apply_motion(
            job_id, params, path, work, aspect=params.aspect, audio_duration=audio_duration
        ),
    )
    for step in steps:
        out = step(screen_path)
        if out != screen_path:
            encode_count.count("screen_prep")
        screen_path = out
    return screen_path


def _single_pass_eligible(params: ReelForgeParams) -> bool:
    """Whether a style reel can compose in one pass (M1.2, ``COMPOSE_SINGLE_PASS``).

    Needs: a style with no uploaded footage, the captions-only layout, and no
    step that must read a rendered screen file first (dead-air tighten,
    auto-zoom, a legacy baked camera preset, AI music scored to the video).
    """
    from app.services.compose.single_pass import single_pass_enabled

    if not single_pass_enabled():
        return False
    if params.screen_recording_key or not getattr(params, "style", ""):
        return False
    if not _is_captions_only(params):
        return False
    if getattr(params, "auto_tighten", False) or getattr(params, "auto_zoom", False):
        return False
    motion = str(getattr(params, "camera_motion", "none") or "none").strip().lower()
    if motion in _LEGACY_MOTION_PRESETS:
        return False
    return not (params.music_prompt or "").strip()


def _plan_style_scene(job_id: str, params: ReelForgeParams, ctx: dict, work: str) -> Any:
    """The style's ``SceneSpec`` for the single-pass compose, or ``None``."""
    try:
        from app.services.styles.pipeline import plan_style_scene

        return plan_style_scene(job_id, params, ctx, work)
    except Exception as exc:  # noqa: BLE001 - best-effort, the two-pass path follows
        logger.warning(f"[{job_id}] single-pass scene plan failed (non-fatal): {exc}")
        return None


def _record_encode_count(job_id: str, counts: dict[str, int]) -> int:
    """Log the reel's full H.264 encodes as a JobEvent; the total."""
    from app.services.compose import encode_count

    full = encode_count.total(counts)
    try:
        from app.telemetry import events as telemetry_events

        telemetry_events.record_event(
            job_id,
            "compose",
            "encodes",
            message=f"full_encodes={full} " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            payload={"full_encodes": full, "by_kind": dict(counts)},
        )
    except Exception as exc:  # noqa: BLE001 - telemetry never fails a render
        logger.warning(f"[{job_id}] encode-count event failed: {exc}")
    return full


def _counts_encodes(func: Any) -> Any:
    """Tally the full encodes ``func`` runs; log them and add ``full_encodes``."""

    @functools.wraps(func)
    def wrapper(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
        from app.services.compose import encode_count

        with encode_count.tally() as counts:
            result = func(job_id, params, ctx)
        result["full_encodes"] = _record_encode_count(job_id, counts)
        return result

    return wrapper


@_counts_encodes
def stage_compose(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Composite avatar over the screen recording with burned-in captions.

    Re-materializes the screen recording and audio from R2 (and, if needed, the
    avatar/caption artifacts) into the local worker, then runs the pure-FFmpeg
    compose. When ``params.music_id`` is set the resolved background track is
    mixed in (compose already ducks it under the narration); otherwise, when
    ``params.music_prompt`` is supplied, a custom AI track is generated
    best-effort via the chosen provider and mixed in the same way. After a
    successful compose it also generates a poster + short preview and uploads
    them to R2 (best-effort — a preview failure never fails the job). Returns
    ``{'final_key', 'final_video', 'poster_key', 'preview_key', 'music_key'}``.
    """
    from app.models.schema import VideoAspect
    from app.services.compose.compose_ffmpeg import (
        compose_avatar_over_screen,
        compose_captions_over_screen,
    )

    work = _workdir(job_id)

    # No user footage but a curated background was chosen (e.g. the Reddit-story
    # split-screen auto-filled "generic-parkour"): materialize that background
    # into a looping companion clip, upload it under THIS job's prefix, and use it
    # as the screen recording the compose stage layers under. This is what lets
    # faceless split-screen / loop formats render without the user sourcing footage.
    # One-click style with no uploaded footage: render the style's own visual
    # track (product visuals + companion loop + hook overlays). Best-effort: on
    # any failure it returns "" and the classic background path below runs.
    # Single pass (M1.2): a faceless style reel draws its scene, captions and
    # narration in ONE encode. Anything the plan cannot cover takes the
    # two-pass path below, unchanged.
    scene_spec = None
    if _single_pass_eligible(params):
        scene_spec = _plan_style_scene(job_id, params, ctx, work)
    style_screen = ""
    if scene_spec is None and not params.screen_recording_key and getattr(params, "style", ""):
        style_screen = _materialize_style_scene(job_id, params, ctx, work)

    if (
        scene_spec is None
        and not style_screen
        and not params.screen_recording_key
        and params.background_id
    ):
        # Size the footage to the narration when it runs past the target length
        # (a TTS read of a generated script often does); compose ends at the
        # shorter input, so a short background would cut the voiceover off.
        narration_s = float(ctx.get("audio_duration") or 0.0)
        bg_duration = max(int(params.target_duration_s or 0), int(narration_s) + 1 if narration_s > 0 else 0)
        bg_key = _materialize_background(job_id, params.background_id, bg_duration, work)
        if bg_key:
            params = _dc_replace(params, screen_recording_key=bg_key)

    if scene_spec is not None:
        screen_path = ""  # drawn inside the compose filtergraph
    elif style_screen:
        # Rendered by this worker a moment ago: use it in place (server-made,
        # never client-supplied, so no ownership check or R2 round trip).
        screen_path = style_screen
    else:
        if not params.screen_recording_key:
            raise ReelForgeStageError(
                "compose", "params.screen_recording_key is required to compose"
            )
        # Ownership guard (IDOR/BOLA): screen_recording_key is client-supplied, so
        # reject a key that reaches into another creator's per-job artifacts before
        # presigning+downloading it.
        try:
            _assert_owned_r2_key(job_id, params.screen_recording_key)
        except PermissionError as exc:
            raise ReelForgeStageError("compose", str(exc)) from exc
        screen_path = _download_from_r2(
            params.screen_recording_key, os.path.join(work, "screen.mp4")
        )

    # Screen PRE-steps (tighten -> zoom -> motion), each opt-in and degrade-safe;
    # with every flag off the screen recording flows through unchanged.
    if screen_path:
        screen_path = _apply_screen_presteps(job_id, params, ctx, screen_path, work)

    audio_key = str(ctx.get("audio_key") or "")
    if not audio_key:
        raise ReelForgeStageError("compose", "ctx is missing audio_key")
    audio_path = _download_from_r2(audio_key, os.path.join(work, "audio.mp3"))

    # Avatar-less captions-only path has no avatar artifact to materialize.
    captions_only = _is_captions_only(params)
    avatar_path = ""
    if not captions_only:
        avatar_path = _ensure_local(
            str(ctx.get("avatar_video") or ""),
            str(ctx.get("avatar_key") or ""),
            os.path.join(work, "avatar.mp4"),
        )
        # Background-removal matting PRE-step (last in the tighten -> zoom ->
        # motion -> matting order): opt-in, degrade-safe neural cut-out of the
        # AVATAR composited over chroma green so compose's existing chromakey keys
        # it spill-free. When the flag is off / rembg is absent the ORIGINAL avatar
        # flows through unchanged and compose falls back to the existing chromakey
        # path.
        matted = _apply_matting(job_id, params, avatar_path, work)
        if matted != avatar_path:
            from app.services.compose import encode_count

            encode_count.count("screen_prep")
        avatar_path = matted

    ass_path: str | None = None
    if ctx.get("ass_path") or ctx.get("ass_key"):
        # Re-materializing captions can fail on a different worker (stale local
        # path, missing R2 object, provider error). Convert any such failure into
        # a typed ReelForgeStageError so a raw provider exception never escapes
        # this stage (module contract: "never lets a raw provider exception
        # escape unlabelled").
        try:
            ass_path = _ensure_local(
                str(ctx.get("ass_path") or ""),
                str(ctx.get("ass_key") or ""),
                os.path.join(work, "captions.ass"),
            )
        except Exception as exc:  # noqa: BLE001 - re-hydration must not leak raw
            raise ReelForgeStageError(
                "compose", f"could not materialize captions artifact: {exc}"
            ) from exc

    try:
        aspect = VideoAspect(params.aspect)
    except (ValueError, KeyError):
        aspect = VideoAspect.portrait

    # §6 background music: resolve the chosen track id to a safe local path and
    # let compose mix (and duck) it under the narration. An unknown/blank id
    # resolves to None, which keeps the current (music-less) behaviour.
    music_path: str | None = None
    music_key: str = ""
    if params.music_id:
        from app.services.music import get_music_path

        music_path = get_music_path(params.music_id)
        if music_path is None:
            logger.warning(
                f"[{job_id}] music_id {params.music_id!r} did not resolve; "
                f"composing without background music"
            )

    # AI background music: when a text prompt is supplied and no explicit track
    # was chosen/resolved above, generate a custom royalty-free BGM via the
    # configured provider (reusing MPT's elevenlabs_music/sonilo integrations)
    # from the screen recording, then hand it to compose as music_path so the
    # existing sidechain-duck applies. BEST-EFFORT: any failure composes WITHOUT
    # music and never fails the job.
    if music_path is None and (params.music_prompt or "").strip():
        music_path, music_key = _prepare_ai_music(
            job_id,
            params,
            screen_path,
            work,
            float(ctx.get("audio_duration") or 0.0),
        )

    # M2.4 music bed: level library or AI music so it sits well under the
    # narration before compose ducks it (never raises; falls back to as-is).
    if music_path:
        from app.services.audio.leveling import prepare_music_bed

        music_path = prepare_music_bed(
            music_path, audio_path, os.path.join(work, "music_bed.wav")
        )

    # Brand Watermark (§ brand overlay): resolve the effective per-user/per-job
    # logo and download it to a temp file. Entirely best-effort — a watermark
    # or download failure leaves watermark_path=None so compose runs without it.
    watermark_path, watermark_position, watermark_opacity = _prepare_watermark(
        job_id, params, work
    )

    final_video = os.path.join(work, "final.mp4")
    try:
        if scene_spec is not None:
            from app.services.compose.single_pass import compose_scene_with_captions

            compose_scene_with_captions(
                scene_spec,
                audio_path,
                final_video,
                ass_path=ass_path,
                aspect=aspect,
                music_path=music_path,
                watermark_path=watermark_path,
                watermark_position=watermark_position,
                watermark_opacity=watermark_opacity,
                camera_motion=str(getattr(params, "camera_motion", None) or "none"),
                effects=list(getattr(params, "effects", ()) or ()),
                vfx_intensity=int(getattr(params, "vfx_intensity", 50) or 50),
            )
        elif captions_only:
            # Avatar-less compose: burn captions over the screen recording with its
            # own narration audio. No HeyGen input at all. Music/watermark/VFX still
            # apply exactly as in the avatar path.
            compose_captions_over_screen(
                screen_path,
                audio_path,
                final_video,
                ass_path=ass_path,
                aspect=aspect,
                music_path=music_path,
                watermark_path=watermark_path,
                watermark_position=watermark_position,
                watermark_opacity=watermark_opacity,
                camera_motion=str(getattr(params, "camera_motion", None) or "none"),
                effects=list(getattr(params, "effects", ()) or ()),
                vfx_intensity=int(getattr(params, "vfx_intensity", 50) or 50),
            )
        else:
            compose_avatar_over_screen(
                screen_path,
                avatar_path,
                audio_path,
                final_video,
                layout=params.layout,
                ass_path=ass_path,
                aspect=aspect,
                music_path=music_path,
                watermark_path=watermark_path,
                watermark_position=watermark_position,
                watermark_opacity=watermark_opacity,
                # Higgsfield-class VFX render: the compose stage splices the
                # selected camera-motion + Effects-Mix fragments into the
                # filtergraph under the captions. Legacy camera presets
                # (ken_burns/push_in/pull_out) already baked pre-compose read as
                # ``none`` here (no fragment); catalog moves + VFX render at this
                # stage. Empty selection => the classic graph.
                camera_motion=str(getattr(params, "camera_motion", None) or "none"),
                effects=list(getattr(params, "effects", ()) or ()),
                vfx_intensity=int(getattr(params, "vfx_intensity", 50) or 50),
            )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise ReelForgeStageError("compose", f"ffmpeg compose failed: {exc}") from exc

    # AI B-roll cutaways: splice a muted intro/outro stock clip around the reel
    # (best-effort). Runs AFTER the main compose so the un-spliced reel is a
    # complete, uploadable artifact if the splice fails; the returned path (the
    # spliced video on success, else the original reel) is what we upload and
    # derive previews from.
    final_video = _apply_broll(job_id, params, final_video, aspect, work)

    final_key = f"jobs/{job_id}/final.mp4"
    _r2().upload_file(final_video, final_key, "video/mp4")

    # §6 studio previews: poster + teaser clip (best-effort, never fatal).
    derivatives = _generate_derivatives(job_id, final_video, work)

    # Generate->edit seam (EDITING-SUITE-PLAN §4): probe the final output here,
    # where it is still local, so the completion stage can emit an accurate
    # WolfCut GeneratedClip descriptor (exact width/height/frame-rate/codecs)
    # without a second download. Best-effort: an empty probe degrades to the
    # job's aspect resolution downstream and never fails the render.
    clip_media: dict[str, Any] = {}
    try:
        from app.services.generated_clip import probe_media_descriptor

        clip_media = probe_media_descriptor(final_video)
    except Exception as exc:  # noqa: BLE001 - descriptor probe is best-effort
        logger.warning(f"[{job_id}] could not probe final for clip descriptor: {exc}")

    logger.success(f"[{job_id}] compose ready: {final_key}")
    return {
        "final_key": final_key,
        "final_video": final_video,
        "poster_key": derivatives["poster_key"],
        "preview_key": derivatives["preview_key"],
        "music_key": music_key,
        "clip_media": clip_media,
    }


def _attach_generated_clip(
    job_id: str, params: ReelForgeParams, ctx: dict, payload: dict[str, Any]
) -> None:
    """Build the WolfCut GeneratedClip descriptor, attach it, and persist it.

    Assembles the descriptor from the finished job (the compose probe in
    ``ctx['clip_media']`` and the authoritative word timing in ``ctx['words']``),
    presigns a directly-openable GET URL for its ``src`` on the completion
    payload, and persists the URL-less base on the job so the pull path
    (``GET /jobs/{id}``) can surface the same object with a freshly-signed URL.

    Entirely best-effort: any failure (probe, presign, DB) is swallowed so it
    can never turn a finished render into a failure. When no usable final key
    exists (nothing to open) the descriptor is skipped.
    """
    try:
        from app.services.generated_clip import descriptor_from_job

        final_key = str(ctx.get("final_key") or "").strip()
        if not final_key:
            return

        base = descriptor_from_job(params, ctx, src=None)

        # A directly-openable URL for the descriptor's ``src``. Presigning is
        # best-effort; if it fails the receiver still has ``result_key`` on the
        # payload and can sign its own URL.
        src = ""
        try:
            src = _r2().presign_result_get(final_key)
        except Exception as exc:  # noqa: BLE001 - individual URL is best-effort
            logger.warning(
                f"[{job_id}] could not presign clip descriptor src: {exc}"
            )
        payload["generated_clip"] = {**base, "src": src}

        # Persist the URL-less base so the status route can re-sign ``src`` on
        # each read (presigned URLs expire; the base does not).
        try:
            from app.models.db.base import get_session
            from app.models.db.repositories import JobRepository

            with get_session() as session:
                JobRepository(session).set_result_media(job_id, base)
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            logger.warning(
                f"[{job_id}] could not persist clip descriptor: {exc}"
            )
    except Exception as exc:  # noqa: BLE001 - descriptor is best-effort (§ seam)
        logger.warning(
            f"[{job_id}] generated-clip descriptor build failed (non-fatal): {exc}"
        )


def _fire_completion_webhook(job_id: str, params: ReelForgeParams, ctx: dict) -> None:
    """Deliver the job-completion webhook (best-effort) and record a JobEvent.

    Fires only when ``params.webhook_url`` is set. The payload mirrors the
    Creator-Studio contract (§6): ``{job_id, status, result_key, poster_key,
    preview_key}``. Delivery itself never raises (``webhooks.deliver_webhook``
    returns a result envelope), and we additionally wrap everything so a
    telemetry/import hiccup can never fail the job. A ``JobEvent`` records the
    delivery outcome for auditing.
    """
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": "complete",
        "result_key": str(ctx.get("final_key") or ""),
        "poster_key": str(ctx.get("poster_key") or ""),
        "preview_key": str(ctx.get("preview_key") or ""),
    }

    # Generate->edit seam (EDITING-SUITE-PLAN §4 / Phase 1): attach the WolfCut
    # GeneratedClip descriptor so a completion consumer (webhook receiver,
    # workspace subscription, or the desktop shell polling the job) can open the
    # finished reel straight in the editor. Best-effort and never fatal.
    _attach_generated_clip(job_id, params, ctx, payload)

    # Existing per-job callback (unchanged): fires only when the job set a
    # ``webhook_url``. This is the original power-user behavior and is preserved
    # exactly.
    if params.webhook_url:
        try:
            from app.services.webhooks import deliver_webhook
            from app.telemetry import events as telemetry_events

            result = deliver_webhook(
                params.webhook_url,
                payload,
                secret=params.webhook_secret or None,
            )
            delivered = bool(result.get("delivered"))
            status = "complete" if delivered else "warning"
            message = (
                f"webhook delivered (http {result.get('status')})"
                if delivered
                else f"webhook not delivered: {result.get('error') or 'unknown error'}"
            )
            if delivered:
                logger.info(f"[{job_id}] {message}")
            else:
                logger.warning(f"[{job_id}] {message}")
            telemetry_events.record_event(
                job_id,
                "webhook",
                status,
                message=message,
                payload={
                    "delivered": delivered,
                    "http_status": result.get("status"),
                },
            )
        except Exception as exc:  # noqa: BLE001 - webhook delivery is best-effort (§6)
            logger.warning(
                f"[{job_id}] completion webhook failed (non-fatal): {exc}"
            )

    # ADDITIVE (Enterprise API Platform, Epic 4): fan the completion out to any
    # workspace webhook SUBSCRIPTIONS the job owner has registered for
    # ``job.completed``. Independent of the per-job ``webhook_url`` above and
    # fully best-effort — a telemetry/DB hiccup here never fails the job.
    _dispatch_completion_subscriptions(job_id, payload)


def _dispatch_completion_subscriptions(job_id: str, payload: dict) -> None:
    """Fan a ``job.completed`` event out to the owner's workspace subscriptions.

    Best-effort platform integration: resolves the job's owning user, then every
    workspace they belong to, and dispatches a ``job.completed`` event (idempotent
    on ``job.completed:<job_id>``) to each workspace's enabled webhook
    subscriptions via :func:`app.services.webhook_subscriptions.dispatch`. Wrapped
    end-to-end so any failure (unconfigured DB, missing tables, delivery error) is
    swallowed — this never affects the render job.
    """
    try:
        from app.models.db.base import get_session
        from app.models.db.repositories import (
            JobRepository,
            WorkspaceRepository,
        )
        from app.services import webhook_subscriptions

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            owner_id = getattr(job, "user_id", "") if job is not None else ""
            if not owner_id:
                return
            workspaces = WorkspaceRepository(session).list_for_user(owner_id)
            event_id = f"job.completed:{job_id}"
            for workspace in workspaces:
                webhook_subscriptions.dispatch(
                    session,
                    workspace.id,
                    "job.completed",
                    payload,
                    event_id=event_id,
                )
    except Exception as exc:  # noqa: BLE001 - platform fan-out is best-effort
        logger.warning(
            f"[{job_id}] subscription dispatch failed (non-fatal): {exc}"
        )


# --------------------------------------------------------------------------- #
# Stage 5 — upload
# --------------------------------------------------------------------------- #
def stage_upload(job_id: str, params: ReelForgeParams, ctx: dict) -> dict:
    """Cross-post the final video to the requested platforms.

    Skips the cross-post gracefully when ``params.platforms`` is empty. When
    ``params.webhook_url`` is set a best-effort job-completion webhook is fired
    at the end (§6) regardless of whether any platforms were requested. Returns
    ``{'upload_results': [...], 'request_id': str}``.
    """
    if not params.platforms:
        logger.info(f"[{job_id}] no platforms requested; skipping upload")
        _fire_completion_webhook(job_id, params, ctx)
        return {"upload_results": [], "request_id": ""}

    from app.services.upload_post import cross_post_video

    final_video = _ensure_local(
        str(ctx.get("final_video") or ""),
        str(ctx.get("final_key") or ""),
        os.path.join(_workdir(job_id), "final.mp4"),
    )

    title = (params.video_subject or "ReelForge video").strip()[:100]
    youtube_extra: dict[str, Any] = {
        "youtube_title": title,
        "privacyStatus": params.youtube_privacy_status,
    }

    # §5d: when the per-job ToS/AI-disclosure toggle is on, mark the output as
    # AI/synthetic media across every requested platform. YouTube already sets
    # ``containsSyntheticMedia`` in ``upload_post``; we assert it here too and add
    # a description note, then append the same note to the shared caption so
    # TikTok/Instagram (which only receive ``title``) are disclosed as well. When
    # the toggle is off the metadata is left exactly as before.
    caption = title
    if params.tos_disclosure:
        youtube_extra["containsSyntheticMedia"] = "true"
        youtube_extra["youtube_description"] = _with_disclosure(
            str(youtube_extra.get("youtube_description", ""))
        )
        caption = _with_disclosure(title)

    result = cross_post_video(
        final_video,
        caption,
        platforms=list(params.platforms),
        youtube_extra=youtube_extra,
    )
    if not isinstance(result, dict):
        raise ReelForgeStageError("upload", "cross_post_video returned no result")

    request_id = str(result.get("request_id", "") or "")
    raw_results = result.get("results")
    upload_results = raw_results if isinstance(raw_results, list) else [result]

    if not result.get("success", True):
        logger.warning(f"[{job_id}] upload reported failure: {result.get('message')}")

    logger.success(
        f"[{job_id}] upload done: request_id={request_id or 'n/a'} "
        f"platforms={list(params.platforms)}"
    )

    # §6 job-completion webhook (best-effort; fired after the cross-post so the
    # receiver can trust the job is fully done).
    _fire_completion_webhook(job_id, params, ctx)

    return {"upload_results": upload_results, "request_id": request_id}
