"""Compiled render-spec — the concrete plan the composer consumes.

The compiler (``compiler.py``) binds a genre template + user inputs into a
:class:`RenderSpec`: an ordered list of timed :class:`SegmentSpec`s (each with a
resolved absolute start/end, a bound media/text source, and its caption + audio
plan), plus reel-level camera-motion / VFX / loop / aspect settings that map
directly onto the existing ``services/compose`` pipeline.

Pure, serializable dataclasses — no ffmpeg here. ``to_dict`` yields the JSON the
``POST /templates/{slug}/compile`` endpoint returns and the render worker reads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class MediaBinding:
    """A resolved source for a track within a segment.

    ``kind`` is ``"clip"`` (a user/library video, e.g. gameplay), ``"text"`` (a
    narrated/dialogue text block driving TTS + captions), ``"image"`` (a still),
    or ``"none"``. ``ref`` is the R2 key / library id / raw text depending on kind.
    """

    track: str
    kind: str
    ref: str = ""
    loop: bool = False


@dataclass(frozen=True)
class CaptionCue:
    """A caption directive for a segment (text + style + safe-zone placement)."""

    text: str
    style: str = "karaoke_yellow"
    highlight: str = "#FFD93D"
    all_caps: bool = True
    y_frac: float = 0.63
    height_frac: float = 0.14


@dataclass(frozen=True)
class AudioCue:
    """One realized audio layer under a segment (with duck/gain intent)."""

    layer: str
    gain_db: float = 0.0
    ducked: bool = False


@dataclass(frozen=True)
class IdentityLock:
    """Character identity conditioning attached to a compiled segment (Wave 4).

    When a reel is compiled with a bound :class:`CharacterProfile`, each segment
    carries this lock so the render worker can reproduce the SAME character: the
    deterministic per-shot ``seed`` plus the identity-conditioning inputs the
    real IPAdapter / LoRA nodes consume (``reference_images`` + ``lora_ref``).

    ``ip_adapter_weight`` / ``lora_weight`` are the model-native conditioning
    strengths; ``negative_prompt`` carries the character's drift-guards. All
    fields are frozen + defaulted so :func:`dataclasses.asdict` recurses cleanly
    and an existing (character-less) compiled spec stays byte-identical.
    """

    character_id: str
    identity_key: str
    seed: int
    reference_images: tuple[str, ...] = ()
    ip_adapter_weight: float = 0.8
    lora_ref: str = ""
    lora_weight: float = 0.9
    negative_prompt: str = ""


@dataclass(frozen=True)
class SegmentSpec:
    """A compiled segment: a slot with resolved absolute timing + bound sources."""

    role: str
    order: int
    t_start: float
    t_end: float
    track: str
    media: tuple[MediaBinding, ...] = ()
    caption: CaptionCue | None = None
    audio: tuple[AudioCue, ...] = ()
    transition_in: str = "cut"
    transition_out: str = "cut"
    hook_gate: bool = False
    label: str = ""
    # Wave-4 identity lock (additive, backward-safe): present only when the reel
    # was compiled against a bound character; ``None`` preserves today's specs.
    identity_lock: IdentityLock | None = None

    @property
    def duration(self) -> float:
        return round(self.t_end - self.t_start, 3)


@dataclass(frozen=True)
class LoopPlan:
    """Seamless-loop intent (ASMR / loop-back genres)."""

    enabled: bool = False
    match_last_to_first: bool = True
    max_discontinuity: float = 0.02


@dataclass(frozen=True)
class RenderSpec:
    """The full compose plan for one reel produced from a template."""

    template_slug: str
    template_version: str
    genre: str
    aspect: str
    layout: str
    duration_s: float
    segments: tuple[SegmentSpec, ...]
    camera_motion: str = "none"
    effects: tuple[str, ...] = ()
    vfx_intensity: int = 50
    # Wave-1 motion engine (additive, backward-safe): which render path the
    # camera move takes ("filter" | "model" | "hybrid") and the motion preset id.
    # Defaults preserve today's pure-FFmpeg behavior.
    motion_class: str = "filter"
    motion_preset: str = ""
    caption_style: str = "karaoke_yellow"
    music_prompt: str = ""
    audio_foreground: str = "narration"
    duck: bool = True
    trend_relink: bool = False
    loop: LoopPlan = field(default_factory=LoopPlan)
    # Resolved background-library id for the looping companion track (when the
    # caller supplied no clip and the compiler auto-filled one). Empty otherwise.
    background_id: str = ""
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """JSON-safe dict (dataclasses → nested dicts/lists)."""
        return asdict(self)
