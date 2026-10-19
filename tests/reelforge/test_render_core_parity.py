"""Executor ↔ library filtergraph parity (T10 — preview == output).

``packages/render-core`` is the shared spec→filtergraph library the client uses to
build its preview and to serialise the RenderSpec to the API. The executor
(``app/services/compose/compose_ffmpeg.py``) is the only process that spawns
FFmpeg. For a preview to match the burned output, the executor's composition graph
(everything up to the ``[comp]`` sink) and its ducked-audio graph (``[aout]``) must
be **byte-identical** to what the library emits for the same spec.

This test pins that invariant: it drives the executor's own pure builders with the
exact parameters ``reelforge.py`` uses in production (portrait 1080x1920, default
chroma / PiP diameter / margin, the per-path audio input indices) and asserts the
library reproduces each fragment character-for-character. If either side drifts —
a new ``setsar``, a retuned duck curve, a moved overlay — this fails loudly instead
of silently desyncing the preview from the render.

The environment-specific finishing the executor appends *after* ``[comp]`` (the
libass caption burn, which escapes an absolute path and embeds ``utils.font_dir()``,
and the brand watermark) is intentionally out of the shared byte contract and is
not asserted here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.models.schema import VideoAspect
from app.services.compose import compose_ffmpeg as cf

# Make the shared library importable without installing it (monorepo path dep).
_RENDER_CORE = Path(__file__).resolve().parents[2] / "packages" / "render-core" / "python"
if str(_RENDER_CORE) not in sys.path:
    sys.path.insert(0, str(_RENDER_CORE))

reelforge_render_core = pytest.importorskip(
    "reelforge_render_core",
    reason="render-core python port not found on disk",
)
from reelforge_render_core import (  # noqa: E402
    build_audio_graph,
    build_video_graph,
    make_spec,
)

# The executor's shipping defaults (compose_avatar_over_screen signature) — these
# are what reelforge.py relies on since it never overrides chroma/diameter/margin.
_CHROMA = {"color": "0x00FF00", "similarity": 0.18, "blend": 0.10}
_W, _H = VideoAspect.portrait.to_resolution()  # 1080 x 1920


def _exec_layout(name: str) -> str:
    return cf._LAYOUTS[name](_W, _H, cf._PIP_DIAMETER, cf._PIP_MARGIN, _CHROMA)


# --------------------------------------------------------------------------- #
# Video composition parity (executor layout builder == library video graph)
# --------------------------------------------------------------------------- #
def test_captions_only_base_matches_executor_fill_node():
    # compose_captions_over_screen builds its base with _fill_node("0:v","comp").
    executor = cf._fill_node("0:v", "comp", _W, _H)
    library = build_video_graph(make_spec(layout="captions_only"))
    assert library == executor


@pytest.mark.parametrize("layout", ["pip", "split", "hook_intro"])
def test_avatar_layouts_match_executor(layout):
    executor = _exec_layout(layout)
    library = build_video_graph(make_spec(layout=layout, avatar_input=1))
    assert library == executor


# --------------------------------------------------------------------------- #
# Audio graph parity (executor _build_audio_graph == library audio graph)
# --------------------------------------------------------------------------- #
def test_avatar_audio_graph_matches_executor():
    # compose_avatar_over_screen: narration=input 2, bgm=input 3 (defaults).
    executor_graph, _ = cf._build_audio_graph()
    library = build_audio_graph(
        make_spec(layout="pip", avatar_input=1, narration=2, bgm=3)
    )
    assert library == executor_graph


def test_captions_only_audio_graph_matches_executor():
    # compose_captions_over_screen: narration=input 1, bgm=input 2.
    executor_graph, _ = cf._build_audio_graph(voice_input=1, music_input=2)
    library = build_audio_graph(
        make_spec(layout="captions_only", narration=1, bgm=2)
    )
    assert library == executor_graph


# --------------------------------------------------------------------------- #
# Every executor layout has a matching library layout (registries can't drift)
# --------------------------------------------------------------------------- #
def test_library_covers_every_executor_avatar_layout():
    from reelforge_render_core import AVATAR_LAYOUTS

    assert set(cf._LAYOUTS) == set(AVATAR_LAYOUTS)


def test_goldens_are_the_executor_output():
    """The committed golden fixtures equal the executor's real composition."""
    import json

    golden_path = (
        _RENDER_CORE.parent / "test" / "fixtures" / "golden" / "filtergraphs.json"
    )
    golden = json.loads(golden_path.read_text())

    expected = {
        "captions-only-base": cf._fill_node("0:v", "comp", _W, _H),
        "captions-only-music": cf._fill_node("0:v", "comp", _W, _H)
        + ";"
        + cf._build_audio_graph(voice_input=1, music_input=2)[0],
        "pip": _exec_layout("pip"),
        "split": _exec_layout("split"),
        "hook-intro": _exec_layout("hook_intro"),
        "pip-music": _exec_layout("pip")
        + ";"
        + cf._build_audio_graph(voice_input=2, music_input=3)[0],
    }
    for name, want in expected.items():
        assert golden[name]["filtergraph"] == want, f"{name} golden != executor"
