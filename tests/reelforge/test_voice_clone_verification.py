# ruff: noqa: F811 - pytest fixtures imported from test_voices_api are used as arguments
"""M7.2: voice clone verification.

* A voice name or description naming a public figure or a character is refused
  before any storage or provider call (denylist hit).
* In the default ``required`` mode, the clone needs a recording of a fresh,
  signed phrase: a recording that does not say the phrase, or is a different
  speaker from the sample, is refused (mismatch reject) and nothing reaches the
  provider.
* The phrase token is bound to the user, expires, and cannot be tampered with.
* The speaker model check runs on the real WeSpeaker ONNX model when
  ``MENIVOR_TEST_SPEAKER_MODEL`` points at a local copy and macOS ``say`` is
  available (skipped otherwise).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

import app.controllers.v1.voices as voices_mod
from app.domains.compliance import voice_verification as vv
from app.models.db.models import UserVoice
from tests.reelforge.test_voices_api import (  # noqa: F401 - pytest fixtures
    _HEADERS,
    _make_asset,
    _make_user,
    db_factory,
    voices_client,
)

SECRET = "test-voice-verify-secret-0123456789abcdef"
CLONE = "/api/v1/voices/clone"


@pytest.fixture(autouse=True)
def _required_mode(monkeypatch):
    monkeypatch.setenv(vv.ENV_MODE, "required")
    monkeypatch.setenv(vv.ENV_SECRET, SECRET)
    monkeypatch.delenv(vv.ENV_THRESHOLD, raising=False)


# --------------------------------------------------------------------------- #
# Label denylist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label",
    ["Morgan Freeman narrator", "morgan-freeman", "TAYLOR SWIFT vibes", "Erdoğan sesi",
     "Darth Vader deep", "SpongeBob", "celebrity voice pack", "Mr. Beast intro"],
)
def test_denylist_hits(label):
    assert vv.denied_label(label)
    with pytest.raises(vv.VoiceVerificationError) as err:
        vv.check_labels("My voice", label)
    assert err.value.code == "voice_label_denied"


@pytest.mark.parametrize("label", ["My Brand Voice", "Alexa from support", "the rock band intro", "Mario Rossi", ""])
def test_ordinary_labels_pass(label):
    assert vv.denied_label(label) is None


# --------------------------------------------------------------------------- #
# Phrase token
# --------------------------------------------------------------------------- #
def test_phrase_token_round_trip_and_binding():
    challenge = vv.issue_phrase("u1", now=1_000_000)
    words = challenge.phrase.split()
    assert len(words) == vv.PHRASE_WORDS and all(w in vv.WORDLIST for w in words)
    assert challenge.expires_at == 1_000_000 + vv.PHRASE_TTL_S
    assert vv.phrase_from_token("u1", challenge.token, now=1_000_100) == challenge.phrase

    with pytest.raises(vv.VoiceVerificationError) as other_user:
        vv.phrase_from_token("u2", challenge.token, now=1_000_100)
    assert other_user.value.code == "voice_verification_invalid"

    with pytest.raises(vv.VoiceVerificationError) as expired:
        vv.phrase_from_token("u1", challenge.token, now=1_000_000 + vv.PHRASE_TTL_S + 1)
    assert expired.value.code == "voice_verification_expired"

    tampered = challenge.token[:-3] + ("AAA" if not challenge.token.endswith("AAA") else "BBB")
    with pytest.raises(vv.VoiceVerificationError):
        vv.phrase_from_token("u1", tampered, now=1_000_100)
    with pytest.raises(vv.VoiceVerificationError):
        vv.phrase_from_token("u1", "not-a-token", now=1_000_100)


def test_no_secret_is_503(monkeypatch):
    monkeypatch.delenv(vv.ENV_SECRET, raising=False)
    monkeypatch.setattr("app.services.crypto_tokens._resolve_secret", lambda: "")
    with pytest.raises(vv.VoiceVerificationError) as err:
        vv.issue_phrase("u1")
    assert err.value.status_code == 503


def test_phrase_matching_tolerates_small_transcription_slips():
    phrase = "river copper lantern tiger violin meadow"
    assert vv.phrase_matches(phrase, "River, copper, lantern. Tiger violin meadow!") == (6, 6)
    assert vv.phrase_matches(phrase, "river coper lanterns tiger violins meadow") == (6, 6)
    assert vv.phrase_matches(phrase, "hello this is my voice sample")[0] == 0


# --------------------------------------------------------------------------- #
# verify(): mismatch rejects
# --------------------------------------------------------------------------- #
def _embedder(vectors: dict[str, list[float]]):
    return lambda path: vectors[os.path.basename(path)]


def test_verify_rejects_a_recording_without_the_phrase():
    challenge = vv.issue_phrase("u1")
    with pytest.raises(vv.VoiceVerificationError) as err:
        vv.verify("u1", challenge.token, "sample.wav", "rec.wav",
                  transcriber=lambda p: "some other words entirely",
                  embedder=_embedder({"sample.wav": [1.0, 0.0], "rec.wav": [1.0, 0.0]}))
    assert err.value.code == "voice_verification_phrase_mismatch"


def test_verify_rejects_a_different_speaker():
    challenge = vv.issue_phrase("u1")
    with pytest.raises(vv.VoiceVerificationError) as err:
        vv.verify("u1", challenge.token, "sample.wav", "rec.wav",
                  transcriber=lambda p: challenge.phrase,
                  embedder=_embedder({"sample.wav": [1.0, 0.0], "rec.wav": [0.2, 0.98]}))
    assert err.value.code == "voice_verification_speaker_mismatch"


def test_verify_accepts_the_same_speaker_saying_the_phrase(monkeypatch):
    challenge = vv.issue_phrase("u1")
    result = vv.verify("u1", challenge.token, "sample.wav", "rec.wav",
                       transcriber=lambda p: challenge.phrase,
                       embedder=_embedder({"sample.wav": [1.0, 0.0], "rec.wav": [0.9, 0.436]}))
    assert result.phrase_words_heard == vv.PHRASE_WORDS
    assert result.speaker_similarity == pytest.approx(0.9)
    monkeypatch.setenv(vv.ENV_THRESHOLD, "0.95")
    with pytest.raises(vv.VoiceVerificationError):
        vv.verify("u1", challenge.token, "sample.wav", "rec.wav",
                  transcriber=lambda p: challenge.phrase,
                  embedder=_embedder({"sample.wav": [1.0, 0.0], "rec.wav": [0.9, 0.436]}))


# --------------------------------------------------------------------------- #
# Real model (optional)
# --------------------------------------------------------------------------- #
_MODEL = os.getenv("MENIVOR_TEST_SPEAKER_MODEL", "")


@pytest.mark.skipif(
    not (_MODEL and os.path.isfile(_MODEL) and shutil.which("say") and shutil.which("ffmpeg")),
    reason="needs MENIVOR_TEST_SPEAKER_MODEL, macOS say and ffmpeg",
)
def test_real_speaker_model_separates_voices(tmp_path, monkeypatch):
    monkeypatch.setenv(vv.ENV_MODEL_PATH, _MODEL)
    vv._session.cache_clear()
    lines = ("Thanks for trying our product. We make short videos for small teams every week.",
             "Please read this phrase out loud: river copper lantern tiger violin meadow.")
    paths = {}
    for voice in ("Daniel", "Albert"):
        for i, text in enumerate(lines):
            path = str(tmp_path / f"{voice}{i}.aiff")
            subprocess.run(["say", "-v", voice, "-o", path, text], check=True)
            paths[(voice, i)] = path
    emb = {key: vv.speaker_embedding(path) for key, path in paths.items()}
    same = vv.similarity(emb[("Daniel", 0)], emb[("Daniel", 1)])
    different = vv.similarity(emb[("Daniel", 0)], emb[("Albert", 1)])
    assert same >= vv.DEFAULT_MATCH_THRESHOLD > different
    vv._session.cache_clear()


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def _body(**extra):
    return {"name": "My Brand Voice", "sample_key": "uploads/sample.mp3", "consent": True, **extra}


def _patch_verify(monkeypatch, *, transcript, sample_vec, rec_vec):
    real = vv.verify

    def _verify(user_id, token, sample_path, recording_path):
        vectors = {sample_path: sample_vec, recording_path: rec_vec}
        return real(user_id, token, sample_path, recording_path,
                    transcriber=lambda p: transcript(token, user_id),
                    embedder=lambda p: vectors[p])

    monkeypatch.setattr(voices_mod.voice_verification, "verify", _verify)


def _phrase_for(token, user_id):
    return vv.phrase_from_token(str(user_id), token)


def _setup(voices_client):
    client, Factory, fake_vc = voices_client
    uid = _make_user(Factory)
    _make_asset(Factory, uid, "uploads/sample.mp3")
    _make_asset(Factory, uid, "uploads/verify.webm")
    return client, Factory, fake_vc


def _token(client):
    resp = client.post("/api/v1/voices/verification-phrase", headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["phrase"].split()) == vv.PHRASE_WORDS and data["required"] is True
    return data["token"]


def test_phrase_endpoint_requires_auth(voices_client):
    client, _, _ = voices_client
    assert client.post("/api/v1/voices/verification-phrase").status_code == 401


def test_clone_without_a_recording_is_refused(voices_client):
    client, Factory, fake_vc = _setup(voices_client)
    resp = client.post(CLONE, json=_body(), headers=_HEADERS)
    assert resp.status_code == 400
    assert resp.json()["data"]["code"] == "voice_verification_required"
    assert fake_vc.clone_calls == []


def test_denylisted_label_is_refused_even_with_verification_off(voices_client, monkeypatch):
    client, Factory, fake_vc = _setup(voices_client)
    monkeypatch.setenv(vv.ENV_MODE, "off")
    resp = client.post(CLONE, json=_body(name="Morgan Freeman narrator"), headers=_HEADERS)
    assert resp.status_code == 400
    assert resp.json()["data"]["code"] == "voice_label_denied"
    resp = client.post(CLONE, json=_body(description="sounds like Taylor Swift"), headers=_HEADERS)
    assert resp.json()["data"]["code"] == "voice_label_denied"
    assert fake_vc.clone_calls == []


def test_foreign_recording_is_403(voices_client):
    client, Factory, fake_vc = _setup(voices_client)
    token = _token(client)
    resp = client.post(CLONE, json=_body(verification_token=token, verification_key="uploads/not-mine.webm"),
                       headers=_HEADERS)
    assert resp.status_code == 403
    assert fake_vc.clone_calls == []


def test_phrase_mismatch_is_refused_and_nothing_is_cloned(voices_client, monkeypatch):
    client, Factory, fake_vc = _setup(voices_client)
    _patch_verify(monkeypatch, transcript=lambda t, u: "hello there", sample_vec=[1.0, 0.0], rec_vec=[1.0, 0.0])
    token = _token(client)
    resp = client.post(CLONE, json=_body(verification_token=token, verification_key="uploads/verify.webm"),
                       headers=_HEADERS)
    assert resp.status_code == 400
    assert resp.json()["data"]["code"] == "voice_verification_phrase_mismatch"
    assert fake_vc.clone_calls == []
    with Factory() as s:
        assert s.query(UserVoice).count() == 0


def test_speaker_mismatch_is_refused_and_nothing_is_cloned(voices_client, monkeypatch):
    client, Factory, fake_vc = _setup(voices_client)
    _patch_verify(monkeypatch, transcript=_phrase_for, sample_vec=[1.0, 0.0], rec_vec=[0.1, 0.995])
    token = _token(client)
    resp = client.post(CLONE, json=_body(verification_token=token, verification_key="uploads/verify.webm"),
                       headers=_HEADERS)
    assert resp.status_code == 400
    assert resp.json()["data"]["code"] == "voice_verification_speaker_mismatch"
    assert fake_vc.clone_calls == []


def test_verified_clone_goes_through_with_proof(voices_client, monkeypatch):
    client, Factory, fake_vc = _setup(voices_client)
    _patch_verify(monkeypatch, transcript=_phrase_for, sample_vec=[1.0, 0.0], rec_vec=[0.8, 0.6])
    token = _token(client)
    resp = client.post(CLONE, json=_body(verification_token=token, verification_key="uploads/verify.webm"),
                       headers=_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["voice_id"] == "elevenlabs:vc_abc123"
    assert data["verification"] == {
        "phrase_words_heard": vv.PHRASE_WORDS, "phrase_words": vv.PHRASE_WORDS,
        "speaker_similarity": 0.8, "threshold": vv.DEFAULT_MATCH_THRESHOLD,
    }
    # Only the sample goes to the provider, never the verification recording.
    assert len(fake_vc.clone_calls) == 1 and len(fake_vc.clone_calls[0][1]) == 1
