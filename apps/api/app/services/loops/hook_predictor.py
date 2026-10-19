"""Hook-strength predictor — the first-3s retention gate.

Research (docs/reelforge/vision2026): the first ~3 seconds decide ~70% of
retention, and clearing ~70% completion on the test audience is the viral-reach
gate. This module scores a reel's cold-open BEFORE publish from cheap, explainable
signals and flags anything below the gate so the creator can strengthen it.

Pure + deterministic: it scores a :class:`HookSignals` feature bundle (extracted
upstream by a lightweight probe — motion energy, on-screen text presence, audio
onset, cut in the window, spoken-word density). No ffmpeg/ML here, so the scoring
policy is unit-testable and identical across API, worker, and desktop.

:func:`extract_hook_signals` is the extraction probe that populates
:class:`HookSignals` from real media inputs (FFmpeg + Whisper word timings).
It lives here so that importers get both the data class and the probe from a
single import without a circular dependency.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from app.services.loops import policy

_log = logging.getLogger(__name__)

# Weighted contribution of each first-3s signal to the hook score (sums to 1.0).
_WEIGHTS = {
    "motion": 0.22,       # visual motion energy in the window (pattern interrupt)
    "text": 0.20,         # a bold on-screen text hook present early
    "audio_onset": 0.18,  # an immediate audio hit (no dead air / slow fade-in)
    "early_cut": 0.15,    # a hard cut / scene change inside the window
    "speech": 0.15,       # spoken-word density (a verbal hook, not silence)
    "face_or_subject": 0.10,  # a clear subject/face on screen
}


@dataclass(frozen=True)
class HookSignals:
    """Normalized first-3s features (each 0..1) extracted from the reel."""

    motion: float = 0.0
    text: float = 0.0
    audio_onset: float = 0.0
    early_cut: float = 0.0
    speech: float = 0.0
    face_or_subject: float = 0.0
    hook_end_s: float = 3.0  # where the hook slot actually ends


@dataclass(frozen=True)
class HookScore:
    """The predicted hook strength + verdict against the viral gate."""

    score: float             # 0..1 predicted first-3s retention
    passes_gate: bool        # score >= HOOK_MIN_CLEARANCE
    subscores: dict          # per-signal weighted contribution
    reasons: tuple[str, ...] = ()  # why it may fail (weakest signals + timing)

    @property
    def grade(self) -> str:
        if self.score >= 0.85:
            return "viral"       # ≥85% first-3s → 2.8x reach
        if self.score >= policy.HOOK_MIN_CLEARANCE:
            return "strong"      # clears the gate
        if self.score >= 0.55:
            return "weak"
        return "poor"


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def predict_hook(signals: HookSignals) -> HookScore:
    """Score the cold-open and flag it against the 70% retention gate."""
    subscores = {
        name: round(weight * _clamp(getattr(signals, name)), 4)
        for name, weight in _WEIGHTS.items()
    }
    score = round(sum(subscores.values()), 4)

    # A hook that overruns the 3s window is penalized (late payoff loses viewers).
    if signals.hook_end_s > policy.HOOK_WINDOW_S:
        overrun = min(1.0, (signals.hook_end_s - policy.HOOK_WINDOW_S) / policy.HOOK_WINDOW_S)
        score = round(max(0.0, score * (1.0 - 0.25 * overrun)), 4)

    reasons = _weakness_reasons(signals, subscores)
    return HookScore(
        score=score,
        passes_gate=score >= policy.HOOK_MIN_CLEARANCE,
        subscores=subscores,
        reasons=tuple(reasons),
    )


def _weakness_reasons(signals: HookSignals, subscores: dict) -> list[str]:
    reasons: list[str] = []
    if signals.hook_end_s > policy.HOOK_WINDOW_S:
        reasons.append(
            f"hook ends at {signals.hook_end_s:.1f}s — tighten it under {policy.HOOK_WINDOW_S:.0f}s"
        )
    # Surface the two weakest signals (largest headroom vs. their max weight).
    headroom = sorted(
        ((_WEIGHTS[name] - subscores[name], name) for name in _WEIGHTS),
        reverse=True,
    )
    for gap, name in headroom[:2]:
        if gap > 0.06:
            reasons.append(_SUGGESTIONS[name])
    return reasons


_SUGGESTIONS = {
    "motion": "add motion in the first second (snap-zoom / whip-pan) — a static open loses viewers",
    "text": "add a bold on-screen text hook in the first frame (lands with sound off)",
    "audio_onset": "start on an immediate audio hit — cut the slow fade-in / dead air",
    "early_cut": "add a hard cut within the first 2s to create a pattern interrupt",
    "speech": "open on the spiciest spoken line first, not setup",
    "face_or_subject": "put a clear subject/face on screen in the opening frame",
}


# ---------------------------------------------------------------------------
# Media probe — populates HookSignals from real inputs
# ---------------------------------------------------------------------------

def extract_hook_signals(
    video_path: str | None,
    audio_path: str | None,
    words: list[dict] | None,
    *,
    hook_window_s: float = policy.HOOK_WINDOW_S,
) -> HookSignals:
    """Extract hook-strength signals for the first ``hook_window_s`` seconds.

    motion          — FFmpeg temporal-diff frame sampling (32×32 px, 8 fps).
    audio_onset     — first-second RMS energy via FFmpeg astats; falls back
                      to Whisper word onset timing when audio_path is absent.
    speech          — fraction of the hook window covered by Whisper word spans.
    early_cut       — longest within-window word gap (proxy for a hard cut or
                      scene transition).
    text            — always 0.0 (OCR not available in this probe; caller may
                      override after running a separate text-detection pass).
    face_or_subject — per-frame brightness variance via FFmpeg as a coarse
                      subject-presence proxy (a clear subject creates contrast).

    All inputs are optional; any missing input degrades its dependent signal
    to 0.0 rather than raising.
    """
    motion = _probe_motion(video_path, hook_window_s) if video_path else 0.0
    face_proxy = _probe_face_proxy(video_path, hook_window_s) if video_path else 0.0

    speech, early_cut, word_onset = _signals_from_words(words or [], hook_window_s)

    if audio_path:
        ffmpeg_onset = _probe_audio_onset(audio_path)
        audio_onset = ffmpeg_onset if ffmpeg_onset > 0.0 else word_onset
    else:
        audio_onset = word_onset

    return HookSignals(
        motion=round(motion, 4),
        text=0.0,
        audio_onset=round(audio_onset, 4),
        early_cut=round(early_cut, 4),
        speech=round(speech, 4),
        face_or_subject=round(face_proxy, 4),
        hook_end_s=hook_window_s,
    )


# --- private probes ---------------------------------------------------------

def _probe_motion(video_path: str, window_s: float) -> float:
    """Mean temporal-diff across 8-fps 32×32 frames — normalised to [0, 1].

    Degrades to 0.0 if ffmpeg is unavailable or the video cannot be decoded.
    A mean pixel-diff of ~0.12 (normalised) corresponds to energetic motion.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error",
                "-t", str(window_s),
                "-i", video_path,
                "-vf", "fps=8,scale=32:32",
                "-f", "rawvideo", "-pix_fmt", "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=20,
        )
        data = result.stdout
        frame_size = 32 * 32
        if len(data) < frame_size * 2:
            return 0.0
        n_frames = len(data) // frame_size
        frames = [data[i * frame_size: (i + 1) * frame_size] for i in range(n_frames)]
        diffs: list[float] = []
        for a, b in zip(frames[:-1], frames[1:]):
            # bytes iteration yields ints in Python 3
            diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / (frame_size * 255.0))
        if not diffs:
            return 0.0
        mean_diff = sum(diffs) / len(diffs)
        return min(1.0, mean_diff / 0.12)   # 0.12 = "energetic motion" baseline
    except Exception as exc:
        _log.debug("motion probe failed for %s: %s", video_path, exc)
        return 0.0


def _probe_face_proxy(video_path: str, window_s: float) -> float:
    """Per-frame brightness variance as a coarse subject-presence proxy.

    A clear face or subject creates spatial brightness contrast; a plain
    background has low variance.  Typical face scene: variance ~500–2000;
    plain: ~50–200.  Normalised against 2000.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error",
                "-t", str(min(window_s, 1.0)),
                "-i", video_path,
                "-vf", "fps=2,scale=32:32",
                "-frames:v", "2",
                "-f", "rawvideo", "-pix_fmt", "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=10,
        )
        data = result.stdout
        frame_size = 32 * 32
        if len(data) < frame_size:
            return 0.0
        frame = data[:frame_size]
        mean = sum(frame) / frame_size
        variance = sum((b - mean) ** 2 for b in frame) / frame_size
        return min(1.0, variance / 2000.0)
    except Exception as exc:
        _log.debug("face proxy probe failed for %s: %s", video_path, exc)
        return 0.0


def _probe_audio_onset(audio_path: str) -> float:
    """RMS level in the first second via FFmpeg astats, mapped to [0, 1].

    A strong audio onset (immediate hit, no dead air) maps to high values.
    RMS range assumed: [-60 dBFS, -6 dBFS] → [0, 1].
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error",
                "-t", "1.0",
                "-i", audio_path,
                "-af", "astats=metadata=1:reset=1",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stderr.splitlines():
            if "RMS level dB" in line:
                try:
                    db = float(line.split(":")[-1].strip())
                    return max(0.0, min(1.0, (db + 60.0) / 54.0))
                except ValueError:
                    continue
        return 0.0
    except Exception as exc:
        _log.debug("audio onset probe failed for %s: %s", audio_path, exc)
        return 0.0


def _signals_from_words(
    words: list[dict], window_s: float
) -> tuple[float, float, float]:
    """Derive (speech, early_cut, audio_onset) from Whisper word timings.

    Each entry in ``words`` is expected to have ``start`` (float, seconds) and
    optionally ``end`` keys.  Returns three floats each in [0, 1]:

    speech      — fraction of the hook window covered by spoken word spans.
    early_cut   — longest gap between consecutive word starts inside the window,
                  normalised by 1.0 s; a long silence gap proxies a hard cut.
    audio_onset — 1.0 if the first word begins within 0.5 s, decaying linearly.
    """
    if not words:
        return 0.0, 0.0, 0.0

    early = [w for w in words if isinstance(w, dict) and w.get("start", 9999.0) < window_s]
    if not early:
        return 0.0, 0.0, 0.0

    # Speech density: total word-span time inside the window.
    covered = sum(
        min(float(w.get("end", w.get("start", 0.0))), window_s)
        - float(w.get("start", 0.0))
        for w in early
    )
    speech = min(1.0, max(0.0, covered / window_s))

    # Audio onset: how soon does speech start?
    first_start = min(float(w.get("start", 9999.0)) for w in early)
    audio_onset = 1.0 if first_start < 0.5 else max(0.0, 1.0 - first_start / window_s)

    # Early-cut proxy: normalised longest gap between word starts.
    starts = sorted(float(w.get("start", 0.0)) for w in early)
    if len(starts) >= 2:
        max_gap = max(b - a for a, b in zip(starts[:-1], starts[1:]))
        early_cut = min(1.0, max_gap / 1.0)
    else:
        early_cut = 0.0

    return speech, early_cut, audio_onset
