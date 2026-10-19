"""ElevenLabs direct API: Voice Design (description -> previews -> saved voice id) and per-line TTS.

Voices are DESIGNED from a text description only. No reference audio is ever sent and a
description asking to clone or imitate someone is refused (:func:`ipguard.check_voice_description`).
Endpoints (docs checked 2026-10-06, elevenlabs.io/docs/api-reference):
* ``POST /v1/text-to-voice/design`` {voice_description, model_id, text|auto_generate_text} -> previews[]
* ``POST /v1/text-to-voice`` {voice_name, voice_description, generated_voice_id} -> {voice_id}
* ``POST /v1/text-to-speech/{voice_id}`` {text, model_id, voice_settings} -> audio/mpeg
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from . import ipguard, presets

BASE_URL = "https://api.elevenlabs.io"
DESIGN_MODEL = "eleven_multilingual_ttv_v2"
TTS_MODEL = "eleven_multilingual_v2"
PREVIEW_TEXT = ("Simit went up again this morning, and the bakkal just shrugged at me. You know what, I am not even "
                "angry any more. I made tea. Some days are just very Turkish, and that is fine by me.")
_VOICE_ID = re.compile(r"^[A-Za-z0-9]{8,40}$")

Http = Callable[[str, str, Mapping[str, str], Any], tuple[int, bytes]]


class ElevenLabsError(RuntimeError):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status_code = status


def default_http(method: str, url: str, headers: Mapping[str, str], body: Any) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed https base URL
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""


@dataclass
class ElevenLabs:
    api_key: str
    http: Http = default_http
    base_url: str = BASE_URL

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> "ElevenLabs":
        env = os.environ if env is None else env
        key = (env.get("ELEVENLABS_API_KEY") or "").strip()
        if not key:
            raise ElevenLabsError("set ELEVENLABS_API_KEY (Starter plan or above for commercial use)", 503)
        return cls(api_key=key, **kw)

    def _post(self, path: str, body: dict, *, accept: str = "application/json") -> bytes:
        status, raw = self.http("POST", self.base_url + path,
                                {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": accept}, body)
        if status == 401:
            raise ElevenLabsError("ElevenLabs refused the key", 503)
        if status == 402 or status == 429:
            raise ElevenLabsError("ElevenLabs quota or credits exhausted", 402)
        if status >= 400:
            raise ElevenLabsError(f"ElevenLabs error {status}: {raw[:200]!r}")
        return raw

    def design(self, description: str, *, text: str = PREVIEW_TEXT) -> list[dict]:
        """Preview voices for a description: [{generated_voice_id, audio_base_64, duration_secs}]."""
        ipguard.check_voice_description(description)
        data = json.loads(self._post("/v1/text-to-voice/design",
                                     {"voice_description": description[:1000], "model_id": DESIGN_MODEL, "text": text}))
        previews = data.get("previews") or []
        if not previews:
            raise ElevenLabsError("ElevenLabs returned no voice previews")
        return [{"generated_voice_id": p["generated_voice_id"], "audio_base_64": p.get("audio_base_64", ""),
                 "duration_secs": p.get("duration_secs")} for p in previews if p.get("generated_voice_id")]

    def save(self, *, name: str, description: str, generated_voice_id: str) -> str:
        ipguard.check_voice_description(description)
        data = json.loads(self._post("/v1/text-to-voice", {"voice_name": name[:60], "voice_description": description[:1000],
                                                          "generated_voice_id": generated_voice_id}))
        voice_id = str(data.get("voice_id") or "")
        if not _VOICE_ID.match(voice_id):
            raise ElevenLabsError("ElevenLabs returned no voice id")
        return voice_id

    def tts(self, *, voice_id: str, text: str, out_path: str, model_id: str = TTS_MODEL) -> str:
        if not _VOICE_ID.match(voice_id or ""):
            raise ElevenLabsError("this character has no locked voice id yet; run voice design first", 409)
        audio = self._post(f"/v1/text-to-speech/{voice_id}", {"text": text[:2000], "model_id": model_id,
                                                               "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}},
                           accept="audio/mpeg")
        if not audio:
            raise ElevenLabsError("ElevenLabs returned empty audio")
        with open(out_path, "wb") as fh:
            fh.write(audio)
        return out_path


def lock_character_voice(client: ElevenLabs, preset: dict, character: str, generated_voice_id: str) -> dict:
    """Save a chosen preview as a voice and return a NEW preset with it locked for the character."""
    c = (preset.get("characters") or {}).get(character)
    if c is None:
        raise presets.PresetError(f"unknown character {character!r}")
    voice_id = client.save(name=f"{preset['brand_name']} {c['name']}", description=c["voice"]["voice_design"],
                           generated_voice_id=generated_voice_id)
    return presets.with_voice(preset, character, voice_id)


def line_audio(client: ElevenLabs, preset: dict, plan: Mapping[str, Any], outdir: str) -> dict[str, str]:
    """One mp3 per plan line, each with the speaker's locked voice id."""
    os.makedirs(outdir, exist_ok=True)
    out = {}
    for ln in plan.get("lines") or []:
        c = preset["characters"].get(ln["speaker"]) or {}
        vid = (c.get("voice") or {}).get("elevenlabs_voice_id", "")
        out[ln["id"]] = client.tts(voice_id=vid, text=ln.get("tts") or ln["text"],
                                   out_path=os.path.join(outdir, f"{ln['id']}.mp3"))
    return out
