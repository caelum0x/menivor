"""P9 consistency moat — character lock + storyboard shot-list decomposition."""

from __future__ import annotations

import asyncio

from app.domains.characters.consistency import (
    CharacterProfile,
    build_shot_prompt,
    shot_seed,
)
from app.domains.growth.typesafe_client import TypeSafeError
from app.domains.storyboard.shotlist import (
    CAMERA_PRESETS,
    SceneBeat,
    build_shot_list,
    plan_shot_list,
)


# --------------------------------------------------------------------------- #
# Character lock
# --------------------------------------------------------------------------- #
def _profile():
    return CharacterProfile(
        character_id="c1",
        name="Nova",
        descriptors=("silver hair", "red jacket", "cyberpunk"),
        reference_images=("r2://sheet1.png",),
        style="3D pixar",
        negative=("blurry", "extra limbs"),
    )


def test_identity_seed_is_deterministic_across_instances():
    a, b = _profile(), _profile()
    assert a.identity_key() == b.identity_key()
    assert a.base_seed() == b.base_seed()


def test_shot_seed_stable_per_shot_but_varies():
    p = _profile()
    assert shot_seed(p, 0) == shot_seed(p, 0)   # reproducible
    assert shot_seed(p, 0) != shot_seed(p, 1)   # variety per shot


def test_prompt_injects_identity_first():
    p = _profile()
    sp = build_shot_prompt(p, "walks through neon rain", shot_index=2, scene="a dark alley")
    assert sp.prompt.startswith("Nova, silver hair, red jacket, cyberpunk")
    assert "3D pixar" in sp.prompt and "neon rain" in sp.prompt
    assert "blurry" in sp.negative_prompt
    assert sp.reference_images == ("r2://sheet1.png",)
    assert sp.seed == shot_seed(p, 2)


def test_descriptor_order_does_not_change_identity():
    p1 = CharacterProfile("c", "N", descriptors=("a", "b"))
    p2 = CharacterProfile("c", "N", descriptors=("b", "a"))
    assert p1.identity_key() == p2.identity_key()


# --------------------------------------------------------------------------- #
# Storyboard shot list
# --------------------------------------------------------------------------- #
def _beats():
    return [
        SceneBeat("sc1", "hero enters the city", weight=2.0, dialogue="I'm here."),
        SceneBeat("sc2", "the confrontation", weight=3.0),
        SceneBeat("sc3", "resolution", weight=1.0),
    ]


def test_shot_list_allocates_by_weight():
    shots = build_shot_list(_beats(), total_shots=12)
    by_scene = {}
    for s in shots:
        by_scene[s.scene_id] = by_scene.get(s.scene_id, 0) + 1
    # Heaviest scene gets the most shots; every scene gets at least one.
    assert by_scene["sc2"] >= by_scene["sc1"] >= by_scene["sc3"]
    assert all(v >= 1 for v in by_scene.values())
    assert len(shots) == 12


def test_shots_have_ordered_roles_and_cameras():
    shots = build_shot_list(_beats(), total_shots=12)
    assert [s.order for s in shots] == list(range(len(shots)))
    assert shots[0].role == "establishing" and shots[0].camera_motion == "dolly_in"
    # First shot of a scene carries its dialogue.
    assert shots[0].dialogue == "I'm here."


def test_runtime_normalization():
    shots = build_shot_list(_beats(), total_shots=10, target_runtime_s=30.0)
    assert abs(sum(s.duration_s for s in shots) - 30.0) < 0.1


def test_empty_beats_yields_no_shots():
    assert build_shot_list([]) == []


def test_camera_overrides_replace_establishing_camera():
    # A valid preset replaces the establishing shot's camera for that scene only.
    shots = build_shot_list(
        _beats(), total_shots=12, camera_overrides={"sc1": "crane_up"}
    )
    sc1_establishing = [s for s in shots if s.scene_id == "sc1" and s.role == "establishing"]
    assert sc1_establishing and all(s.camera_motion == "crane_up" for s in sc1_establishing)
    # Scenes without an override keep the deterministic default.
    sc2_establishing = [s for s in shots if s.scene_id == "sc2" and s.role == "establishing"]
    assert all(s.camera_motion == "dolly_in" for s in sc2_establishing)


def test_camera_overrides_ignore_unknown_preset():
    # An unknown preset id is ignored → identical to the no-override result.
    base = build_shot_list(_beats(), total_shots=12)
    overridden = build_shot_list(
        _beats(), total_shots=12, camera_overrides={"sc1": "not_a_real_move"}
    )
    assert [s.camera_motion for s in overridden] == [s.camera_motion for s in base]


# --------------------------------------------------------------------------- #
# Jev-planned shot list (plan_shot_list)
# --------------------------------------------------------------------------- #
class _StubCameraClient:
    """Fake ``TypeSafeClient`` returning a canned camera preset per scene summary."""

    def __init__(self, by_scene: dict[str, str]) -> None:
        self.by_scene = by_scene
        self.calls = 0

    async def system_one(self, state, questions, *, model=None):
        self.calls += 1
        chosen = self.by_scene.get(state["scene"], "")
        return {"answers": {"camera_preset": {"choice": chosen, "confidence": 0.9}}}


class _RaisingClient:
    """Fake client whose batched call always fails (TypeSafeError)."""

    async def system_one(self, state, questions, *, model=None):
        raise TypeSafeError("boom")


def test_plan_shot_list_degrades_without_key(monkeypatch):
    # No key (client is None) → identical deterministic output to build_shot_list.
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)
    planned = asyncio.run(plan_shot_list(_beats(), total_shots=12))
    baseline = build_shot_list(_beats(), total_shots=12)
    assert [s.camera_motion for s in planned] == [s.camera_motion for s in baseline]


def test_plan_shot_list_applies_jev_camera_choices():
    stub = _StubCameraClient(
        {
            "hero enters the city": "crane_up",
            "the confrontation": "orbit_left",
            "resolution": "static_wide",
        }
    )
    planned = asyncio.run(plan_shot_list(_beats(), total_shots=12, client=stub))
    assert stub.calls == 3  # one batched call per beat
    establishing = {
        s.scene_id: s.camera_motion
        for s in planned
        if s.role == "establishing"
    }
    assert establishing["sc1"] == "crane_up"
    assert establishing["sc2"] == "orbit_left"
    assert establishing["sc3"] == "static_wide"
    assert all(v in CAMERA_PRESETS for v in establishing.values())


def test_plan_shot_list_ignores_unknown_jev_choice():
    # An off-catalog pick is dropped → that scene keeps the deterministic default.
    stub = _StubCameraClient({"hero enters the city": "not_a_preset"})
    planned = asyncio.run(plan_shot_list(_beats(), total_shots=12, client=stub))
    sc1_establishing = [s for s in planned if s.scene_id == "sc1" and s.role == "establishing"]
    assert all(s.camera_motion == "dolly_in" for s in sc1_establishing)


def test_plan_shot_list_degrades_on_typesafe_error():
    planned = asyncio.run(
        plan_shot_list(_beats(), total_shots=12, client=_RaisingClient())
    )
    baseline = build_shot_list(_beats(), total_shots=12)
    assert [s.camera_motion for s in planned] == [s.camera_motion for s in baseline]


def test_plan_shot_list_empty_beats():
    assert asyncio.run(plan_shot_list([])) == []
