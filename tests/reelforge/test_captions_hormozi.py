"""P7 Hormozi caption engine + safe-zone; P9 film orchestrator integration."""

from __future__ import annotations

import pytest

from app.domains.characters.consistency import CharacterProfile
from app.domains.film.orchestrator import plan_film
from app.domains.storyboard.shotlist import SceneBeat
from app.services.captions import safezone
from app.services.captions.hormozi import (
    WordCue,
    group_words,
    hormozi_style,
    select_highlight,
)


# --------------------------------------------------------------------------- #
# Hormozi word grouping + highlight selection
# --------------------------------------------------------------------------- #
def _words(pairs):
    t = 0.0
    out = []
    for w in pairs:
        out.append(WordCue(w, t, t + 0.3))
        t += 0.3
    return out


def test_group_words_chunks_by_two_and_preserves_timing():
    words = _words(["this", "changed", "my", "entire", "life"])
    groups = group_words(words, max_per_group=2)
    assert [g.text for g in groups] == ["this changed", "my entire", "life"]
    # Timing is exact: first group starts at first word, ends at second word.
    assert groups[0].start == pytest.approx(0.0)
    assert groups[0].end == pytest.approx(0.6)
    assert groups[-1].start == pytest.approx(1.2)


def test_highlight_picks_content_word_not_stopword():
    # "the plan" -> 'plan' (index 1), 'the' is a stopword.
    assert select_highlight(("the", "plan")) == 1
    # "changed everything" -> 'changed' (verb ending -ed scores higher).
    assert select_highlight(("changed", "today")) == 0
    # all stopwords -> none.
    assert select_highlight(("of", "the")) == -1


def test_group_carries_highlight_index():
    groups = group_words(_words(["my", "breakthrough"]), max_per_group=2)
    assert groups[0].highlight_index == 1  # 'breakthrough'


def test_group_validates_size():
    with pytest.raises(ValueError):
        group_words(_words(["a"]), max_per_group=0)


def test_hormozi_style_defaults():
    s = hormozi_style()
    assert s.all_caps and s.highlight_hex == "#FFD93D"
    assert s.as_params()["font"].startswith("Montserrat")
    assert hormozi_style("#00FF00").highlight_hex == "#00FF00"


# --------------------------------------------------------------------------- #
# Safe-zone
# --------------------------------------------------------------------------- #
def test_safezone_differs_per_surface():
    tiktok = safezone.safezone_for("tiktok", 1920)
    shorts = safezone.safezone_for("shorts", 1920)
    # Shorts uses a smaller caption than TikTok (clears the title bar).
    assert shorts.fontsize < tiktok.fontsize
    assert 0 < tiktok.margin_v < 1920


def test_safezone_unknown_surface_falls_back():
    z = safezone.safezone_for("myspace", 1920)
    assert z.fontsize > 0 and "tiktok" in safezone.supported_surfaces()


# --------------------------------------------------------------------------- #
# Film orchestrator (integrates storyboard + character lock + DAG)
# --------------------------------------------------------------------------- #
def test_plan_film_builds_locked_shot_dag():
    beats = [
        SceneBeat("sc1", "hero enters", weight=2.0),
        SceneBeat("sc2", "the twist", weight=1.0),
    ]
    char = CharacterProfile("c1", "Nova", descriptors=("red jacket",), style="3D")
    plan = plan_film(beats, char, total_shots=8, target_runtime_s=24.0)

    # A shot per plan, each with an identity-locked prompt + deterministic seed.
    assert len(plan.shots) == 8
    assert all("Nova" in sp.prompt.prompt for sp in plan.shots)
    seeds = [sp.prompt.seed for sp in plan.shots]
    assert len(set(seeds)) > 1  # shots vary but are deterministic

    # DAG: every gen node feeds stitch; finish (upload + record) is last and
    # mirrors the export worker, which has no separate voice step.
    assert "stitch" in plan.dag.nodes and "finish" in plan.dag.nodes
    assert plan.node_order[-1] == "finish"
    gen_positions = [
        plan.node_order.index(n) for n in plan.node_order if n.startswith("gen:")
    ]
    assert len(gen_positions) == 8
    assert max(gen_positions) < plan.node_order.index("stitch")
    assert plan.node_order.index("stitch") < plan.node_order.index("finish")
    assert abs(plan.total_runtime_s - 24.0) < 0.2


def test_plan_film_is_deterministic():
    beats = [SceneBeat("sc1", "a", weight=1.0)]
    char = CharacterProfile("c", "N", descriptors=("x",))
    p1 = plan_film(beats, char, total_shots=3)
    p2 = plan_film(beats, char, total_shots=3)
    assert [s.prompt.seed for s in p1.shots] == [s.prompt.seed for s in p2.shots]
