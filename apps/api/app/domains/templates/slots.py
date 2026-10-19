"""Segment-slot authoring model for the genre shot-template engine.

A genre template (``definitions.ShotTemplateDef``) is a versioned graph of named
**segment slots** — the part-by-part structure every viral short-form format
shares: a cold-open Hook, a body (setup / rising / escalation), a Climax/Payoff,
and a Loop/CTA button. Each :class:`SlotSpec` carries its *default* timing and the
compose bindings (which visual track it drives, which audio layers play under it,
which caption preset styles it). The compiler (``compiler.py``) turns a template's
slots + user inputs into a concrete :class:`~app.domains.templates.render_spec.RenderSpec`.

Pure data only — no DB, no ffmpeg — so the whole authoring/compile path is unit
testable in isolation (mirrors ``app.domains.catalog.presets``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Canonical segment-slot roles (the recurring grammar across all genres). Kept as
# plain strings (not an Enum) so seeded preset data and JSON round-trips stay
# trivial, matching the preset-catalog style elsewhere in the codebase.
SLOT_ROLES: frozenset[str] = frozenset(
    {
        "hook",        # cold-open pattern-interrupt (must clear the first-3s retention gate)
        "setup",       # framing / context
        "rising",      # rising action / tension bumps
        "escalation",  # brainrot-style escalating nonsense to a signature sound
        "body",        # generic narrated/dialogue body
        "exchange",    # podcast speaker-turn body
        "climax",      # peak / twist
        "payoff",      # punchline / resolution
        "button",      # closing beat
        "loop",        # loop-back seam (last frame ≈ first frame)
        "cta",         # comment-bait / "Part 2?" call to action
        "seam",        # invisible-cut loop seam (ASMR)
    }
)

# Visual track a slot drives. ``primary`` is the hero surface (narrated panel /
# recap B-roll), ``secondary`` the companion surface (looping gameplay), ``full``
# the single full-frame surface, ``overlay`` a composited element.
TRACK_ROLES: frozenset[str] = frozenset({"primary", "secondary", "full", "overlay"})

# Audio layers a slot can request; the compiler assembles these into an audio bus
# with narration always mixed above gameplay SFX and ducked BGM.
AUDIO_LAYERS: frozenset[str] = frozenset(
    {"narration", "dialogue", "trigger", "gameplay_sfx", "bgm", "trend_audio", "sfx"}
)


@dataclass(frozen=True)
class SlotSpec:
    """One named segment slot in a genre template.

    Timing is expressed as a fraction of the reel's total duration
    (``t_start_frac``/``t_end_frac`` in ``0..1``) so a template scales to any
    requested length while preserving its pacing; ``min_s``/``max_s`` clamp the
    absolute duration of the slot after scaling. ``hook_gate`` marks the slot that
    must clear the first-3s retention threshold.
    """

    role: str
    order: int
    t_start_frac: float
    t_end_frac: float
    track: str = "full"
    audio: tuple[str, ...] = ()
    caption: bool = True
    transition_in: str = "cut"
    transition_out: str = "cut"
    min_s: float = 0.0
    max_s: float = 0.0  # 0 => unbounded
    hook_gate: bool = False
    label: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.role not in SLOT_ROLES:
            raise ValueError(f"unknown slot role {self.role!r}; expected one of {sorted(SLOT_ROLES)}")
        if self.track not in TRACK_ROLES:
            raise ValueError(f"unknown track {self.track!r}; expected one of {sorted(TRACK_ROLES)}")
        if not (0.0 <= self.t_start_frac < self.t_end_frac <= 1.0):
            raise ValueError(
                f"slot {self.role!r} has invalid timing fractions "
                f"[{self.t_start_frac}, {self.t_end_frac}) — expected 0<=start<end<=1"
            )
        for layer in self.audio:
            if layer not in AUDIO_LAYERS:
                raise ValueError(f"unknown audio layer {layer!r}; expected one of {sorted(AUDIO_LAYERS)}")

    @property
    def duration_frac(self) -> float:
        return round(self.t_end_frac - self.t_start_frac, 6)


@dataclass(frozen=True)
class AudioPlanDef:
    """Template-level audio intent the compiler realizes into a mixed bus.

    ``foreground`` is the layer that is never ducked (narration/dialogue/trigger);
    ``bgm_prompt`` seeds AI background music; ``duck`` enables sidechain ducking of
    BGM/gameplay under the foreground; ``trend_relink`` flags the "edit muted →
    re-add the native trending sound on upload" workflow.
    """

    foreground: str = "narration"
    bgm_prompt: str = ""
    duck: bool = True
    trend_relink: bool = False
    layers: tuple[str, ...] = field(default_factory=tuple)
