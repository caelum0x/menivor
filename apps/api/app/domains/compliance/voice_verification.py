"""Voice clone verification (M7.2).

Two checks run before any voice is sent to the clone provider:

1. **Label denylist.** The voice name and description may not name a
   well-known person or a fictional character
   (``voice_label_denylist.json``). This is a label check: it stops the obvious
   "Morgan Freeman narrator" clone, not a sample that merely sounds like one
   (check 2 covers the sample).
2. **Live spoken phrase.** The caller asks for a one-off phrase
   (:func:`issue_phrase`), records themselves reading it, and sends that
   recording with the sample. The clone goes ahead only when

   * the recording says the phrase (faster-whisper transcript; at least
     ``PHRASE_MIN_MATCH`` of the words), and
   * the same person speaks in the recording and in the sample (cosine
     similarity of WeSpeaker ResNet34 speaker embeddings at or above
     ``REELFORGE_VOICE_MATCH_THRESHOLD``, default ``DEFAULT_MATCH_THRESHOLD``).

   The phrase is fresh (a signed token, bound to the user, valid for
   ``PHRASE_TTL_S``), so a stored recording of somebody else cannot answer it.
   What this does not stop: a person who can synthesise the target's voice
   saying an arbitrary phrase in real time. That limit is stated, not hidden.

Models (both open source, run on our own CPU, no per-call cost):

* Speech to text: faster-whisper (MIT), already used for captions.
* Speaker embedding: WeSpeaker ``voxceleb_resnet34`` ONNX (Apache-2.0,
  https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34), run with
  onnxruntime (a faster-whisper dependency). Downloaded once from a pinned
  revision and checked against its SHA-256; ``REELFORGE_SPEAKER_MODEL_PATH``
  points at a local copy instead.

``REELFORGE_VOICE_CLONE_VERIFICATION``: ``required`` (default) or ``off``
(owner rollback switch; the label denylist still applies).
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import json
import os
import secrets
import struct
import subprocess
import tempfile
import time
import unicodedata
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Sequence

ENV_MODE = "REELFORGE_VOICE_CLONE_VERIFICATION"
ENV_SECRET = "REELFORGE_VOICE_VERIFY_SECRET"
ENV_THRESHOLD = "REELFORGE_VOICE_MATCH_THRESHOLD"
ENV_MODEL_PATH = "REELFORGE_SPEAKER_MODEL_PATH"

MODE_REQUIRED = "required"
MODE_OFF = "off"

PHRASE_WORDS = 6
PHRASE_MIN_MATCH = 5
PHRASE_TTL_S = 600
WORD_SIMILARITY = 0.8
DEFAULT_MATCH_THRESHOLD = 0.5
MIN_SPEECH_SECONDS = 1.5
MAX_EMBED_SECONDS = 60
SAMPLE_RATE = 16000

SPEAKER_MODEL_URL = (
    "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34/resolve/"
    "ff1ac5bca8ef11e90662b879aa923979e0bd277b/voxceleb_resnet34.onnx"
)
SPEAKER_MODEL_SHA256 = "9fea6516d7ad6bf0a76c7689f5a49b65d330fad6dde96c91bb4435ffbfe056a1"
SPEAKER_MODEL_FILE = "wespeaker_voxceleb_resnet34.onnx"
MODEL_DOWNLOAD_TIMEOUT_S = 120

#: Short, distinct English words that speech-to-text rarely confuses.
WORDLIST: tuple[str, ...] = (
    "anchor", "apple", "arrow", "basket", "blanket", "bottle", "bridge", "button",
    "camera", "candle", "carpet", "castle", "cherry", "circle", "cloud", "copper",
    "cotton", "desert", "dragon", "engine", "feather", "forest", "garden", "ginger",
    "glacier", "hammer", "harbor", "helmet", "island", "jacket", "jungle", "kettle",
    "ladder", "lantern", "lemon", "marble", "meadow", "mirror", "monkey", "needle",
    "orange", "otter", "paddle", "pencil", "pepper", "pillow", "planet", "pocket",
    "rabbit", "ribbon", "river", "rocket", "saddle", "silver", "spider", "thunder",
    "ticket", "tiger", "tomato", "tunnel", "velvet", "violin", "window", "yellow",
)

_DENYLIST_FILE = Path(__file__).with_name("voice_label_denylist.json")


class VoiceVerificationError(Exception):
    """A verification step refused the clone. ``code`` is machine-readable."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def mode() -> str:
    value = os.getenv(ENV_MODE, MODE_REQUIRED).strip().lower()
    return MODE_OFF if value == MODE_OFF else MODE_REQUIRED


def match_threshold() -> float:
    try:
        return float(os.getenv(ENV_THRESHOLD, "") or DEFAULT_MATCH_THRESHOLD)
    except ValueError:
        return DEFAULT_MATCH_THRESHOLD


# --------------------------------------------------------------------------- #
# 1. Label denylist
# --------------------------------------------------------------------------- #
def _fold(text: str) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "I"))
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    cleaned = "".join(ch if ch.isalnum() else " " for ch in plain)
    return " ".join(cleaned.split())


@lru_cache(maxsize=1)
def denylist() -> tuple[str, ...]:
    data = json.loads(_DENYLIST_FILE.read_text(encoding="utf-8"))
    names = [*data.get("people", []), *data.get("characters", []), *data.get("phrases", [])]
    return tuple(sorted({_fold(n) for n in names if _fold(n)}))


def denied_label(*labels: str) -> str | None:
    """The first denylisted name found in any label, or None."""
    for label in labels:
        folded = f" {_fold(label or '')} "
        squashed = folded.replace(" ", "")
        for name in denylist():
            if f" {name} " in folded or (len(name) >= 8 and name.replace(" ", "") in squashed):
                return name
    return None


def check_labels(name: str, description: str = "") -> None:
    hit = denied_label(name, description)
    if hit:
        raise VoiceVerificationError(
            "voice_label_denied",
            f"voice labels may not name a real public figure or a character ({hit!r}); "
            "clone only your own voice or one you are authorised to use",
        )


# --------------------------------------------------------------------------- #
# 2a. Phrase challenge (stateless, signed, bound to the user)
# --------------------------------------------------------------------------- #
def _secret() -> bytes:
    raw = os.getenv(ENV_SECRET, "").strip()
    if not raw:
        try:
            from app.services import crypto_tokens

            raw = crypto_tokens._resolve_secret()
        except Exception:  # noqa: BLE001 - no secret configured
            raw = ""
    if not raw:
        raise VoiceVerificationError(
            "voice_verification_unavailable",
            f"voice verification is not configured; set {ENV_SECRET}",
            status_code=503,
        )
    return hashlib.sha256(b"menivor-voice-verify-v1|" + raw.encode("utf-8")).digest()


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(secret: bytes, user_id: str, body: bytes) -> bytes:
    return hmac.new(secret, str(user_id).encode("utf-8") + b"|" + body, hashlib.sha256).digest()[:16]


def _words_for(indices: bytes) -> list[str]:
    return [WORDLIST[i % len(WORDLIST)] for i in indices]


@dataclass(frozen=True)
class Challenge:
    token: str
    phrase: str
    expires_at: int


def issue_phrase(user_id: str, *, now: float | None = None) -> Challenge:
    """A fresh phrase for ``user_id`` and the signed token that carries it."""
    issued = int(now if now is not None else time.time())
    indices = bytes(secrets.randbelow(len(WORDLIST)) for _ in range(PHRASE_WORDS))
    body = struct.pack(">Q", issued) + indices
    token = _b64u(body + _mac(_secret(), user_id, body))
    return Challenge(token=token, phrase=" ".join(_words_for(indices)), expires_at=issued + PHRASE_TTL_S)


def phrase_from_token(user_id: str, token: str, *, now: float | None = None) -> str:
    """The phrase a token carries, after checking signature, owner and age."""
    try:
        raw = _unb64u(str(token or ""))
    except (ValueError, TypeError) as exc:
        raise VoiceVerificationError("voice_verification_invalid", "the verification token is malformed") from exc
    if len(raw) != 8 + PHRASE_WORDS + 16:
        raise VoiceVerificationError("voice_verification_invalid", "the verification token is malformed")
    body, mac = raw[:-16], raw[-16:]
    if not hmac.compare_digest(mac, _mac(_secret(), user_id, body)):
        raise VoiceVerificationError("voice_verification_invalid", "the verification token is not valid for this account")
    issued = struct.unpack(">Q", body[:8])[0]
    current = now if now is not None else time.time()
    if current - issued > PHRASE_TTL_S or issued - current > 60:
        raise VoiceVerificationError("voice_verification_expired", "the verification phrase expired; ask for a new one")
    return " ".join(_words_for(body[8:]))


# --------------------------------------------------------------------------- #
# 2b. Phrase spoken?
# --------------------------------------------------------------------------- #
def phrase_matches(phrase: str, transcript: str) -> tuple[int, int]:
    """(words of ``phrase`` heard in ``transcript``, words in ``phrase``)."""
    heard = _fold(transcript).split()
    wanted = _fold(phrase).split()
    found = 0
    for word in wanted:
        if any(difflib.SequenceMatcher(None, word, h).ratio() >= WORD_SIMILARITY for h in heard):
            found += 1
    return found, len(wanted)


def _transcribe(path: str) -> str:
    from app.services import transcribe

    try:
        words = transcribe.transcribe_to_words(path, language="en")
    except transcribe.TranscriptionError as exc:
        raise VoiceVerificationError(
            "voice_verification_unavailable", "speech recognition is not available right now", status_code=503
        ) from exc
    return " ".join(w.text for w in words)


# --------------------------------------------------------------------------- #
# 2c. Same speaker?
# --------------------------------------------------------------------------- #
def load_pcm(path: str, max_seconds: float = MAX_EMBED_SECONDS) -> Any:
    """Mono 16 kHz float32 samples (int16 scale) decoded with ffmpeg."""
    import numpy as np

    from app.services.provenance import _binary

    cmd = [_binary("ffmpeg"), "-v", "error", "-i", path, "-t", str(max_seconds),
           "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VoiceVerificationError("voice_verification_audio", "the recording could not be decoded") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise VoiceVerificationError("voice_verification_audio", "the recording could not be decoded")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)


@lru_cache(maxsize=1)
def _mel_banks() -> Any:
    """Kaldi-style triangular mel filters: 80 bins, 512-point FFT, 20 Hz to Nyquist."""
    import numpy as np

    n_mels, n_fft, low, high = 80, 512, 20.0, SAMPLE_RATE / 2
    half = n_fft // 2

    def mel(freq: Any) -> Any:
        return 1127.0 * np.log(1.0 + freq / 700.0)

    mel_low, mel_high = mel(low), mel(high)
    delta = (mel_high - mel_low) / (n_mels + 1)
    bins = mel(SAMPLE_RATE / n_fft * np.arange(half))
    banks = np.zeros((n_mels, half + 1), dtype=np.float64)
    for i in range(n_mels):
        left, centre, right = (mel_low + (i + k) * delta for k in range(3))
        rising = (bins - left) / (centre - left)
        falling = (right - bins) / (right - centre)
        banks[i, :half] = np.maximum(0.0, np.minimum(rising, falling))
    return banks


def fbank(samples: Any) -> Any:
    """80-bin log-mel filterbank (Kaldi defaults WeSpeaker was trained on), mean-normalised."""
    import numpy as np

    frame, shift = 400, 160  # 25 ms / 10 ms at 16 kHz
    if len(samples) < frame:
        raise VoiceVerificationError("voice_verification_short", "the recording is too short")
    count = 1 + (len(samples) - frame) // shift
    idx = np.arange(frame)[None, :] + shift * np.arange(count)[:, None]
    frames = samples[idx].astype(np.float64)
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1] * 0.03, frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    window = np.power(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(frame) / (frame - 1)), 0.85)
    power = np.abs(np.fft.rfft(frames * window, n=512)) ** 2
    feats = np.log(np.maximum(power @ _mel_banks().T, np.finfo(np.float32).eps)).astype(np.float32)
    return feats - feats.mean(axis=0, keepdims=True)


def _model_path() -> str:
    configured = os.getenv(ENV_MODEL_PATH, "").strip()
    if configured:
        return configured
    from app.utils import utils

    directory = os.path.join(utils.storage_dir(), "models")
    path = os.path.join(directory, SPEAKER_MODEL_FILE)
    if not os.path.isfile(path):
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".speaker-", dir=directory)
        try:
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as out, urllib.request.urlopen(  # noqa: S310 - pinned https URL
                SPEAKER_MODEL_URL, timeout=MODEL_DOWNLOAD_TIMEOUT_S
            ) as resp:
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != SPEAKER_MODEL_SHA256:
                raise VoiceVerificationError(
                    "voice_verification_unavailable", "speaker model checksum mismatch", status_code=503
                )
            os.replace(tmp, path)
        except VoiceVerificationError:
            raise
        except Exception as exc:  # noqa: BLE001 - network or disk failure
            raise VoiceVerificationError(
                "voice_verification_unavailable", "speaker model could not be loaded", status_code=503
            ) from exc
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return path


@lru_cache(maxsize=1)
def _session() -> Any:
    try:
        import onnxruntime as ort

        return ort.InferenceSession(_model_path(), providers=["CPUExecutionProvider"])
    except VoiceVerificationError:
        raise
    except Exception as exc:  # noqa: BLE001 - missing runtime or bad model
        raise VoiceVerificationError(
            "voice_verification_unavailable", "speaker model could not be loaded", status_code=503
        ) from exc


def speaker_embedding(path: str) -> Any:
    """Unit-length 256-d speaker embedding of the audio at ``path``."""
    import numpy as np

    samples = load_pcm(path)
    if len(samples) < MIN_SPEECH_SECONDS * SAMPLE_RATE:
        raise VoiceVerificationError("voice_verification_short", "the recording is too short")
    feats = fbank(samples)
    emb = _session().run(None, {"feats": feats[None]})[0][0]
    norm = float(np.linalg.norm(emb))
    if norm == 0.0:
        raise VoiceVerificationError("voice_verification_audio", "no voice was found in the recording")
    return emb / norm


def similarity(a: Any, b: Any) -> float:
    return float(sum(float(x) * float(y) for x, y in zip(a, b)))


# --------------------------------------------------------------------------- #
# The whole check
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Verification:
    phrase_words_heard: int
    phrase_words: int
    speaker_similarity: float
    threshold: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "phrase_words_heard": self.phrase_words_heard,
            "phrase_words": self.phrase_words,
            "speaker_similarity": round(self.speaker_similarity, 3),
            "threshold": self.threshold,
        }


def verify(
    user_id: str,
    token: str,
    sample_path: str,
    recording_path: str,
    *,
    transcriber: Callable[[str], str] = _transcribe,
    embedder: Callable[[str], Sequence[float]] = speaker_embedding,
) -> Verification:
    """Raise :class:`VoiceVerificationError` unless the recording answers the phrase in the sample's voice."""
    phrase = phrase_from_token(user_id, token)
    heard, total = phrase_matches(phrase, transcriber(recording_path))
    if heard < PHRASE_MIN_MATCH:
        raise VoiceVerificationError(
            "voice_verification_phrase_mismatch",
            f"the recording does not say the verification phrase ({heard} of {total} words heard); "
            "record it again, clearly",
        )
    score = similarity(embedder(sample_path), embedder(recording_path))
    threshold = match_threshold()
    if score < threshold:
        raise VoiceVerificationError(
            "voice_verification_speaker_mismatch",
            "the voice in the verification recording does not match the sample; "
            "the sample must be your own voice",
        )
    return Verification(heard, total, score, threshold)


__all__ = [
    "Challenge",
    "DEFAULT_MATCH_THRESHOLD",
    "ENV_MODE",
    "ENV_SECRET",
    "MODE_OFF",
    "MODE_REQUIRED",
    "Verification",
    "VoiceVerificationError",
    "check_labels",
    "denied_label",
    "issue_phrase",
    "mode",
    "phrase_from_token",
    "phrase_matches",
    "speaker_embedding",
    "verify",
]
