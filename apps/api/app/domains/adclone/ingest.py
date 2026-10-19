"""Downloaded source video -> Observations (local, $0). The source file is analysis-only input.

Callers delete the workdir afterwards (``service.analyze_link``); nothing derived from the
source (frames, audio, voice) is ever handed to a plan or a render engine.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

from . import media, vision
from .analyze import CaptionObs, Observations, ShotObs, SpeechObs

OCR_STEP_S = 0.5
MAX_OCR_SAMPLES = 120
_DOMAIN = re.compile(r"\b(?:www\.)?([\w-]+)\.(?:com|co|net|org|shop|store|io)\b", re.I)


def _shot_obs(path: str, shot: media.Shot, workdir: str) -> ShotObs:
    pad = min(0.12, shot.duration_s / 4)
    a = media.extract_frame(path, shot.start_s + pad, os.path.join(workdir, f"shot{shot.index}-a.jpg"))
    m = media.extract_frame(path, shot.mid_s, os.path.join(workdir, f"shot{shot.index}-m.jpg"))
    b = media.extract_frame(path, shot.end_s - pad, os.path.join(workdir, f"shot{shot.index}-b.jpg"))
    scale, dx = vision.similarity(a, b)
    return ShotObs(shot.start_s, shot.end_s, vision.largest_face_ratio(m), scale, dx)


def _captions(path: str, duration_s: float, workdir: str) -> tuple[list[CaptionObs], bool]:
    times = media.sample_times(duration_s, OCR_STEP_S)[:MAX_OCR_SAMPLES]
    out: list[CaptionObs] = []
    for i, t in enumerate(times):
        frame = media.extract_frame(path, t, os.path.join(workdir, f"ocr{i:03d}.jpg"), width=720)
        lines = vision.ocr_image(frame)
        if lines is None:
            return [], False
        good = [ln for ln in lines if ln.confidence >= 0.4 and len(ln.text) >= 2]
        if not good:
            out.append(CaptionObs(at_s=t, text="", y_center=0.8))  # a sample with no text ends a caption
        out.extend(CaptionObs(at_s=t, text=ln.text, y_center=ln.y_center, x_center=ln.x_center) for ln in good)
    return out, True


def avoid_terms_from(captions: list[CaptionObs], extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Brand names / domains the source shows (e.g. on its product card): never allowed in our plan."""
    terms = set(t.strip() for t in extra if t and t.strip())
    for c in captions:
        for m in _DOMAIN.finditer(c.text):
            terms.add(m.group(1))
    return tuple(sorted(terms))


def observe(path: str, workdir: str, *, url: str, platform: str, source_ref: str,
            extra_avoid: tuple[str, ...] = (),
            transcriber: Callable[..., tuple[list, str] | None] | None = None,
            language: str | None = None) -> Observations:
    """``language``: the ad's spoken language if known (ISO code); None / "original" = auto-detect."""
    os.makedirs(workdir, exist_ok=True)
    pr = media.probe(path)
    notes: list[str] = []
    shots = media.detect_shots(path, pr.duration_s)
    shot_obs = tuple(_shot_obs(path, s, workdir) for s in shots)
    captions, ocr_ok = _captions(path, pr.duration_s, workdir)
    if not ocr_ok:
        notes.append("no OCR engine installed: on-screen captions not read")
    speech: list[SpeechObs] = []
    wanted = (language or "").strip().lower()
    language = "" if wanted in ("", "original", "auto") else wanted
    if pr.has_audio:
        result = (transcriber or vision.transcribe)(path, language=language or None)
        if result is None:
            notes.append("no local speech model: transcript empty")
        else:
            segs, language = result
            speech = [SpeechObs(s.start_s, s.end_s, s.text) for s in segs]
        onsets = tuple(media.onsets_from_envelope(media.audio_envelope(path)))
    else:
        onsets = ()
    return Observations(url=url, platform=platform, source_ref=source_ref, duration_s=pr.duration_s,
                        width=pr.width, height=pr.height, shots=shot_obs, captions=tuple(captions),
                        speech=tuple(speech), onsets_s=onsets, language=language or "en",
                        avoid_terms=avoid_terms_from(captions, extra_avoid), notes=tuple(notes), ocr_available=ocr_ok)
