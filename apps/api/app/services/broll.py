"""AI B-roll cutaways — suggest + fetch short stock clips for a reel.

This module repurposes MoneyPrinterTurbo's already-vendored stock-footage path
(``app.services.material``) as an *optional* creative overlay for ReelForge. The
main ReelForge pipeline never sources stock footage (see
``tests/reelforge/test_no_stock_sourcing.py``); B-roll is a separate, opt-in
feature that a caller explicitly requests. A chosen clip is spliced as a brief,
**muted** INTRO (before the hook) and/or OUTRO (after) around the composed reel
— the main reel keeps its full audio + captions.

Design contract:

* **Best-effort** — a B-roll failure NEVER fails the job. Every public entry
  point swallows its errors and returns an empty/None result instead of raising.
* **Security** — a *client-supplied* B-roll R2 key must belong to the caller's
  own job. :func:`get_broll_local` reuses the ownership guard added by the
  ReelForge audit (``reelforge._assert_owned_r2_key``) when a ``job_id`` is
  supplied, so a caller cannot exfiltrate another creator's per-job artifact.
* **No secrets** — nothing here logs or persists API keys; the underlying
  ``material`` module already redacts provider keys from its own errors.
* **Guarded optional imports** — heavy/optional deps (moviepy, ffprobe, boto3,
  the ReelForge guard) are imported lazily inside functions so that merely
  importing this module never crashes the pipeline.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from loguru import logger

from app.models.schema import VideoAspect

# --------------------------------------------------------------------------- #
# Tunables (no magic numbers scattered through the code)
# --------------------------------------------------------------------------- #
#: Hard cap on how many clips a single suggestion request may fetch. Keeps LLM
#: term generation, provider search and R2 uploads bounded regardless of what a
#: caller passes for ``amount``.
MAX_BROLL_AMOUNT: int = 12

#: Individual B-roll cutaways are intentionally short (intro/outro stingers).
_BROLL_CLIP_SECONDS: int = 5

#: R2 content type + key layout for uploaded B-roll clips.
_BROLL_CONTENT_TYPE: str = "video/mp4"

#: ``source`` value that routes a suggestion request to the AI generation
#: backend (ComfyUI/Wan via ``broll_gen``) instead of stock-footage providers.
_AI_SOURCE: str = "ai"

#: AI generation is far costlier than a stock fetch (30-120s of GPU per clip),
#: so an ``source="ai"`` request is capped tighter than the stock ceiling.
MAX_AI_BROLL_AMOUNT: int = 4


def _clamp_amount(amount: int) -> int:
    """Clamp a caller-supplied ``amount`` into ``[1, MAX_BROLL_AMOUNT]``.

    Non-integer / negative input degrades to a single clip rather than raising,
    keeping the best-effort contract intact at the boundary.
    """
    try:
        value = int(amount)
    except (TypeError, ValueError):
        return 1
    if value < 1:
        return 1
    return min(value, MAX_BROLL_AMOUNT)


def _derive_terms(subject: str, script: str, amount: int) -> list[str]:
    """Derive stock-search keywords for ``subject`` / ``script``.

    Primary source is ``llm.generate_terms``; when that yields nothing (provider
    failure, empty response) we fall back to the distinct words of ``subject`` so
    a suggestion request still has *something* to search for. Never raises.
    """
    subject = (subject or "").strip()
    try:
        from app.services import llm

        terms = llm.generate_terms(
            video_subject=subject,
            video_script=script or "",
            amount=amount,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort: fall back below
        logger.warning(
            f"broll: term generation failed, falling back to subject words: "
            f"{type(exc).__name__}: {exc}"
        )
        terms = []

    cleaned = [t.strip() for t in (terms or []) if isinstance(t, str) and t.strip()]
    if cleaned:
        return cleaned[:amount]

    # Fallback: distinct, order-preserving words from the subject.
    fallback: list[str] = []
    seen: set[str] = set()
    for word in subject.split():
        token = word.strip()
        key = token.lower()
        if token and key not in seen:
            seen.add(key)
            fallback.append(token)
    return fallback[:amount] if fallback else ([subject] if subject else [])


def _probe_duration(local_path: str) -> float:
    """Return the duration (seconds) of ``local_path``, or ``0.0`` on any failure.

    Tries ffprobe first (cheap, no full decode) via the compose module's probe,
    then falls back to moviepy. Both imports are optional and guarded, so a
    missing binary/dependency degrades to ``0.0`` rather than raising.
    """
    try:
        from app.services.compose.compose_ffmpeg import _probe_video

        info = _probe_video(local_path)
        if info is not None and info.duration and info.duration > 0:
            return float(info.duration)
    except Exception as exc:  # noqa: BLE001 - fall through to moviepy
        logger.debug(f"broll: ffprobe duration failed for {local_path!r}: {exc}")

    clip = None
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip

        clip = VideoFileClip(local_path)
        if clip.duration and clip.duration > 0:
            return float(clip.duration)
    except Exception as exc:  # noqa: BLE001 - best-effort: unknown duration
        logger.debug(f"broll: moviepy duration failed for {local_path!r}: {exc}")
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass
    return 0.0


def _upload_broll_clip(job_id: str, local_path: str) -> str:
    """Upload ``local_path`` to ``jobs/<job_id>/broll/<uuid>.mp4`` and return the key.

    Raises on failure so the per-clip caller can log-and-skip; the object key is
    generated server-side (never client-supplied), so uploaded clips are always
    scoped to *this* job.
    """
    from app.services.storage.r2 import get_r2_client

    key = f"jobs/{job_id}/broll/{uuid4().hex}.mp4"
    get_r2_client().upload_file(local_path, key, _BROLL_CONTENT_TYPE)
    return key


def _aspect_dimensions(aspect: VideoAspect) -> tuple[int, int]:
    """Return ``(width, height)`` for an aspect, defaulting to portrait 1080x1920.

    Best-effort: an unrecognised aspect degrades to portrait rather than raising,
    keeping the AI path aligned with the stock path's tolerant validation.
    """
    try:
        if aspect == VideoAspect.landscape:
            return 1920, 1080
        if aspect == VideoAspect.square:
            return 1080, 1080
    except Exception:  # noqa: BLE001 - unknown enum member: fall through
        pass
    return 1080, 1920


def _suggest_broll_ai(
    job_id: str,
    subject: str,
    script: str,
    amount: int,
    aspect: VideoAspect,
) -> list[dict[str, Any]]:
    """Generate short AI motion clips as B-roll (``source="ai"``), best-effort.

    Mirrors the stock path's contract but swaps the ``material.download_videos``
    fetch for per-prompt calls to the ``broll_gen`` provider (ComfyUI/Wan on a
    serverless GPU). Each generated clip is re-hosted to R2 under the same
    ``jobs/<job_id>/broll/<uuid>.mp4`` layout, so the returned records — and the
    BOLA ownership guard in :func:`get_broll_local` — are identical to stock.

    Returns up to ``amount`` records ``{"broll_key","duration","source":"ai",
    "term"}`` or ``[]`` on any failure. A generation failure never fails the job:
    the provider itself returns ``None`` rather than raising, and this function
    additionally guards the whole flow.
    """
    capped = min(_clamp_amount(amount), MAX_AI_BROLL_AMOUNT)

    try:
        from app.domains.broll import get_broll_provider

        provider = get_broll_provider()
    except Exception as exc:  # noqa: BLE001 - no provider registered: degrade
        logger.warning(
            f"broll: AI provider unavailable for job={job_id!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return []

    if not provider.is_enabled():
        logger.info(
            "broll: AI source requested but broll_gen provider is not configured; "
            "no suggestions"
        )
        return []

    prompts = _derive_terms(subject, script, capped)
    if not prompts:
        logger.info("broll: no AI prompts could be derived; no suggestions")
        return []

    width, height = _aspect_dimensions(aspect)
    suggestions: list[dict[str, Any]] = []
    for prompt in prompts[:capped]:
        try:
            clip = provider.generate_clip(
                prompt,
                mode="t2v",
                width=width,
                height=height,
                duration_s=float(_BROLL_CLIP_SECONDS),
            )
        except Exception as exc:  # noqa: BLE001 - defensive: provider shouldn't raise
            logger.warning(
                f"broll: AI generation raised for prompt={prompt!r} "
                f"(job={job_id!r}): {type(exc).__name__}: {exc}"
            )
            continue
        if not clip or not clip.get("clip_path"):
            logger.info(f"broll: AI generation returned nothing for prompt={prompt!r}")
            continue

        local_path = clip["clip_path"]
        try:
            broll_key = _upload_broll_clip(job_id, local_path)
        except Exception as exc:  # noqa: BLE001 - skip this clip, keep the rest
            logger.warning(
                f"broll: AI clip upload failed for {local_path!r} "
                f"(job={job_id!r}): {type(exc).__name__}: {exc}"
            )
            continue
        finally:
            _cleanup_temp(local_path)

        duration = clip.get("duration") or _probe_duration(local_path)
        suggestions.append(
            {
                "broll_key": broll_key,
                "duration": float(duration or 0.0),
                "source": _AI_SOURCE,
                "term": prompt,
            }
        )

    logger.info(
        f"broll: generated {len(suggestions)} AI clip(s) for job={job_id!r} "
        f"(requested={capped})"
    )
    return suggestions


def _cleanup_temp(local_path: str) -> None:
    """Remove a provider-produced temp clip after re-hosting, best-effort."""
    try:
        import os

        if local_path and os.path.exists(local_path):
            os.remove(local_path)
    except Exception:  # noqa: BLE001 - cleanup is best-effort
        pass


def suggest_broll(
    job_id: str,
    subject: str,
    script: str = "",
    source: str = "pexels",
    amount: int = 6,
    aspect: VideoAspect = VideoAspect.portrait,
) -> list[dict[str, Any]]:
    """Suggest short, relevant B-roll clips for a reel (best-effort).

    Two backends behind one contract, selected by ``source``:

    * ``source="ai"`` — generate AI motion clips (text→video) via the
      ``broll_gen`` provider (ComfyUI/Wan on a serverless GPU). See
      :func:`_suggest_broll_ai`.
    * any other value (``pexels``/``pixabay``/``coverr``, default) — fetch stock
      footage. Pipeline:

      1. Derive search keywords from ``subject`` / ``script`` via
         ``llm.generate_terms`` (falling back to subject words).
      2. Fetch short stock clips through ``material.download_videos`` — reusing
         MPT's Pexels / Pixabay / Coverr integration + 24h search cache.
      3. Upload each fetched clip to R2 under ``jobs/<job_id>/broll/<uuid>.mp4``
         and return a lightweight suggestion record per clip.

    :returns: up to ``amount`` dicts, each shaped like::

        {"broll_key": str, "duration": float, "source": str, "term": str}

        (``duration`` may be ``0.0`` when it could not be probed.) Returns an
        empty list on *any* failure — a B-roll failure never fails the job.
    """
    job_id = (job_id or "").strip()
    if not job_id:
        logger.warning("broll: suggest_broll called without a job_id; skipping")
        return []

    capped = _clamp_amount(amount)
    source = (source or "pexels").strip() or "pexels"

    # AI generation is a wholly separate backend (GPU, not stock search).
    if source == _AI_SOURCE:
        try:
            return _suggest_broll_ai(job_id, subject, script, capped, aspect)
        except Exception as exc:  # noqa: BLE001 - best-effort: [] on any failure
            logger.warning(
                f"broll: AI suggestion failed for job={job_id!r}: "
                f"{type(exc).__name__}: {exc}"
            )
            return []

    try:
        video_aspect = VideoAspect(aspect)
    except (ValueError, KeyError):
        logger.warning(f"broll: unknown aspect {aspect!r}; defaulting to portrait")
        video_aspect = VideoAspect.portrait

    try:
        terms = _derive_terms(subject, script, capped)
        if not terms:
            logger.info("broll: no search terms could be derived; no suggestions")
            return []

        from app.services import material

        # Fetch roughly ``capped`` short clips: download_videos stops once the
        # accumulated clip duration exceeds ``audio_duration``, so sizing the
        # budget to ``capped * clip_seconds`` bounds the fetch to ~capped clips.
        local_paths = material.download_videos(
            task_id=job_id,
            search_terms=terms,
            source=source,
            video_aspect=video_aspect,
            audio_duration=float(capped * _BROLL_CLIP_SECONDS),
            max_clip_duration=_BROLL_CLIP_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort: no clips on failure
        logger.warning(
            f"broll: fetch failed for job={job_id!r}: {type(exc).__name__}: {exc}"
        )
        return []

    suggestions: list[dict[str, Any]] = []
    for index, local_path in enumerate(local_paths or []):
        if len(suggestions) >= capped:
            break
        if not local_path:
            continue
        try:
            broll_key = _upload_broll_clip(job_id, local_path)
        except Exception as exc:  # noqa: BLE001 - skip this clip, keep the rest
            logger.warning(
                f"broll: upload failed for {local_path!r} "
                f"(job={job_id!r}): {type(exc).__name__}: {exc}"
            )
            continue
        # download_videos returns paths, not the term that produced each; assign
        # terms cyclically as a best-effort label for the UI (approximate).
        term = terms[index % len(terms)] if terms else ""
        suggestions.append(
            {
                "broll_key": broll_key,
                "duration": _probe_duration(local_path),
                "source": source,
                "term": term,
            }
        )

    logger.info(
        f"broll: suggested {len(suggestions)} clip(s) for job={job_id!r} "
        f"(source={source}, requested={capped})"
    )
    return suggestions


def get_broll_local(
    broll_key: str,
    job_id: str = "",
    dest_path: str | None = None,
) -> str | None:
    """Download a B-roll clip from R2 to a local path (best-effort).

    :param broll_key: the R2 object key (e.g. from :func:`suggest_broll`).
    :param job_id: when supplied, the *caller's* job id. A client-supplied
        ``broll_key`` is validated against it via the ReelForge ownership guard
        so a caller cannot fetch another creator's per-job artifact
        (``jobs/<victim>/...``). Omit only for server-generated keys.
    :param dest_path: optional destination; a temp file is used when unset.
    :returns: the local path on success, or ``None`` on any failure (missing
        dependency, ownership violation, network error). Never raises.
    """
    key = (broll_key or "").strip()
    if not key:
        logger.warning("broll: get_broll_local called without a broll_key")
        return None

    # Security: a client-supplied key must belong to the caller's own job. Reuse
    # the audited BOLA guard rather than re-implementing the check here.
    if job_id:
        try:
            from app.services.reelforge import _assert_owned_r2_key

            _assert_owned_r2_key(job_id, key)
        except PermissionError as exc:
            logger.warning(f"broll: refusing cross-tenant B-roll key: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 - guard unavailable: fail closed
            logger.warning(
                f"broll: could not verify ownership of {key!r}; refusing: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    try:
        import os
        import tempfile

        import requests

        from app.services.storage.r2 import get_r2_client

        if not dest_path:
            fd, dest_path = tempfile.mkstemp(prefix="broll-", suffix=".mp4")
            os.close(fd)

        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        url = get_r2_client().presign_get(key)
        with requests.get(url, stream=True, timeout=300) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
        return dest_path
    except Exception as exc:  # noqa: BLE001 - best-effort: None on any failure
        logger.warning(
            f"broll: download failed for key={key!r}: {type(exc).__name__}: {exc}"
        )
        return None
