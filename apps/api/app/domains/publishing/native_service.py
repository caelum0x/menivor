"""Native multi-platform publish service.

Ties the pieces together for a real, direct-to-platform post of a rendered reel:

1. resolve + validate the platform connector (``connectors.get_connector``),
2. ensure the caller has a connected account with a **valid** OAuth token
   (``oauth_connect.refresh_if_needed`` → decrypt), else a clean "connect first",
3. resolve the job's rendered MP4 → a short-lived presigned R2 URL (API-hosted
   upload path) and, for YouTube's byte-upload, a local temp download,
3b. for a clipped-from-a-link job (``app.domains.clipping``), hold a cross-post
   that would carry a foreign platform's watermark into a platform that
   suppresses it (``_watermark_block_reason``) — the same reach-killing cross-
   post this already guards against in the web/mobile composer,
4. dispatch the connector (the only network step, via the injectable transport),
5. append a ``JobEvent`` audit row and return the :class:`PublishResult`.

Import-safe: the persistence layer is pulled in behind a guarded block so importing
this module never breaks app startup; a missing DB layer raises at call time.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

from loguru import logger

from app.models import const

from .content_gate import GateContext, GateResult, evaluate_content_sync
from .connectors import (
    PublishError,
    PublishRequest,
    PublishResult,
    RequestsTransport,
    Transport,
    available_platforms,
    get_connector,
)

try:
    from app.models.db.base import get_session
    from app.models.db.models import Asset, Job
    from app.services import oauth_connect

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only before DB layer exists
    get_session = None  # type: ignore[assignment]
    Asset = Job = None  # type: ignore[assignment]
    oauth_connect = None  # type: ignore[assignment]
    _DB_IMPORT_ERROR = exc


# Platforms that need a public URL (API-hosted ingest) vs. a local byte upload.
_URL_UPLOAD = frozenset({"tiktok", "instagram"})
_BYTE_UPLOAD = frozenset({"youtube"})
_SCHEDULE_PLATFORM_ALIASES = {"youtube_shorts": "youtube"}


class NativePublishError(RuntimeError):
    """A native publish could not be prepared or executed (surfaced by the router).

    ``status_code`` lets the router map the failure to the right HTTP status
    (400 bad request · 404 missing job · 409 not-ready/not-connected · 502 upstream
    platform error · 503 persistence layer unavailable).
    """

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.status_code = status_code
        super().__init__(message)


def require_ready() -> None:
    """Raise if the DB/oauth layer is unavailable (router maps to 503)."""
    if get_session is None or oauth_connect is None:
        raise NativePublishError(f"publishing persistence layer unavailable: {_DB_IMPORT_ERROR}", status_code=503)


def publish_reel_native(
    user_id: str,
    job_id: str,
    platform: str,
    *,
    title: str = "",
    caption: str = "",
    hashtags: tuple[str, ...] = (),
    privacy: str = "public",
    transport: Transport | None = None,
    oauth_client=None,
) -> PublishResult:
    """Publish a completed job's reel to ``platform`` via its native API.

    ``transport`` / ``oauth_client`` are injectable network seams (real HTTP by
    default) so the whole path is deterministically testable.
    """
    require_ready()
    plat = str(platform or "").strip().lower()
    connector = get_connector(plat)
    if connector is None:
        raise NativePublishError(
            f"unsupported platform {platform!r}; expected one of {list(available_platforms())}",
            status_code=400,
        )

    access_token, external_account_id = _valid_token(user_id, plat, oauth_client)
    final_key, source_context, watermark_source = _resolve_final_key(user_id, job_id)

    # Foreign-watermark cross-post guard: a clip auto-clipped from a pasted
    # TikTok/YouTube/etc. link (app.domains.clipping) still carries that
    # platform's watermark baked into the pixels. Posting it as-is to a
    # platform that suppresses rival watermarks (e.g. TikTok -> Instagram
    # Reels) silently tanks its reach, so this is checked BEFORE any network
    # call — the same policy already shared with the web/mobile composer
    # (``@reelforge/publishing-connectors``'s watermark-policy) just never
    # wired into this native-publish path.
    if watermark_source:
        reason = _watermark_block_reason(plat, watermark_source)
        if reason:
            _record(
                job_id, "held", f"watermark guard held reel: {reason}",
                {"platform": plat, "watermark_source": watermark_source},
            )
            raise NativePublishError(reason, status_code=409)

    video_url = ""
    video_path = ""
    from app.platform.storage.r2 import get_r2_client

    if plat in _URL_UPLOAD:
        video_url = get_r2_client().presign_get(final_key)
    if plat in _BYTE_UPLOAD:
        video_path = _download_temp(final_key, job_id)

    req = PublishRequest(
        platform=plat,
        access_token=access_token,
        video_url=video_url,
        video_path=video_path,
        title=title,
        caption=caption,
        hashtags=tuple(hashtags),
        privacy=privacy,
        external_account_id=external_account_id,
    )

    # Pre-publish CONTENT QUALITY + SAFETY gate. The generated caption/hook is
    # evaluated (Jev, one batched typed call) and a code-owned verdict is computed
    # BEFORE any dispatch. ``needs_edit``/``block`` (and low-confidence) hold the
    # reel for human review — the connector is never called. ``publish`` /
    # ``publish_with_review`` proceed; the latter is flagged. The gate degrades to
    # ``publish_with_review`` when the decision backend is unavailable and never
    # performs the publish itself. Always recorded on the job so the UI can show
    # why something was held.
    gate = _run_content_gate(plat, req)
    _persist_gate_result(job_id, gate)
    if not gate.can_publish:
        _record(
            job_id,
            "held",
            f"content gate held reel: {gate.decision}",
            {"platform": plat, "content_gate": gate.to_record()},
        )
        raise NativePublishError(
            f"content gate held this reel for review (decision={gate.decision}); "
            f"reasons: {_reasons_summary(gate)}",
            status_code=409,
        )

    try:
        result = connector.publish(req, transport=transport or RequestsTransport())
    except PublishError as exc:
        _record(
            job_id,
            "failed",
            str(exc),
            {"platform": plat, **_trace_payload(source_context)},
        )
        raise NativePublishError(str(exc), status_code=502) from exc
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except OSError:  # pragma: no cover - best-effort cleanup
                pass

    trace_payload = _trace_payload(source_context)
    result = replace(
        result,
        raw={
            **(result.raw if isinstance(result.raw, dict) else {}),
            **({"reelforge_trace": trace_payload} if trace_payload else {}),
        },
    )
    _record(
        job_id,
        result.status,
        f"published to {plat}",
        {
            "platform": plat,
            "external_id": result.external_id,
            "url": result.url,
            **trace_payload,
        },
    )
    logger.info(f"[{job_id}] native publish {plat} -> {result.status} id={result.external_id}")
    _rally_published(user_id, job_id, plat, result)
    return result


def publish_scheduled_reel_native(
    user_id: str,
    job_id: str,
    platforms: list[str],
    *,
    youtube_privacy_status: str = "private",
) -> dict:
    """Publish a scheduled reel through the owner's native OAuth connections.

    Scheduled publishing used to fall through the legacy shared Upload-Post
    account. This path deliberately dispatches the same native connectors as
    "Publish now", preserving creator account ownership at execution time.
    """
    normalized = [
        _SCHEDULE_PLATFORM_ALIASES.get(str(platform).strip().lower(), str(platform).strip().lower())
        for platform in platforms
        if str(platform).strip()
    ]
    if not normalized:
        raise NativePublishError("at least one platform is required", status_code=400)

    metadata = _social_metadata_for_job(user_id, job_id, normalized[0])
    results: list[dict] = []
    for platform in normalized:
        result = publish_reel_native(
            user_id,
            job_id,
            platform,
            title=str(metadata.get("title", "") or ""),
            caption=str(metadata.get("caption", "") or ""),
            hashtags=tuple(str(tag) for tag in (metadata.get("hashtags", []) or [])),
            privacy=youtube_privacy_status if platform == "youtube" else "public",
        )
        results.append(
            {
                "platform": result.platform,
                "status": result.status,
                "external_id": result.external_id,
                "url": result.url,
                **public_trace_result(result),
            }
        )

    return {
        "job_id": job_id,
        "platforms": normalized,
        "success": all(result["status"] != "failed" for result in results),
        "results": results,
    }


def resume_native_publish(
    user_id: str,
    job_id: str,
    platform: str,
    external_id: str,
    *,
    transport: Transport | None = None,
    oauth_client=None,
) -> PublishResult:
    """Re-poll a ``processing`` native publish and finish it when ready.

    Uses the owner's (refreshed) OAuth connection and the connector's
    ``resume`` step (Instagram: container status + ``media_publish``; TikTok:
    ``publish_id`` status fetch). Raises :class:`NativePublishError` on a
    terminal platform failure.
    """
    require_ready()
    plat = _SCHEDULE_PLATFORM_ALIASES.get(
        str(platform or "").strip().lower(), str(platform or "").strip().lower()
    )
    connector = get_connector(plat)
    resume = getattr(connector, "resume", None) if connector is not None else None
    if resume is None:
        raise NativePublishError(
            f"platform {platform!r} does not support resuming a publish", status_code=400
        )
    if not external_id:
        raise NativePublishError("missing platform publish id", status_code=400)
    access_token, external_account_id = _valid_token(user_id, plat, oauth_client)
    req = PublishRequest(
        platform=plat,
        access_token=access_token,
        external_account_id=external_account_id,
    )
    try:
        result = resume(req, external_id, transport=transport or RequestsTransport())
    except PublishError as exc:
        _record(job_id, "failed", str(exc), {"platform": plat, "external_id": external_id})
        raise NativePublishError(str(exc), status_code=502) from exc
    if result.status != "processing":
        _record(
            job_id,
            result.status,
            f"published to {plat}",
            {"platform": plat, "external_id": result.external_id, "url": result.url},
        )
        _rally_published(user_id, job_id, plat, result)
    return result


def track_processing_publish(user_id: str, job_id: str, result: PublishResult) -> None:
    """Queue an immediate publish that is still ``processing`` for re-polling.

    Best-effort: a tracking failure is logged, never raised, because the post
    was already dispatched to the platform.
    """
    if result.status != "processing" or get_session is None:
        return
    try:
        from datetime import datetime, timezone

        from app.models.db.repositories import ScheduledPublishRepository

        with get_session() as session:
            ScheduledPublishRepository(session).create_processing(
                user_id=str(user_id),
                job_id=job_id,
                platforms=[result.platform],
                result={
                    "job_id": job_id,
                    "platforms": [result.platform],
                    "success": True,
                    "results": [
                        {
                            "platform": result.platform,
                            "status": result.status,
                            "external_id": result.external_id,
                            "url": result.url,
                        }
                    ],
                },
                scheduled_at=datetime.now(timezone.utc),
            )
    except Exception as exc:  # noqa: BLE001 - the post itself already went out
        logger.error(f"[{job_id}] could not track processing publish: {exc}")


def require_native_connections(user_id: str, platforms: list[str]) -> None:
    """Fail before scheduling when any requested creator account is missing."""
    normalized = {
        _SCHEDULE_PLATFORM_ALIASES.get(str(platform).strip().lower(), str(platform).strip().lower())
        for platform in platforms
        if str(platform).strip()
    }
    for platform in sorted(normalized):
        if get_connector(platform) is None:
            raise NativePublishError(
                f"unsupported platform {platform!r}", status_code=400
            )
        # Refresh now when necessary and verify that this creator owns a usable
        # connection. The token is deliberately discarded and resolved again
        # by the due-runner at execution time.
        _valid_token(user_id, platform, None)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _valid_token(user_id: str, platform: str, oauth_client) -> tuple[str, str]:
    """Return (access_token, external_account_id) for a connected, fresh account."""
    with get_session() as session:  # type: ignore[misc]
        account = oauth_connect.refresh_if_needed(
            session, user_id, platform, client=oauth_client
        )
        if account is None:
            raise NativePublishError(
                f"no connected {platform!r} account; connect it under Settings → Connections first",
                status_code=409,
            )
        tokens = oauth_connect._decrypt_account(account)  # noqa: SLF001 - same package boundary
        return tokens.access_token, (tokens.external_account_id or "")


def _clip_watermark_source(job: Any) -> str:
    """The foreign platform a job's underlying clip was sourced from, if any.

    Clipping jobs ("paste a link -> auto-clip -> publish", see
    ``app.domains.clipping.platform_source``) tag each produced clip with a
    ``source_ref`` like ``"platform:tiktok:<hash>"`` when the source was a
    recognized social link. An avatar-reel / AI-generated job carries no such
    tag, so this returns ``""`` for the common case.
    """
    stages = dict(getattr(job, "stages", None) or {})
    clips = stages.get("clips")
    if not isinstance(clips, list):
        return ""
    for clip in clips:
        ref = str((clip or {}).get("source_ref") or "") if isinstance(clip, dict) else ""
        if ref.startswith("platform:"):
            return ref.split(":", 2)[1]
    return ""


def _watermark_block_reason(target_platform: str, watermark_source: str) -> str:
    """Empty when ``watermark_source`` may be cross-posted to ``target_platform``,
    else the user-facing reason it is held.

    Reuses the single, canonical foreign-watermark suppression table
    (``@reelforge/publishing-connectors``'s ``watermark-policy``, mirrored in
    ``reelforge_publishing_connectors`` for Python) so the web/mobile composer
    and this native-publish guard can never drift apart.
    """
    try:
        from reelforge_publishing_connectors import check_watermark
    except ModuleNotFoundError:  # monorepo path dep, not pip-installed (mirrors vfx.py)
        import sys as _sys
        from pathlib import Path as _Path

        _PUBLISHING_CONNECTORS = (
            _Path(__file__).resolve().parents[5] / "packages" / "publishing-connectors" / "python"
        )
        if str(_PUBLISHING_CONNECTORS) not in _sys.path:
            _sys.path.insert(0, str(_PUBLISHING_CONNECTORS))
        from reelforge_publishing_connectors import check_watermark

    result = check_watermark(target_platform, watermark_source)
    return str(result.get("reason") or "") if not result.get("allowed") else ""


def _resolve_final_key(user_id: str, job_id: str) -> tuple[str, dict, str]:
    """Resolve final output, bounded acquisition context, and watermark source
    (BOLA-guarded)."""
    with get_session() as session:  # type: ignore[misc]
        job = session.get(Job, job_id)
        if job is None or str(getattr(job, "user_id", "")) != str(user_id):
            raise NativePublishError(f"job not found: {job_id}", status_code=404)
        if job.state != const.TASK_STATE_COMPLETE:
            raise NativePublishError(f"job is not complete (state={job.state})", status_code=409)
        # MN5: a video soft-blocked after a content report is not published either.
        from app.domains.compliance.takedown import BLOCKED_MESSAGE, is_blocked

        if is_blocked(str(job_id)):
            raise NativePublishError(BLOCKED_MESSAGE, status_code=409)
        final_key = str(getattr(job, "result_key", "") or "").strip()
        if not final_key:
            asset = (
                session.query(Asset)
                .filter(Asset.job_id == job_id, Asset.kind == "final")
                .order_by(Asset.created_at.desc())
                .first()
            )
            final_key = str(getattr(asset, "r2_key", "") or "").strip() if asset else ""
        if not final_key:
            raise NativePublishError(f"job has no final output to publish: {job_id}", status_code=409)
        params = dict(getattr(job, "params", {}) or {})
        raw_source = params.get("source_context")
        source_context = raw_source if isinstance(raw_source, dict) else {}
        watermark_source = _clip_watermark_source(job)
        return final_key, source_context, watermark_source


def _trace_payload(source_context: dict) -> dict:
    """Return bounded job provenance for append-only native publish events."""
    if not source_context:
        return {}
    forecast_id = str(source_context.get("forecast_id") or "").strip()
    return {
        "source_context": source_context,
        **({"forecast_id": forecast_id} if forecast_id else {}),
    }


def public_trace_result(result: PublishResult) -> dict:
    """Expose only the forecast id from connector-private/raw publish data."""
    raw = result.raw if isinstance(result.raw, dict) else {}
    trace = raw.get("reelforge_trace")
    if not isinstance(trace, dict):
        return {}
    forecast_id = str(trace.get("forecast_id") or "").strip()
    return {"forecast_id": forecast_id} if forecast_id else {}


def _social_metadata_for_job(user_id: str, job_id: str, platform: str) -> dict:
    """Generate scheduled-post copy from the owner's persisted reel brief."""
    with get_session() as session:  # type: ignore[misc]
        job = session.get(Job, job_id)
        if job is None or str(getattr(job, "user_id", "")) != str(user_id):
            raise NativePublishError(f"job not found: {job_id}", status_code=404)
        params = dict(getattr(job, "params", {}) or {})

    # Ad Studio carrier jobs carry the ad's own reviewed post copy; post exactly
    # that instead of generating new copy (the content gate still judges it).
    prepared = params.get("social_metadata") if params.get("source") == "adstudio" else None
    if isinstance(prepared, dict) and str(prepared.get("caption") or "").strip():
        return {
            "title": str(prepared.get("title") or ""),
            "caption": str(prepared.get("caption") or ""),
            "hashtags": [str(t) for t in (prepared.get("hashtags") or []) if str(t).strip()],
        }

    from app.services.llm import generate_social_metadata

    return generate_social_metadata(
        video_subject=str(params.get("video_subject", "") or "ReelForge video"),
        video_script=str(params.get("video_script", "") or ""),
        language=str(params.get("language", "auto") or "auto"),
        platform=platform,
    )


def _download_temp(final_key: str, job_id: str) -> str:
    """Presign + stream the final MP4 to a local temp file (YouTube byte upload)."""
    import tempfile

    import requests

    from app.platform.storage.r2 import get_r2_client

    url = get_r2_client().presign_get(final_key)
    fd, local_path = tempfile.mkstemp(prefix=f"native_{job_id}_", suffix=".mp4")
    try:
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
    except Exception:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:  # pragma: no cover
                pass
        raise
    return local_path


def _run_content_gate(platform: str, req: PublishRequest) -> GateResult:
    """Evaluate the reel's generated caption/hook through the pre-publish gate.

    Judges the exact copy that would be posted (caption + hook). The hook is the
    title when present, else the caption's first line. Treats the copy as
    untrusted data; the gate itself degrades gracefully and never raises here.
    """
    caption = str(req.caption or "")
    hook = str(req.title or "").strip()
    if not hook:
        hook = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    context = GateContext(platform=platform)
    return evaluate_content_sync(caption, hook, context)


def _persist_gate_result(job_id: str, gate: GateResult) -> None:
    """Persist the gate verdict on the job's ``stages`` JSON (best-effort).

    Rides inside the ``stages`` map under a private ``_content_gate`` key (no
    schema migration — mirrors the ``_result_media`` clip-descriptor pattern), so
    the read path can surface it as ``content_gate`` and the UI can show why a
    reel was held. Immutable update; a persistence hiccup must not break publish.
    """
    if get_session is None or Job is None:
        return
    try:
        record = gate.to_record()
        with get_session() as session:  # type: ignore[misc]
            job = session.get(Job, job_id)
            if job is None:
                return
            stages = dict(getattr(job, "stages", {}) or {})
            stages["_content_gate"] = record
            job.stages = stages
    except Exception as exc:  # noqa: BLE001 - the record is best-effort telemetry
        logger.warning(f"[{job_id}] could not persist content-gate result: {exc}")


def _reasons_summary(gate: GateResult) -> str:
    """A short, secret-free one-liner of the reasons that drove a hold."""
    parts = [f"{key}: {value}" for key, value in gate.reasons.items()]
    return "; ".join(parts) if parts else gate.decision


def _rally_published(user_id: str, job_id: str, platform: str, result: PublishResult) -> None:
    """Rally ``reel_published`` on a live post (no-op unless RALLY_EVENTS_KEY)."""
    if result.status != "published":
        return
    try:
        from app.integrations.rally import track_reel_published

        track_reel_published(str(user_id), job_id, platform, str(result.external_id or ""))
    except Exception as exc:  # noqa: BLE001 - lifecycle events never fail a publish
        logger.debug(f"[{job_id}] rally publish event skipped: {exc}")


def _record(job_id: str, status: str, message: str, payload: dict | None = None) -> None:
    """Best-effort ``JobEvent`` audit for the native-publish stage (never raises)."""
    try:
        from app.telemetry import events as telemetry_events

        telemetry_events.record_event(
            job_id, "publish", f"native_{status}", message=message, payload=payload or {}
        )
    except Exception:  # pragma: no cover - telemetry is best-effort
        pass
