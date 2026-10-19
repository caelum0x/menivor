"""Clipping orchestrator: long recording -> vertical caption-burned shorts.

A thin orchestrator (mirrors ``domains/broll/service.py`` +
``domains/repurpose/service.py``) that wires the pipeline through INJECTED
collaborators so it is fully testable with fakes:

    (1) transcriber  -> WhisperX word timings (single timing authority)
    (2) ranker       -> score coarse windows into viral-moment candidates
    (3) policy       -> select highlights + snap to word-boundary cut points
    (4) cutter       -> ffmpeg segment-extract + crop-to-vertical + burn captions
    (5) composer     -> optional cross-fade stitch (services/compose/transitions)
    (6) result       -> per-clip vertical RenderSpec drafts (+ optional publish)

Robustness discipline adapted (not pasted) from the upstream asset_manager:
fail fast with clear guards, and NEVER silently swallow a partial output (the
``audio.py`` anti-pattern) nor do substring-gated ``os.unlink``/``rmtree`` (the
``main.py`` anti-pattern). Temp cleanup is best-effort via a scoped tempdir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from loguru import logger

from app.domains.clipping import policy
from app.domains.clipping.policy import ClipPlan, Word
from app.domains.templates.render_spec import (
    CaptionCue,
    MediaBinding,
    RenderSpec,
    SegmentSpec,
)

# Vertical short-form target frame (1080x1920 == 9:16).
PORTRAIT_W = 1080
PORTRAIT_H = 1920
ASPECT_LABEL = "9:16"


class ClippingError(Exception):
    """A caller-facing clipping failure (HTTP status + safe message)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --------------------------------------------------------------------------- #
# Collaborator seams (Protocols) — fakes in tests, real impls in production.
# --------------------------------------------------------------------------- #
class Transcriber(Protocol):
    def __call__(self, audio_path: str, language: str = "auto") -> Sequence[object]: ...


class Ranker(Protocol):
    def __call__(
        self, segments: list[dict], *, language: str = "auto"
    ) -> list[dict]: ...


class Cutter(Protocol):
    def __call__(
        self,
        source_path: str,
        start_s: float,
        end_s: float,
        out_path: str,
        *,
        words: Sequence[object] | None = None,
        caption_preset: str | None = None,
    ) -> str: ...


class Composer(Protocol):
    def __call__(self, clip_paths: Sequence[str], out_path: str) -> str: ...


# --------------------------------------------------------------------------- #
# Result DTOs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ClipDraft:
    """A produced clip: its source window + the vertical-reframed RenderSpec."""

    source_in_s: float
    source_out_s: float
    source_ref: str
    plan: ClipPlan
    render_spec: RenderSpec
    result_path: str = ""
    result_key: str = ""

    def to_dict(self) -> dict:
        return {
            "source_in_s": self.source_in_s,
            "source_out_s": self.source_out_s,
            "start_s": self.source_in_s,
            "end_s": self.source_out_s,
            "source_ref": self.source_ref,
            "score": self.plan.score,
            "title": self.plan.title,
            "hook": self.plan.hook,
            "transcript": self.plan.transcript,
            "reason": self.plan.reason,
            "length_s": self.plan.length_s,
            "aspect": self.render_spec.aspect,
            "result_path": self.result_path,
            "result_key": self.result_key,
            "render_spec": self.render_spec.to_dict(),
        }


@dataclass(frozen=True)
class ClippingResult:
    """The outcome of a clipping run."""

    drafts: tuple[ClipDraft, ...] = ()
    clip_paths: tuple[str, ...] = ()
    stitched_path: str = ""
    stitched_key: str = ""
    note: str = ""

    @property
    def clip_count(self) -> int:
        return len(self.drafts)

    def to_dict(self) -> dict:
        return {
            "clips": [d.to_dict() for d in self.drafts],
            "clip_paths": list(self.clip_paths),
            "stitched_path": self.stitched_path,
            "stitched_key": self.stitched_key,
            "clip_count": len(self.drafts),
            "note": self.note,
        }


@dataclass
class ClipRequest:
    """Normalised clipping parameters (plain dataclass, not the HTTP DTO)."""

    language: str = "auto"
    target_count: int = 3
    min_len_s: int = 15
    max_len_s: int = 60
    score_floor: int = 50
    captions: str | None = "hormozi"
    transitions: bool = True
    publish_targets: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Pure draft builder (RenderSpec) — testable without any collaborator.
# --------------------------------------------------------------------------- #
def build_draft(
    plan: ClipPlan,
    *,
    source_ref: str = "",
    caption_style: str | None = "hormozi",
    result_path: str = "",
) -> ClipDraft:
    """Build a vertical-reframed :class:`RenderSpec` draft for one clip.

    The clip is reframed to a 9:16 crop-to-fill portrait frame with a single
    segment covering ``[0, length_s]`` (its own timeline), the clip's transcript
    as a burned caption cue, and the source window recorded for the extractor.
    Pure + deterministic.
    """
    length = plan.length_s
    caption: CaptionCue | None = None
    if caption_style and plan.transcript:
        caption = CaptionCue(text=plan.transcript, style=str(caption_style))

    segment = SegmentSpec(
        role="clip",
        order=0,
        t_start=0.0,
        t_end=length,
        track="video",
        media=(MediaBinding(track="video", kind="clip", ref=source_ref),),
        caption=caption,
        label=f"src={plan.start_s:g}-{plan.end_s:g}",
    )
    spec = RenderSpec(
        template_slug="clipping",
        template_version="1",
        genre="clip",
        aspect=ASPECT_LABEL,
        layout="fill",
        duration_s=length,
        segments=(segment,),
        caption_style=str(caption_style) if caption_style else "none",
    )
    return ClipDraft(
        source_in_s=plan.start_s,
        source_out_s=plan.end_s,
        source_ref=source_ref,
        plan=plan,
        render_spec=spec,
        result_path=result_path,
    )


def _words_in_window(
    words: Sequence[object], start_s: float, end_s: float
) -> list[Word]:
    """Return the (re-based) words overlapping ``[start_s, end_s]``.

    Timings are shifted to the clip's own timeline (origin at ``start_s``) so
    burned captions line up with the extracted segment.
    """
    out: list[Word] = []
    for item in words or []:
        w = policy._as_word(item)  # noqa: SLF001 - shared coercion helper
        if w is None:
            continue
        if w.end_s > start_s and w.start_s < end_s:
            out.append(
                Word(
                    text=w.text,
                    start_s=round(max(0.0, w.start_s - start_s), 3),
                    end_s=round(max(0.0, w.end_s - start_s), 3),
                )
            )
    return out


class ClippingService:
    """Wire the long->short pipeline through injected collaborators."""

    def __init__(
        self,
        *,
        transcriber: Transcriber | None = None,
        ranker: Ranker | None = None,
        cutter: Cutter | None = None,
        composer: Composer | None = None,
    ) -> None:
        self._transcriber = transcriber
        self._ranker = ranker
        self._cutter = cutter
        self._composer = composer

    # ------------------------------------------------------------------ #
    # Pure planning (no I/O) — "transcript -> ranked clip segments".
    # ------------------------------------------------------------------ #
    def plan(
        self,
        words: Sequence[object],
        ranked_segments: Sequence[object],
        request: ClipRequest,
    ) -> list[ClipPlan]:
        """Select + snap highlight windows into concrete clip plans."""
        return policy.plan_clips(
            words,
            ranked_segments,
            target_count=request.target_count,
            min_len_s=request.min_len_s,
            max_len_s=request.max_len_s,
            score_floor=request.score_floor,
        )

    def drafts_for(
        self, plans: Sequence[ClipPlan], request: ClipRequest, *, source_ref: str = ""
    ) -> list[ClipDraft]:
        """Build a vertical RenderSpec draft per plan (no rendering)."""
        return [
            build_draft(p, source_ref=source_ref, caption_style=request.captions)
            for p in plans
        ]

    # ------------------------------------------------------------------ #
    # Full pipeline (I/O via injected seams).
    # ------------------------------------------------------------------ #
    def process(
        self,
        source_path: str,
        request: ClipRequest,
        *,
        source_ref: str = "",
        workdir: str | None = None,
    ) -> ClippingResult:
        """Run the clipping pipeline over a local ``source_path``.

        Transcribe -> rank coarse windows -> select + snap -> (optional) extract
        each vertical clip and stitch. When no speech is detected the run returns
        an empty result with an explanatory note rather than raising — an empty
        transcript is a legitimate outcome, not a failure.
        """
        if self._transcriber is None:
            raise ClippingError(500, "no transcriber configured")
        if not source_path or not os.path.exists(source_path):
            raise ClippingError(400, f"source file not found: {source_path!r}")

        words = list(self._transcriber(source_path, request.language) or [])
        if not words:
            logger.info(f"clipping: no speech detected in {source_path!r}")
            return ClippingResult(note="no speech detected")

        segments = policy.segments_from_words(words, window_s=request.max_len_s)
        ranker = self._ranker or _default_ranker
        scored = list(ranker(segments, language=request.language) or [])

        plans = self.plan(words, scored, request)
        drafts = self.drafts_for(plans, request, source_ref=source_ref)
        if not plans:
            return ClippingResult(note="no clips passed the selection policy")

        clip_paths: list[str] = []
        rendered_drafts: list[ClipDraft] = list(drafts)
        if self._cutter is not None and workdir is not None:
            clip_paths, rendered_drafts = self._render_clips(
                source_path, plans, drafts, request, words, workdir
            )

        stitched = ""
        if (
            request.transitions
            and self._composer is not None
            and policy.should_stitch(plans)
            and len(clip_paths) > 1
        ):
            stitched = self._composer(
                clip_paths, os.path.join(workdir or ".", "stitched.mp4")
            )

        return ClippingResult(
            drafts=tuple(rendered_drafts),
            clip_paths=tuple(clip_paths),
            stitched_path=stitched,
        )

    # ------------------------------------------------------------------ #
    # DB-backed worker entry (thin — no business logic lives in the Celery
    # wrapper). Loads the job, resolves its source to a local file, runs the
    # pipeline, and persists the produced clips + stitched artifact.
    # ------------------------------------------------------------------ #
    @classmethod
    def run(cls, job_id: str) -> dict:
        """Execute a persisted ``Job(kind='clipping')`` end to end.

        Returns the serialized :class:`ClippingResult`. Raises
        :class:`ClippingError` on any unrecoverable failure so the Celery wrapper
        marks the job failed (and releases the wallet reservation).
        """
        import tempfile

        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        job_id = (job_id or "").strip()
        if not job_id:
            raise ClippingError(400, "job_id is required")

        with get_session() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                raise ClippingError(404, "clipping job not found")
            params = dict(job.params or {})
            user_id = str(job.user_id)

        request = request_from_params(params)
        service = build_default_service()

        with tempfile.TemporaryDirectory(prefix="clipping_") as workdir:
            source_path, source_ref = _resolve_source(params, workdir)
            result = service.process(
                source_path, request, source_ref=source_ref, workdir=workdir
            )
            result = _durabilize_result(user_id, job_id, result)

        cls._persist_result(job_id, result)
        return result.to_dict()

    @staticmethod
    def _persist_result(job_id: str, result: "ClippingResult") -> None:
        """Persist produced clip drafts into ``stages`` and mark the job complete."""
        from app.models.db.base import get_session
        from app.models.db.repositories import JobRepository

        with get_session() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is not None:
                stages = dict(job.stages or {})
                stages["clips"] = [d.to_dict() for d in result.drafts]
                stages["clipping"] = "done"
                stages["stitched_key"] = result.stitched_key
                job.stages = stages
                job.progress = 100
                session.flush()
            primary_key = result.stitched_key or next(
                (draft.result_key for draft in result.drafts if draft.result_key), ""
            )
            repo.mark_complete(job_id, primary_key)

    def _render_clips(
        self,
        source_path: str,
        plans: Sequence[ClipPlan],
        drafts: Sequence[ClipDraft],
        request: ClipRequest,
        words: Sequence[object],
        workdir: str,
    ) -> tuple[list[str], list[ClipDraft]]:
        """Extract each vertical, caption-burned clip via the injected cutter.

        A single clip's extraction failure is fatal for the run (fail-fast, no
        silent partial-output swallowing): the caller marks the job failed.
        """
        assert self._cutter is not None
        os.makedirs(workdir, exist_ok=True)
        clip_paths: list[str] = []
        rebuilt: list[ClipDraft] = []
        for index, (plan, draft) in enumerate(zip(plans, drafts)):
            out_path = os.path.join(workdir, f"clip_{index:02d}.mp4")
            clip_words = _words_in_window(words, plan.start_s, plan.end_s)
            path = self._cutter(
                source_path,
                plan.start_s,
                plan.end_s,
                out_path,
                words=clip_words,
                caption_preset=request.captions,
            )
            if not path or not os.path.exists(path):
                raise ClippingError(
                    502, f"clip extraction produced no output for clip {index}"
                )
            clip_paths.append(path)
            rebuilt.append(
                build_draft(
                    plan,
                    source_ref=draft.source_ref,
                    caption_style=request.captions,
                    result_path=path,
                )
            )
        return clip_paths, rebuilt


# --------------------------------------------------------------------------- #
# Default (production) collaborators — lazily import heavy deps so the module
# stays importable (and unit-testable) without the ML / ffmpeg stack present.
# --------------------------------------------------------------------------- #
def default_transcriber(audio_path: str, language: str = "auto") -> list[Word]:
    """Real transcriber: WhisperX word timings via ``services/transcribe``."""
    from app.services.transcribe import transcribe_to_words

    timings = transcribe_to_words(
        audio_path, None if language in ("", "auto") else language
    )
    return [
        Word(text=t.text, start_s=float(t.start), end_s=float(t.end)) for t in timings
    ]


def _default_ranker(segments: list[dict], *, language: str = "auto") -> list[dict]:
    """Real ranker: reuse the repurpose LLM virality ranker (503 when absent)."""
    from app.domains.repurpose.service import _default_ranker as repurpose_ranker

    return repurpose_ranker(segments, language=language)


def default_cutter(
    source_path: str,
    start_s: float,
    end_s: float,
    out_path: str,
    *,
    words: Sequence[object] | None = None,
    caption_preset: str | None = None,
) -> str:
    """Real cutter: extract ``[start_s, end_s]``, crop-to-vertical, burn captions.

    Reuses ``compose_ffmpeg`` conventions (crop-to-fill via ``_fill_node``, the
    ``_run_ffmpeg`` runner, ``_escape_ass_filter_path``) rather than the naive
    scale+crop from the upstream project. Caption burning is best-effort: when an
    ``.ass`` cannot be produced the clip is still extracted un-captioned.
    """
    from app.services.compose.compose_ffmpeg import (
        _escape_ass_filter_path,
        _fill_node,
        _run_ffmpeg,
    )
    from app.utils import utils

    ffmpeg = utils.get_ffmpeg_binary()
    graph = _fill_node("0:v", "v", PORTRAIT_W, PORTRAIT_H)
    video_map = "[v]"

    ass_path = ""
    if caption_preset and words:
        ass_path = _write_captions(words, caption_preset, out_path)
    if ass_path:
        esc = _escape_ass_filter_path(ass_path)
        graph = f"{graph};[v]ass={esc}[vc]"
        video_map = "[vc]"

    duration = max(0.0, float(end_s) - float(start_s))
    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{float(start_s):.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        source_path,
        "-filter_complex",
        graph,
        "-map",
        video_map,
        "-map",
        "0:a?",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        out_path,
    ]
    _run_ffmpeg(command)
    return out_path


def _write_captions(words: Sequence[object], preset: str, near_path: str) -> str:
    """Write an ``.ass`` for the clip words via the captions service (best-effort).

    Presets that live in the shared ``reelforge_caption_engine`` registry (e.g.
    ``hormozi``) are burned through that shared builder so the subtitle matches
    the look the web caption preview advertises for that preset; a bundled-font
    substitution keeps libass from tofu-ing the display weight. Any other preset
    id falls back to the self-contained karaoke builder + its style registry.
    """
    try:
        from app.services.captions._engine import shared_preset
        from app.services.captions.ass_karaoke import (
            BURN_FONT_SUBSTITUTIONS,
            engine_preset_ids,
            turkish_upper,
            write_ass,
            write_ass_engine,
        )
        from app.services.captions.presets import get_caption_style
        from app.services.captions.words import (
            WordTiming,
            group_words_into_phrases,
        )

        timings = [
            WordTiming(
                getattr(w, "text", ""),
                float(getattr(w, "start_s", 0.0)),
                float(getattr(w, "end_s", 0.0)),
            )
            for w in words
        ]
        ass_path = os.path.splitext(near_path)[0] + ".ass"

        if preset in engine_preset_ids():
            # Burn the shared-engine LOOK (font/colour/size/grouping/timing) so
            # the subtitle matches the preset the web preview advertises, with a
            # bundled-font substitution so libass resolves the display weight
            # instead of tofu-ing it. Uppercasing stays Turkish-safe (i->İ,
            # ı->I): pre-apply it here and disable the engine's naive upper, so
            # Turkish clips never regress to a dotless/dotted-I mixup.
            engine_style = shared_preset(preset)
            burn_words = timings
            if engine_style is not None and engine_style.uppercase:
                burn_words = [
                    WordTiming(turkish_upper(t.text), t.start, t.end)
                    for t in timings
                ]
            return write_ass_engine(
                ass_path,
                burn_words,
                preset,
                upper=False,
                fonts=BURN_FONT_SUBSTITUTIONS,
            )

        phrases = group_words_into_phrases(timings)
        style = get_caption_style(preset)
        return write_ass(ass_path, phrases, style=style, upper=(preset == "hormozi"))
    except Exception as exc:  # noqa: BLE001 - captions are best-effort, never fatal
        logger.warning(
            f"clipping: caption build failed ({exc}); extracting un-captioned"
        )
        return ""


def default_composer(clip_paths: Sequence[str], out_path: str) -> str:
    """Real composer: cross-fade stitch via ``services/compose/transitions``."""
    from app.services.compose.transitions import stitch_with_transitions

    return stitch_with_transitions(list(clip_paths), out_path)


def request_from_params(params: dict) -> ClipRequest:
    """Build a :class:`ClipRequest` from a persisted ``Job.params`` dict."""
    params = params if isinstance(params, dict) else {}
    targets = params.get("publish_targets") or ()
    return ClipRequest(
        language=str(params.get("language") or "auto"),
        target_count=int(params.get("target_count") or 3),
        min_len_s=int(params.get("min_len_s") or 15),
        max_len_s=int(params.get("max_len_s") or 60),
        score_floor=int(params.get("score_floor") or 50),
        captions=params.get("captions"),
        transitions=bool(params.get("transitions", True)),
        publish_targets=tuple(str(t) for t in targets),
    )


def _resolve_source(params: dict, workdir: str) -> tuple[str, str]:
    """Resolve a job's source to a local file path + a stable source reference.

    Supports an owned R2 object key or one bounded, SSRF-safe HTTPS download.
    Both paths materialize a local file before the media pipeline runs.
    """
    key = str(params.get("source_video_key") or "").strip()
    url = str(params.get("source_url") or "").strip()
    if key:
        from app.platform.storage.r2 import get_r2_client

        dest = os.path.join(workdir, "source" + (os.path.splitext(key)[1] or ".mp4"))
        get_r2_client().download_file(key, dest)
        return dest, key
    if url:
        # A recognized social-platform link (YouTube/TikTok/Vimeo/Twitch/X) is a
        # page, not a media file, so the raw-file downloader would reject it 415.
        # Resolve + download it through yt_dlp (which owns the fetch to the CDN)
        # under the same byte/duration bounds. Everything else is a raw file URL
        # and keeps the SSRF-pinned downloader + its 415 not-a-video guard.
        from app.domains.clipping.platform_source import recognize_platform

        if recognize_platform(url) is not None:
            from app.domains.clipping.platform_source import (
                PlatformSourceError,
                download_platform_video,
                platform_source_ref,
            )

            try:
                path = download_platform_video(
                    url, os.path.join(workdir, "platform_source")
                )
                return path, platform_source_ref(url)
            except PlatformSourceError as exc:
                raise ClippingError(exc.status_code, exc.message) from exc

        from app.domains.clipping.external_source import (
            ExternalSourceError,
            download_external_video,
            external_source_suffix,
            safe_external_source_ref,
        )

        dest = os.path.join(workdir, f"external_source{external_source_suffix(url)}")
        try:
            download_external_video(url, dest)
            return dest, safe_external_source_ref(url)
        except ExternalSourceError as exc:
            raise ClippingError(exc.status_code, exc.message) from exc
    raise ClippingError(400, "clipping job has no source")


def _upload_result(user_id: str, job_id: str, local_path: str) -> str:
    """Upload a produced artifact to R2 and return its object key."""
    if not local_path or not os.path.exists(local_path):
        return ""
    from app.platform.storage.r2 import get_r2_client

    key = f"clipping/{user_id}/{job_id}/{os.path.basename(local_path)}"
    get_r2_client().upload_file(local_path, key, content_type="video/mp4")
    return key


def _durabilize_result(
    user_id: str,
    job_id: str,
    result: ClippingResult,
) -> ClippingResult:
    """Upload every rendered artifact before the scoped tempdir is removed."""
    durable_drafts: list[ClipDraft] = []
    for draft in result.drafts:
        result_key = ""
        if draft.result_path:
            result_key = _upload_result(user_id, job_id, draft.result_path)
        durable_drafts.append(replace(draft, result_path="", result_key=result_key))
    stitched_key = ""
    if result.stitched_path:
        stitched_key = _upload_result(user_id, job_id, result.stitched_path)
    return ClippingResult(
        drafts=tuple(durable_drafts),
        clip_paths=(),
        stitched_path="",
        stitched_key=stitched_key,
        note=result.note,
    )


def build_default_service() -> ClippingService:
    """Construct a :class:`ClippingService` wired to the production collaborators."""
    return ClippingService(
        transcriber=default_transcriber,
        ranker=_default_ranker,
        cutter=default_cutter,
        composer=default_composer,
    )
