"""Sound effects on Replicate: Stable Audio 2.5 (Stability AI's hosted model).

Licence check (2026-10-05):

* ``zsxkib/mmaudio`` (video-to-audio) is NOT used: its code is MIT but the
  checkpoints are CC-BY-NC-4.0 (https://github.com/hkchengrex/MMAudio, "The
  checkpoints are released on Hugging Face under the CC-BY-NC 4.0 license"), and
  ``mmaudio`` is ``non_commercial`` in routing.license_class, so paid work never
  goes to it.
* ``stability-ai/stable-audio-2.5`` is Stability AI's official hosted model
  (prompt, duration 1-190 s, steps 4-8, cfg_scale, seed); vendor key
  ``stability-ai`` is sellable under the Stability terms in license_class.
  It is text-to-audio: the beat's prompt describes the sound, not the picture.
"""

from __future__ import annotations

from typing import Any

from app.domains.gateway import replicate_run
from app.domains.routing.license_class import assert_model_sellable

MODEL = "stability-ai/stable-audio-2.5"
MIN_S, MAX_S = 1, 30
NEGATIVE = "music, melody, singing, speech, voices"


class SfxError(RuntimeError):
    pass


def is_enabled() -> bool:
    return replicate_run.is_enabled()


def build_input(prompt: str, *, seconds: float, seed: int | None = None) -> dict:
    text = " ".join(str(prompt or "").split())
    if not text:
        raise SfxError("describe the sound")
    inp: dict[str, Any] = {
        "prompt": f"{text[:400]}. Sound effect only, no {NEGATIVE}.",
        "duration": max(MIN_S, min(MAX_S, int(round(float(seconds or MIN_S))))),
        "steps": 8, "cfg_scale": 1,
    }
    if seed is not None:
        inp["seed"] = int(seed)
    return inp


def generate_sfx(prompt: str, *, seconds: float, out_path: str, video_url: str = "", image_url: str = "",
                 seed: int | None = None, session: Any = None) -> str:
    """One sound effect for a beat, saved to ``out_path``.

    ``video_url`` / ``image_url`` are accepted for parity with video-to-audio lanes;
    Stable Audio is text-to-audio, so they are not sent (no non-commercial model is used).
    """
    _ = (video_url, image_url)
    assert_model_sellable(MODEL)
    try:
        url = replicate_run.run(MODEL, build_input(prompt, seconds=seconds, seed=seed), session=session)
        replicate_run.download(url, out_path, session=session)
    except SfxError:
        raise
    except Exception as exc:  # noqa: BLE001 - one error type for the mixer
        raise SfxError(f"the sound effect did not render: {exc}") from exc
    return out_path


__all__ = ["MODEL", "SfxError", "build_input", "generate_sfx", "is_enabled"]
