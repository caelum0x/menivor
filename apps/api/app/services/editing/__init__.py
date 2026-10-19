"""ReelForge pure-FFmpeg editing services.

Opt-in pre-processing passes that run on the raw SCREEN RECORDING / AVATAR clip
before the compose smart-handling:

* :mod:`silence_cut` — the Submagic-style "auto-tighten" dead-air
  (silence + static) remover.
* :mod:`auto_zoom` — scene-driven "punch-in" zooms baked into the background
  clip via ``zoompan`` (duration-preserving).
* :mod:`motion` — synthetic "fake camera motion" (ken_burns / push_in /
  pull_out / whip_pan) baked into the background clip via ``scale``+``crop``.
* :mod:`matting` — the (optional, rembg-backed) background-removal matter that
  produces a cleaner avatar cut-out than raw chromakey.

Note: the ``motion`` and ``tighten`` submodules deliberately re-export a FUNCTION
whose name shadows the submodule, so ``from app.services.editing import motion``
returns the callable — which is what the compose pre-steps want; those submodules'
tests reach internals via ``importlib.import_module``. The ``auto_zoom`` submodule
is the exception: its unit tests import the SUBMODULE as ``auto_zoom``, so we do
NOT shadow it with the same-named function here — the compose pre-step imports the
callable via the full path (``from app.services.editing.auto_zoom import
auto_zoom``) instead. Its ``plan_zoom_moments`` / ``apply_zooms`` /
``detect_scene_changes`` helpers are re-exported normally.
"""

from app.services.editing.auto_zoom import (
    apply_zooms,
    detect_scene_changes,
    plan_zoom_moments,
)
from app.services.editing.matting import (
    is_available,
    matte,
    remove_background,
)
from app.services.editing.motion import (
    MOTION_PRESETS,
    apply_motion,
    motion,
)
from app.services.editing.silence_cut import (
    apply_cuts,
    build_keep_segments,
    detect_dead_air,
    tighten,
)

__all__ = [
    "MOTION_PRESETS",
    "apply_cuts",
    "apply_motion",
    "apply_zooms",
    "auto_zoom",  # the submodule (its function is imported via the full path)
    "build_keep_segments",
    "detect_dead_air",
    "detect_scene_changes",
    "is_available",
    "matte",
    "motion",
    "plan_zoom_moments",
    "remove_background",
    "tighten",
]
