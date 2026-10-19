"""Music planning — structure a BGM track to the reel's shape.

Given the reel's total duration + where the hook ends, plan the background-music
sections (a short **build** under the hook to lift the cold-open, a loopable
**body**, and a brief **outro**) with timings, so a routed music provider (Suno /
AIVA / ElevenLabs Music) can generate a track that hits the reel's beats and the
composer can time-align it. Pure planning (no generation call here) — the section
math + prompt assembly are deterministic and unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_MIN_BUILD_S = 0.8
_MAX_BUILD_S = 3.0
_MIN_OUTRO_S = 0.5


@dataclass(frozen=True)
class MusicSection:
    """One timed section of the BGM."""

    name: str        # build | body | outro
    start: float
    end: float
    gain_db: float = 0.0

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


@dataclass(frozen=True)
class MusicPlan:
    """The full BGM plan: sections + a generation prompt for the router."""

    total_s: float
    sections: tuple[MusicSection, ...]
    prompt: str
    loopable: bool
    bpm_hint: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)


def plan_music(
    total_s: float,
    *,
    hook_end_s: float = 3.0,
    mood: str = "energetic",
    duck_db: float = -14.0,
    loopable: bool = False,
    bpm_hint: int = 0,
) -> MusicPlan:
    """Plan BGM sections timed to the reel.

    The **build** covers the hook window (clamped to a sensible range), the
    **body** fills the middle (ducked under narration), and a short **outro**
    closes it. When the reel is too short for all three, sections collapse
    gracefully (a tiny reel is a single body section).
    """
    if total_s <= 0:
        raise ValueError("total_s must be positive")

    warnings: list[str] = []
    build = max(_MIN_BUILD_S, min(_MAX_BUILD_S, hook_end_s))
    outro = _MIN_OUTRO_S
    # Not enough room for build + outro -> single body section.
    if build + outro >= total_s:
        sections = (MusicSection("body", 0.0, round(total_s, 3), gain_db=duck_db),)
        warnings.append("reel too short for build/outro; single body section")
        return MusicPlan(round(total_s, 3), sections, _prompt(mood, "single"), loopable, bpm_hint, tuple(warnings))

    body_start = round(build, 3)
    body_end = round(total_s - outro, 3)
    sections = (
        MusicSection("build", 0.0, body_start, gain_db=duck_db + 2),   # slightly louder to lift the hook
        MusicSection("body", body_start, body_end, gain_db=duck_db),
        MusicSection("outro", body_end, round(total_s, 3), gain_db=duck_db),
    )
    return MusicPlan(round(total_s, 3), sections, _prompt(mood, "structured"), loopable, bpm_hint, tuple(warnings))


def _prompt(mood: str, shape: str) -> str:
    base = f"{mood} background music, instrumental, no vocals"
    if shape == "structured":
        return f"{base}, short rising intro then a steady loopable groove, low-energy under narration"
    return f"{base}, steady loop, low-energy under narration"


def total_section_coverage(plan: MusicPlan) -> float:
    """Sum of the section durations (should equal the total; a plan invariant)."""
    return round(sum(s.duration for s in plan.sections), 3)
