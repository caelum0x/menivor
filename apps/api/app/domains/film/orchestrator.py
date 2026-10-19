"""AI-film orchestrator — beats + character → shot DAG + locked prompts.

Ties the P9 pieces together into one multi-shot pipeline plan (no I/O):

1. **Storyboard** decomposes the beat sheet into an ordered shot list
   (``storyboard.shotlist``),
2. **Character lock** produces a consistency-injected, deterministically-seeded
   prompt per shot (``characters.consistency``) so identity holds across shots,
3. a **DAG** (``app.events.dag``) wires per-shot first-frame → motion generation
   into a ``stitch`` → ``finish`` graph — exactly what the export worker
   (:func:`app.domains.film.export.run_film_export`) executes: stitch every
   shot (video + each shot's own audio, normalised) and finish (upload + record
   the final MP4). No separate voice-over / music stage is planned, so the plan
   never advertises a step the pipeline does not run.

Returns a :class:`FilmPlan` the worker layer runs; deterministic + unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domains.characters.consistency import (
    CharacterProfile,
    ShotPrompt,
    build_shot_prompt,
)
from app.domains.storyboard.shotlist import SceneBeat, Shot, build_shot_list
from app.events.dag import Dag


@dataclass(frozen=True)
class ShotPlan:
    """A shot bound to its consistency-locked generation prompt."""

    shot: Shot
    prompt: ShotPrompt


@dataclass(frozen=True)
class FilmPlan:
    """The full multi-shot render plan + its execution DAG."""

    shots: tuple[ShotPlan, ...]
    dag: Dag
    total_runtime_s: float
    node_order: tuple[str, ...] = field(default_factory=tuple)


def plan_film(
    beats: list[SceneBeat],
    character: CharacterProfile,
    *,
    total_shots: int = 22,
    target_runtime_s: float | None = None,
) -> FilmPlan:
    """Plan a character-consistent multi-shot film from a beat sheet.

    Each shot gets a deterministic, identity-locked prompt+seed so re-rendering a
    single weak shot never drifts the character. The DAG fans out per-shot
    generation (all independent) into a single ``stitch`` join, then ``finish``
    (upload + record), mirroring the export worker step for step.
    """
    shots = build_shot_list(beats, total_shots=total_shots, target_runtime_s=target_runtime_s)

    shot_plans: list[ShotPlan] = []
    dag = Dag()
    gen_nodes: list[str] = []
    for i, shot in enumerate(shots):
        prompt = build_shot_prompt(
            character, shot.action, shot_index=i, scene=shot.scene_id
        )
        shot_plans.append(ShotPlan(shot=shot, prompt=prompt))
        node = f"gen:{shot.shot_id}"
        dag.add(node)          # per-shot generation (independent — parallel fan-out)
        gen_nodes.append(node)

    # Join: stitch waits on every shot; finish uploads + records the final MP4.
    dag.add("stitch", gen_nodes)
    dag.add("finish", ["stitch"])
    dag.validate()

    total = round(sum(sp.shot.duration_s for sp in shot_plans), 2)
    return FilmPlan(
        shots=tuple(shot_plans),
        dag=dag,
        total_runtime_s=total,
        node_order=tuple(dag.topo_order()),
    )
