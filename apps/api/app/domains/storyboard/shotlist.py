"""Storyboard shot-list decomposition — screenplay → shot list.

The AI-film pipeline decomposes a beat sheet into a concrete shot list (~4 scenes
/ ~22 shots) with per-shot camera, framing, duration, and dialogue, then feeds
each shot to first-frame → motion generation. This module is the pure
decomposition: given scene beats + a target runtime, it allocates shots across
scenes proportionally and assigns a shot template (establishing → coverage →
close → payoff) with sensible camera/duration defaults.

Pure + deterministic — no LLM here (the beats come from the screenwriter agent);
this owns the structural allocation so it is unit-testable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Mapping

from loguru import logger

from app.domains.growth.typesafe_client import (
    TypeSafeClient,
    TypeSafeError,
    choice,
    typesafe_from_env,
)

# Per-position shot roles + default camera moves (Higgsfield-catalog ids).
_SHOT_CYCLE = [
    ("establishing", "dolly_in", 3.5),
    ("coverage", "pan_right", 2.5),
    ("reaction", "crash_zoom_in", 1.8),
    ("detail", "focus_change", 2.0),
    ("payoff", "crane_up", 3.0),
]

# Code-supplied camera-move catalog: preset id -> the emphasis it gives a shot.
# ``plan_shot_list`` lets Jev PICK one of these per beat to open the scene; the
# model never invents a move, it only chooses from this fixed set. A chosen (or
# caller-supplied) preset replaces the establishing shot's default camera.
CAMERA_PRESETS: dict[str, str] = {
    "dolly_in": "Slow push toward the subject — builds intimacy and pulls the viewer in.",
    "crane_up": "Rising crane reveal — opens the world and establishes scale.",
    "orbit_left": "Arc around the subject — adds depth and a strong sense of place.",
    "crash_zoom_in": "Sudden aggressive zoom — punches emphasis onto a single beat.",
    "static_wide": "Locked wide frame — lets the composition and staging speak for themselves.",
    "handheld_follow": "Handheld follow — urgent, kinetic, documentary energy.",
}

# Question id for the single batched per-beat camera choice.
_Q_CAMERA = "camera_preset"


@dataclass(frozen=True)
class SceneBeat:
    """One narrative beat/scene from the screenwriter."""

    scene_id: str
    summary: str
    weight: float = 1.0        # relative screen-time weight
    dialogue: str = ""


@dataclass(frozen=True)
class Shot:
    """One planned shot in the storyboard."""

    shot_id: str
    scene_id: str
    order: int
    role: str
    camera_motion: str
    duration_s: float
    action: str
    dialogue: str = ""


def _alloc_shots(weights: list[float], total_shots: int) -> list[int]:
    """Largest-remainder allocation of ``total_shots`` across weighted scenes."""
    wsum = sum(weights) or 1.0
    raw = [w / wsum * total_shots for w in weights]
    base = [int(x) for x in raw]
    # Every scene gets at least 1 shot.
    base = [max(1, b) for b in base]
    # Distribute any remainder by largest fractional part.
    remainder = total_shots - sum(base)
    fracs = sorted(range(len(weights)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
    i = 0
    while remainder > 0 and fracs:
        base[fracs[i % len(fracs)]] += 1
        remainder -= 1
        i += 1
    while remainder < 0:  # too many (min-1 inflated it) — trim largest
        j = max(range(len(base)), key=lambda k: base[k])
        if base[j] > 1:
            base[j] -= 1
        remainder += 1
    return base


def build_shot_list(
    beats: list[SceneBeat],
    *,
    total_shots: int = 22,
    target_runtime_s: float | None = None,
    camera_overrides: Mapping[str, str] | None = None,
) -> list[Shot]:
    """Decompose scene beats into an ordered shot list.

    Shots are allocated across scenes by weight (each scene ≥ 1 shot), assigned a
    cycling role+camera template, and — when ``target_runtime_s`` is given —
    duration-normalized so the shot durations sum to the target.

    ``camera_overrides`` maps a ``scene_id`` to a :data:`CAMERA_PRESETS` id; a
    *valid* preset replaces the camera move of that scene's establishing shot(s).
    Unknown preset ids (and scenes with no entry) are ignored, so the output stays
    deterministic and identical to the no-override result on bad input.
    """
    if not beats:
        return []
    counts = _alloc_shots([b.weight for b in beats], max(len(beats), total_shots))
    overrides = camera_overrides or {}

    shots: list[Shot] = []
    order = 0
    for beat, n in zip(beats, counts):
        for k in range(n):
            role, camera, dur = _SHOT_CYCLE[k % len(_SHOT_CYCLE)]
            # A valid preset override swaps the establishing shot's camera move.
            if role == "establishing":
                preset = overrides.get(beat.scene_id, "")
                if preset in CAMERA_PRESETS:
                    camera = preset
            shots.append(
                Shot(
                    shot_id=f"{beat.scene_id}-s{k+1}",
                    scene_id=beat.scene_id,
                    order=order,
                    role=role,
                    camera_motion=camera,
                    duration_s=dur,
                    action=beat.summary,
                    dialogue=beat.dialogue if k == 0 else "",
                )
            )
            order += 1

    if target_runtime_s and shots:
        scale = target_runtime_s / sum(s.duration_s for s in shots)
        shots = [
            Shot(**{**s.__dict__, "duration_s": round(s.duration_s * scale, 2)}) for s in shots
        ]
    return shots


# --------------------------------------------------------------------------- #
# Jev-planned camera moves — one batched choice() per beat, concurrent
# --------------------------------------------------------------------------- #
def _camera_question() -> dict:
    """The single per-beat choice question: PICK one camera preset (built in code)."""
    return choice(
        "Which camera move best opens this scene — matching its emotional beat and "
        "giving the establishing shot the right emphasis?",
        CAMERA_PRESETS,
    )


def _beat_state(beat: SceneBeat) -> dict:
    """State fed to Jev for one beat (treated purely as data)."""
    return {
        "scene": beat.summary,
        "dialogue": beat.dialogue or None,
        "note": (
            "Choose the establishing camera move for the opening shot of this "
            "scene in a short-form vertical video."
        ),
    }


async def _pick_camera(client: TypeSafeClient, beat: SceneBeat) -> str:
    """Ask Jev for one beat's camera preset; return a valid id or ``""``.

    A single batched ``system_one`` call (one ``choice`` question). Any answer
    that is not a known :data:`CAMERA_PRESETS` id degrades to ``""`` (no override).
    """
    resp = await client.system_one(_beat_state(beat), {_Q_CAMERA: _camera_question()})
    answers = resp.get("answers", {}) if isinstance(resp, dict) else {}
    ans = answers.get(_Q_CAMERA) or {}
    chosen = str(ans.get("choice") or "")
    return chosen if chosen in CAMERA_PRESETS else ""


async def plan_shot_list(
    beats: list[SceneBeat],
    *,
    total_shots: int = 22,
    target_runtime_s: float | None = None,
    client: TypeSafeClient | None = None,
) -> list[Shot]:
    """Plan a shot list, letting Jev pick each scene's establishing camera move.

    One batched ``choice()`` call per beat (run concurrently via
    :func:`asyncio.gather`) picks a camera preset; the winning presets become the
    ``camera_overrides`` map fed into :func:`build_shot_list`.

    ``client`` is injectable for tests; by default it is built from the
    environment. When no ``TYPESAFE_API_KEY`` is configured (``client is None``)
    or on any :class:`TypeSafeError`, this degrades to the IDENTICAL deterministic
    output of :func:`build_shot_list` (no overrides) — camera planning never
    depends on a key being present and never fabricates a move.
    """
    if not beats:
        return []

    resolved = client or typesafe_from_env()
    if resolved is None:
        return build_shot_list(
            beats, total_shots=total_shots, target_runtime_s=target_runtime_s
        )

    try:
        picks = await asyncio.gather(*(_pick_camera(resolved, b) for b in beats))
    except TypeSafeError as exc:
        logger.warning(
            f"plan_shot_list: Jev camera planning failed ({exc}); "
            "falling back to deterministic shot list"
        )
        return build_shot_list(
            beats, total_shots=total_shots, target_runtime_s=target_runtime_s
        )

    overrides = {beat.scene_id: pick for beat, pick in zip(beats, picks) if pick}
    return build_shot_list(
        beats,
        total_shots=total_shots,
        target_runtime_s=target_runtime_s,
        camera_overrides=overrides,
    )
