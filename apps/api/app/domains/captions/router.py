"""Captions HTTP facade — hook-score / Hormozi styling / safe-zones (P7).

Thin, DB-free router over the pure ``services/loops`` + ``services/captions``
cores, so the web/mobile review screens can score a hook, preview the Hormozi
1-2-word grouping, and resolve per-platform safe-zones without running a render.
MPT envelope + :class:`HttpException`; a bad body is a clean 422.
"""

from __future__ import annotations

from fastapi import Request
from pydantic import BaseModel, Field

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

router = new_router()


class HookScoreBody(BaseModel):
    """First-3s signals (each 0..1) extracted by the client-side probe."""

    motion: float = 0.0
    text: float = 0.0
    audio_onset: float = 0.0
    early_cut: float = 0.0
    speech: float = 0.0
    face_or_subject: float = 0.0
    hook_end_s: float = 3.0
    # Optional: the reel's opening line — when provided + the hook is below the
    # gate, the response includes concrete cold-open rewrite suggestions.
    opening_line: str = ""


class WordIn(BaseModel):
    text: str
    start: float
    end: float


class HormoziBody(BaseModel):
    words: list[WordIn] = Field(default_factory=list, max_length=2000)
    max_per_group: int = Field(default=2, ge=1, le=4)
    highlight_hex: str = "#FFD93D"


class LoopCheckBody(BaseModel):
    """Per-candidate-frame discontinuity scores (0 identical .. 1 hard seam)."""

    discontinuities: list[float] = Field(default_factory=list, max_length=100000)
    fps: float = Field(default=30.0, gt=0)
    target_s: float | None = None
    min_s: float = 1.0
    max_s: float | None = None
    max_discontinuity: float | None = None


class BeatFitBody(BaseModel):
    cuts: list[float] = Field(default_factory=list, max_length=5000)
    beats: list[float] = Field(default_factory=list, max_length=5000)
    fps: float = Field(default=30.0, gt=0)


class SeoBody(BaseModel):
    text: str = Field(..., max_length=20000)
    platform: str = Field(default="tiktok", max_length=20)
    base_caption: str = Field(default="", max_length=500)


@router.post("/captions/hook-score", summary="Predict first-3s hook strength (70% gate)")
def hook_score(request: Request, body: HookScoreBody):
    """Score the cold-open against the viral-reach retention gate."""
    _ = base.get_task_id(request)
    from app.services.loops import HookSignals, predict_hook, suggest_hooks

    signals = body.model_dump()
    opening_line = signals.pop("opening_line", "")
    res = predict_hook(HookSignals(**signals))
    # When the hook misses the gate and an opening line was supplied, return
    # concrete cold-open rewrites biased by the flagged weaknesses.
    suggestions = (
        [
            {"shape": s.shape, "text": s.text, "rationale": s.rationale}
            for s in suggest_hooks(opening_line, passes_gate=res.passes_gate, reasons=res.reasons)
        ]
        if (opening_line and not res.passes_gate)
        else []
    )
    return utils.get_response(
        200,
        {
            "score": res.score,
            "passes_gate": res.passes_gate,
            "grade": res.grade,
            "subscores": res.subscores,
            "reasons": list(res.reasons),
            "suggestions": suggestions,
        },
    )


@router.post("/captions/hormozi", summary="Group words into 1-2 word Hormozi caption cues")
def hormozi(request: Request, body: HormoziBody):
    """Chunk word-timed tokens into accented 1-2 word groups (preview)."""
    request_id = base.get_task_id(request)
    from app.services.captions.hormozi import WordCue, group_words, hormozi_style

    if not body.words:
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: words required")
    cues = [WordCue(w.text, w.start, w.end) for w in body.words]
    groups = group_words(cues, max_per_group=body.max_per_group)
    return utils.get_response(
        200,
        {
            "style": hormozi_style(body.highlight_hex).as_params(),
            "groups": [
                {
                    "text": g.text,
                    "words": list(g.words),
                    "start": g.start,
                    "end": g.end,
                    "highlight_index": g.highlight_index,
                }
                for g in groups
            ],
        },
    )


@router.get("/captions/safezones", summary="Per-platform caption safe-zones")
def safezones(request: Request, play_h: int = 1920):
    """Caption placement (fontsize + top margin) for each platform surface."""
    _ = base.get_task_id(request)
    from app.services.captions.safezone import safezone_for, supported_surfaces

    zones = {}
    for surface in supported_surfaces():
        z = safezone_for(surface, play_h)
        zones[surface] = {"fontsize": z.fontsize, "margin_v": z.margin_v, "y_frac": z.y_frac}
    return utils.get_response(200, {"play_h": play_h, "safezones": zones})


@router.post("/captions/loop-check", summary="Find the best seamless-loop point")
def loop_check(request: Request, body: LoopCheckBody):
    """Pick the frame that loops back to the start most seamlessly (ASMR/loop genres)."""
    request_id = base.get_task_id(request)
    from app.services.loops.loop_finder import find_loop_point

    if not body.discontinuities:
        raise HttpException(task_id=request_id, status_code=422,
                            message=f"{request_id}: discontinuities required")
    res = find_loop_point(
        body.discontinuities, fps=body.fps, target_s=body.target_s,
        min_s=body.min_s, max_s=body.max_s, max_discontinuity=body.max_discontinuity,
    )
    return utils.get_response(200, {
        "end_frame": res.end_frame, "end_s": res.end_s,
        "discontinuity": res.discontinuity, "accepted": res.accepted, "reason": res.reason,
    })


@router.post("/captions/beat-fit", summary="Preview beat-cut nudge fits")
def beat_fit(request: Request, body: BeatFitBody):
    """Rank nudge options (-2/-3/-4 frames) by how tightly cuts snap to beats."""
    _ = base.get_task_id(request)
    from app.services.loops.beat_cut import preview_beat_fits

    fits = preview_beat_fits(body.cuts, body.beats, fps=body.fps)
    return utils.get_response(200, {"fits": {str(k): v for k, v in fits.items()}})


@router.post("/captions/seo", summary="Keyword-SEO caption + hashtags for a platform")
def seo_caption(request: Request, body: SeoBody):
    """Front-load searchable keywords + specific hashtags (IG/Shorts index caption text)."""
    request_id = base.get_task_id(request)
    from app.services.captions.keyword_seo import build_seo_caption

    if not body.text.strip():
        raise HttpException(task_id=request_id, status_code=422, message=f"{request_id}: text required")
    res = build_seo_caption(body.text, platform=body.platform, base_caption=body.base_caption)
    return utils.get_response(200, {
        "caption": res.caption, "hashtags": list(res.hashtags), "keywords": list(res.keywords),
    })
