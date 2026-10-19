""""Very ___ Time" one-click template (preset ``very-time@v1``) on top of story8.

One place word, one everyday ritual and (optionally) one line become a 15 s,
five-shot vertical video: detail 2.0 s, character 3.0 s, insert 2.5 s, wide
3.0 s, deadpan 4.5 s. It runs as a story8 job (kind ``story8``,
``params.preset = "very-time"``), so ``GET /film/story8/{job_id}``, the workers,
the price-first debit and the refunds are the story8 ones.

Per-beat text (what each beat shows and says):

* beats 1 to 4 (detail, character, insert, wide) carry no speech and no caption:
  their ``line`` is empty. The words on screen there are the garment's chest
  embroidery ("very <place> time"), which every image prompt asks for.
* beat 5 (deadpan) carries the line ("You met me at a very <place> time in my
  life." by default). It is narrated once, placed at the start of beat 5
  (+0.2 s) and shown as one whole sentence in the look's caption style
  (``game_yellow`` for console, ``serif_lower_third`` for flash and atelier)
  from the start of beat 5 to the end of the video.
* no separate on-screen place title: the chest text already carries the phrase
  in every shot, and a second title would repeat it and cover the garment.

Guard-rail: :func:`guard` runs in plan and start before any credit or provider
call. It scans every user text against the preset's banned imagery, mocking
framing and do-not-copy lists plus the existing prompt denylist (story8's
``moderate``); the place word is also checked against the existing insult list
(``social_inbox.engagement_classify``) and ``VERY_TIME_BLOCKED_WORDS`` (comma
separated, for slurs the operator adds); every field is also checked against the
curated slur and hate-symbol list (``hate_terms``, LDNOOBW slur subset plus
curated symbols). Matching is Turkish-aware (dotted and
dotless i fold together, accents are stripped), whole-word, and allows simple
English and Turkish suffixes (flags, sultanlar, bayraklı).

Animated shots carry the multi-reference contract the media lane consumes
(``video_model``, ``references`` with ``first_frame`` / ``identity`` roles and a
structured ``brief``) next to the old ``prompt`` / ``image_key`` keys.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.controllers import base
from app.controllers.v1.base import new_router
from app.controllers.v1.jobs import _require_db, _resolve_user, get_session
from app.models.exception import HttpException
from app.utils import utils

from . import hate_terms, story8

router = new_router()

PRESET_NAME = "very-time"
PRESET_REF = "very-time@v1"
LOOKS = ("console", "flash", "atelier")
MAX_PLACE = 24
MAX_RITUAL = 120
MAX_LINE = 140
MAX_GARMENT = 200
MAX_CHEST = 40
MAX_LANGUAGE = 12
MAX_CTA = 60
DURATIONS = (10, 15, 30)
DEFAULT_DURATION = 15
CLIP_UNIT_S = 5.0
VOICE_FREE = "free"
VOICE_PREMIUM = "eleven_v3"  # wire value of the studio voice (ElevenLabs v3 or the Replicate voice lane)
VOICE_ENGINES = (VOICE_FREE, VOICE_PREMIUM)
DELIVERIES = ("deadpan", "quiet", "tired", "warm")
PAYOFF_NATIVE = "native"
PAYOFF_LIPSYNC = "lipsync"
PAYOFF_VOICEOVER = "voiceover"
PAYOFF_MODES = (PAYOFF_NATIVE, PAYOFF_LIPSYNC, PAYOFF_VOICEOVER)
VOICE_CREDITS_ENV = "VERY_TIME_VOICE_CREDITS"
SFX_CREDITS_ENV = "VERY_TIME_SFX_CREDITS"
VIDEO_MODEL_ENV = "VERY_TIME_VIDEO_MODEL"
BLOCKED_ENV = "VERY_TIME_BLOCKED_WORDS"
GUARD_FIELDS = ("place_word", "ritual", "line", "garment", "chest_text", "reply_line", "cta")

_PLACE = re.compile(r"^[^\W\d_]+(?:[ \-][^\W\d_]+)*$")
_SLOT = re.compile(r"\{(\w+)\}")
# Simple English plurals and the common Turkish case / plural / -li suffixes, after folding.
_SUFFIX = (r"(?:'?(?:s|es|lar|ler|lari|leri|larin|lerin|larda|lerde|i|u|in|un|nin|nun|a|e|ya|ye|da|de|ta|te"
           r"|dan|den|tan|ten|li|lu|lik|luk|ci|cu|ca|ce))?")


class GuardBlocked(story8.Story8Error):
    def __init__(self, terms: Sequence[str]) -> None:
        self.terms = list(terms)
        super().__init__(400, "guard_blocked",
                         f"this video cannot be made with: {', '.join(self.terms)}. Keep it affectionate and "
                         "everyday: no flags, crescents, sultans, costumes, landmarks or mocking.")


def preset() -> dict[str, Any]:
    return story8.preset(PRESET_NAME)


def video_model() -> str:
    return (os.getenv(VIDEO_MODEL_ENV) or "").strip() or str(preset()["animated"]["video_model"])


# --------------------------------------------------------------------------- #
# Brand presets (built-in brands: garment, chest text, host, line, CTA, assets)
# --------------------------------------------------------------------------- #
BRANDS_DIR = Path(__file__).resolve().parents[3] / "assets" / "brands"
BRAND_PRESETS = ("oxhan",)
BRAND_CUSTOM = "custom"


@lru_cache(maxsize=8)
def brand_preset(name: str) -> dict[str, Any]:
    """A built-in brand (``assets/brands/<id>/brand.json``)."""
    if name not in BRAND_PRESETS:
        raise story8.Story8Error(400, "brand", f"brand preset is one of {', '.join(BRAND_PRESETS)}")
    data = json.loads((BRANDS_DIR / name / "brand.json").read_text(encoding="utf-8"))
    if data.get("id") != name:
        raise ValueError(f"brand {name}: wrong id")
    return data


def brand_asset_path(name: str, asset: str) -> Path | None:
    """Local file of a built-in brand asset (``sheet`` / ``garment`` / ``logo``), or None."""
    if not name or name not in BRAND_PRESETS:
        return None
    filename = (brand_preset(name).get("assets") or {}).get(asset)
    path = BRANDS_DIR / name / str(filename or "")
    return path if filename and path.is_file() else None


def brand_asset_key(name: str, asset: str) -> str | None:
    """The storage key a built-in brand asset is uploaded to once (server-written, versioned)."""
    path = brand_asset_path(name, asset)
    if path is None:
        return None
    return f"brands/{name}/v{int(brand_preset(name).get('version') or 1)}/{path.name}"


# --------------------------------------------------------------------------- #
# Length: 10, 15 or 30 s; the beats scale, the end card closes, the total is exact
# --------------------------------------------------------------------------- #
def end_card_seconds(duration_s: int) -> float:
    table = preset().get("end_card") or {}
    return float((table.get("seconds") or {}).get(str(duration_s)) or 2.0)


def beat_lengths(duration_s: int, *, end_card: bool) -> tuple[list[float], float]:
    """Beat seconds scaled to fill ``duration_s`` minus the end card; the last beat absorbs rounding."""
    data = preset()
    base = [story8.beat_seconds(data, i) for i in range(len(data["beats"]))]
    end_s = end_card_seconds(duration_s) if end_card else 0.0
    room = float(duration_s) - end_s
    scale = room / sum(base)
    seconds = [round(s * scale, 1) for s in base]
    seconds[-1] = round(room - sum(seconds[:-1]), 3)
    return seconds, end_s


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Inputs:
    place_word: str
    ritual: str
    line: str
    look: str
    garment: str
    chest_text: str
    language: str = ""
    character_id: str | None = None
    duration_s: int = DEFAULT_DURATION
    brand_preset: str = ""
    chest_style: str = ""
    host: str = ""
    garment_ref: str = ""
    logo_ref: str = ""
    cta: str = ""
    reply_line: str = ""
    voice_engine: str = VOICE_FREE
    delivery: str = "deadpan"
    take_key: str = ""
    sfx: bool = False
    room_tone: bool = False
    payoff: str = PAYOFF_NATIVE

    @property
    def end_card(self) -> bool:
        return bool(self.cta or self.logo_ref or brand_asset_path(self.brand_preset, "logo"))


def _one_line(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _upload_ref(value: Any, field: str) -> str:
    key = str(value or "").strip()
    if key and (not key.startswith("uploads/") or ".." in key or len(key) > 300):
        raise story8.Story8Error(400, field, "use a file you uploaded")
    return key


def _choice(value: Any, allowed: Sequence[str], default: str, field: str) -> str:
    chosen = str(value or default).strip().lower()
    if chosen not in allowed:
        raise story8.Story8Error(400, field, f"{field} is one of {', '.join(allowed)}")
    return chosen


def _brand_fields(brand: Mapping[str, Any], place: str) -> dict[str, str]:
    """Merge a built-in brand preset (when named) under the user's own brand fields."""
    data = preset()
    name = str(brand.get("preset") or "").strip().lower()
    if name in ("", BRAND_CUSTOM):
        name = ""
    base = brand_preset(name) if name else {}
    garment = _one_line(brand.get("garment"), MAX_GARMENT + 1) or base.get("garment") or data["brand"]["garment"]
    chest = _one_line(brand.get("chest_text"), MAX_CHEST + 1) or base.get("chest_text") or data["brand"]["chest_text"]
    cta = _one_line(brand.get("cta"), MAX_CTA + 1) or str(base.get("cta") or "")
    garment, chest = garment.replace("{place_word}", place), chest.replace("{place_word}", place)
    if len(garment) > MAX_GARMENT or len(chest) > MAX_CHEST or len(cta) > MAX_CTA:
        raise story8.Story8Error(400, "brand", f"the garment is {MAX_GARMENT}, the chest text {MAX_CHEST} and the "
                                               f"closing call to action {MAX_CTA} characters at most")
    return {"preset": name, "garment": garment, "chest_text": chest, "cta": cta,
            "chest_style": str(base.get("chest_style") or ""), "host": str(base.get("host") or ""),
            "line": str(base.get("line") or ""),
            "garment_ref": _upload_ref(brand.get("garment_ref"), "garment_ref"),
            "logo_ref": _upload_ref(brand.get("logo_ref"), "logo_ref")}


def clean_inputs(*, place_word: str, ritual: str, line: str | None = None, look: str | None = None,
                 brand: Mapping[str, Any] | None = None, language: str = "",
                 character_id: str | None = None, duration_s: int | None = None,
                 voice: Mapping[str, Any] | None = None, sound: Mapping[str, Any] | None = None,
                 payoff: str | None = None) -> Inputs:
    data = preset()
    place = _one_line(place_word, MAX_PLACE + 1)
    if not place or len(place) > MAX_PLACE or not _PLACE.match(place):
        raise story8.Story8Error(400, "place_word", f"the place word is 1 to {MAX_PLACE} letters (spaces and "
                                                    "hyphens are fine)")
    ritual_text = _one_line(ritual, MAX_RITUAL + 1)
    if not ritual_text or len(ritual_text) > MAX_RITUAL:
        raise story8.Story8Error(400, "ritual", f"describe the ritual in 1 to {MAX_RITUAL} characters")
    look_id = _choice(look, LOOKS, data["default_look"], "look")
    length = int(duration_s or DEFAULT_DURATION)
    if length not in DURATIONS:
        raise story8.Story8Error(400, "duration_s", "the video is 10, 15 or 30 seconds long")
    fields = _brand_fields(dict(brand or {}), place)
    spoken = _one_line(line, MAX_LINE + 1) or fields["line"] or data["default_line"]
    spoken = spoken.replace("{place_word}", place)
    if len(spoken) > MAX_LINE:
        raise story8.Story8Error(400, "line", f"the line is {MAX_LINE} characters at most")
    voice = dict(voice or {})
    reply = _one_line(voice.get("reply_line"), MAX_LINE + 1)
    if len(reply) > MAX_LINE:
        raise story8.Story8Error(400, "reply_line", f"the answer is {MAX_LINE} characters at most")
    sound = dict(sound or {})
    return Inputs(
        place_word=place, ritual=ritual_text, line=spoken, look=look_id, garment=fields["garment"],
        chest_text=fields["chest_text"], language=_one_line(language, MAX_LANGUAGE),
        character_id=character_id or None, duration_s=length, brand_preset=fields["preset"],
        chest_style=fields["chest_style"], host=fields["host"], garment_ref=fields["garment_ref"],
        logo_ref=fields["logo_ref"], cta=fields["cta"], reply_line=reply,
        voice_engine=_choice(voice.get("engine"), VOICE_ENGINES, VOICE_FREE, "voice engine"),
        delivery=_choice(voice.get("delivery"), DELIVERIES, "deadpan", "delivery"),
        take_key=str(voice.get("take_key") or "").strip()[:200],
        sfx=bool(sound.get("sfx")), room_tone=bool(sound.get("room_tone")),
        payoff=_choice(payoff, PAYOFF_MODES, PAYOFF_NATIVE, "payoff"),
    )


# --------------------------------------------------------------------------- #
# Guard-rail (pure; runs before any credit or provider call)
# --------------------------------------------------------------------------- #
def fold(text: Any) -> str:
    """Turkish-aware casefold: I/ı/İ/i fold together, accents dropped, curly apostrophes straightened."""
    lowered = str(text or "").replace("İ", "i").replace("I", "i").replace("ı", "i").casefold()
    stripped = "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c))
    return stripped.replace("’", "'").replace("‘", "'")


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in re.split(r"[\s\-_]+", fold(term)) if w]
    return re.compile(r"(?<!\w)" + r"[\s\-_]*".join(words) + _SUFFIX + r"(?!\w)")


def _banned_terms() -> list[str]:
    banned = preset().get("banned") or {}
    return [t for key in ("imagery", "mocking", "do_not_copy") for t in banned.get(key) or []]


def _place_only_terms() -> list[str]:
    from app.domains.social_inbox.engagement_classify import _ABUSE_WORDS

    extra = [w.strip() for w in (os.getenv(BLOCKED_ENV) or "").split(",") if w.strip()]
    return [*_ABUSE_WORDS, *extra]


def _field(inputs: Inputs | Mapping[str, Any], name: str) -> str:
    if isinstance(inputs, Mapping):
        if name in ("garment", "chest_text", "cta"):
            return str(inputs.get(name) or (inputs.get("brand") or {}).get(name) or "")
        return str(inputs.get(name) or "")
    return str(getattr(inputs, name, "") or "")


def guard(inputs: Inputs | Mapping[str, Any]) -> list[str]:
    """Blocked terms found in the user's texts (empty list = clean). Pure; no I/O beyond env."""
    from app.domains.broll.router import _PROMPT_DENYLIST

    hits: list[str] = []

    def add(term: str) -> None:
        if term not in hits:
            hits.append(term)

    texts = {name: fold(_field(inputs, name)) for name in GUARD_FIELDS}
    joined = " ".join(texts.values())
    for term in _PROMPT_DENYLIST:  # the same substring rule story8.moderate applies
        if fold(term) in joined:
            add(term)
    for term in _banned_terms():
        if _term_pattern(term).search(joined):
            add(term)
    for term in _place_only_terms():
        if _term_pattern(term).search(texts["place_word"]):
            add(term)
    for term in hate_terms.terms():  # curated slurs and hate symbols, every field
        if _term_pattern(term).search(joined):
            add(term)
    return hits


def check(inputs: Inputs) -> None:
    terms = guard(inputs)
    if terms:
        raise GuardBlocked(terms)


# --------------------------------------------------------------------------- #
# Frames: locked host + brand garment, per-beat prompts, the shot brief
# --------------------------------------------------------------------------- #
def _fill(template: str, slots: Mapping[str, str]) -> str:
    return _SLOT.sub(lambda m: slots.get(m.group(1), m.group(0)), str(template or ""))


def _slots(inputs: Inputs) -> dict[str, str]:
    return {"place_word": inputs.place_word, "ritual": inputs.ritual, "line": inputs.line,
            "garment": inputs.garment, "chest_text": inputs.chest_text}


def continuity(inputs: Inputs) -> str:
    return _fill(preset()["continuity"], _slots(inputs))


def _wearing(inputs: Inputs) -> str:
    style = f" in {inputs.chest_style}" if inputs.chest_style else ""
    return f'wearing {inputs.garment}, the chest embroidery reading "{inputs.chest_text}"{style}'


def _profile(inputs: Inputs, character: Mapping[str, Any] | None):
    from app.domains.characters.consistency import CharacterProfile

    data = preset()
    look = data["looks"][inputs.look]
    wearing = _wearing(inputs)
    style = ", ".join(p for p in (look["style"], data["style"]) if p)
    negative = (*data["negative"], *look.get("negative", ()), *data.get("negative_imagery", ()))
    if character:
        return CharacterProfile(
            character_id=str(character.get("id") or ""), name=str(character.get("name") or ""),
            descriptors=(*(character.get("descriptors") or ()), wearing),
            style=", ".join(p for p in (str(character.get("style") or ""), style) if p),
            reference_images=tuple(character.get("reference_images") or ()),
            lora_ref=str(character.get("lora_ref") or ""),
            negative=(*(character.get("negative") or ()), *negative),
        )
    # No character: the brand's own host (Oxhan) or an invented deadpan host anchors every frame.
    name = "the same host" if inputs.host else "the same deadpan host"
    return CharacterProfile(character_id="", name=name, descriptors=(inputs.host or data["host"], wearing),
                            style=style, negative=negative)


def _brief(inputs: Inputs, beat: Mapping[str, Any], motion: str, seconds: float) -> dict[str, str]:
    look_name = str(preset()["looks"][inputs.look]["name"]).lower()
    if beat.get("speaks") and inputs.payoff == PAYOFF_NATIVE and not inputs.reply_line:
        audio = f'room tone; the host says the line flat and quiet: "{inputs.line}"; no music'
    elif beat.get("speaks"):
        audio = "room tone only; the host's lips move as if saying one short sentence; no music"
    else:
        audio = "room tone and one diegetic sound; no music; no speech"
    return {
        "format": f"9:16, {seconds:g} s, 720p", "action": motion, "camera": str(beat.get("camera_text") or ""),
        "continuity": continuity(inputs), "audio": audio,
        "constraints": f"no new people, no text appearing, no camera shake, keep the {look_name} look",
    }


def shot_credits(seconds: float) -> int:
    """AI-video credits for one shot: one clip's credits per started 5 s of footage."""
    return story8.clip_credits() * max(1, math.ceil(float(seconds) / CLIP_UNIT_S - 1e-9))


def build_frames(inputs: Inputs, character: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    from app.domains.characters.consistency import build_shot_prompt

    data = preset()
    profile = _profile(inputs, character)
    slots = _slots(inputs)
    lengths, _ = beat_lengths(inputs.duration_s, end_card=inputs.end_card)
    rows = []
    for index, beat in enumerate(data["beats"]):
        seconds = lengths[index]
        motion = _fill(beat["motion_prompt"], slots)
        shot = build_shot_prompt(profile, _fill(beat["image_prompt"], slots), shot_index=index,
                                 scene=beat["direction"])
        rows.append({
            "index": index, "beat": beat["id"], "line": inputs.line if beat.get("speaks") else "",
            "prompt": shot.prompt[:1200], "negative": shot.negative_prompt[:600], "seed": shot.seed,
            "camera": beat["camera"], "seconds": seconds, "motion": motion,
            "brief": _brief(inputs, beat, motion, seconds),
            "chest": "{chest_text}" in str(beat.get("image_prompt") or ""),
            "chest_region": list(beat.get("chest_region") or (0.5, 0.55)),
            "sfx": _fill(str(beat.get("sfx") or ""), slots)[:200],
            "ai_credits": shot_credits(seconds),
        })
    return rows


def caption_style(look: str) -> str:
    return str(preset()["looks"][look]["caption_style"])


# --------------------------------------------------------------------------- #
# Price first: length, frames, animation, premium voice and sound effects
# --------------------------------------------------------------------------- #
def _env_credits(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name) or default))
    except ValueError:
        return default


def extras(inputs: Inputs) -> dict[str, int]:
    return {"voice_credits": _env_credits(VOICE_CREDITS_ENV, 1) if inputs.voice_engine == VOICE_PREMIUM else 0,
            "sfx_credits": _env_credits(SFX_CREDITS_ENV, 1) if inputs.sfx else 0}


def quote(rows: Sequence[Mapping[str, Any]], inputs: Inputs) -> dict[str, Any]:
    from app.domains.reels.pricing import standard_credits

    add = extras(inputs)
    standard = int(standard_credits(inputs.duration_s)) + int(preset()["frames_standard_credits"]) + sum(add.values())
    return {
        "seconds": inputs.duration_s,
        story8.MODE_FRAMES: {"standard_credits": standard, "ai_video_credits": 0},
        story8.MODE_ANIMATED: {"standard_credits": standard,
                               "ai_video_credits": sum(int(r["ai_credits"]) for r in rows)},
        "extras": add,
    }


def lanes_view() -> dict[str, Any]:
    from . import very_time_lanes as lanes

    return {"premium_voice": lanes.voice_backend() != "free", "sfx": bool(lanes.sfx_backend()),
            "lipsync": bool(lanes.lipsync_backend()), "animated": bool(lanes.video_model(True) or
                                                                        lanes.video_model(False)),
            "frames": bool(lanes.image_model(False))}


def end_card_view(inputs: Inputs) -> dict[str, Any]:
    _, end_s = beat_lengths(inputs.duration_s, end_card=inputs.end_card)
    return {"cta": inputs.cta, "logo": bool(inputs.logo_ref or brand_asset_path(inputs.brand_preset, "logo")),
            "seconds": end_s}


def plan_view(inputs: Inputs, character: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from app.domains.film import chest_check

    rows = build_frames(inputs, character)
    return {
        "preset": PRESET_REF, "look": inputs.look, "caption_style": caption_style(inputs.look),
        "duration_s": inputs.duration_s, "brand_preset": inputs.brand_preset or BRAND_CUSTOM,
        "lines": [r["line"] for r in rows], "beats": [story8.frame_view(r) for r in rows],
        "reply_line": inputs.reply_line, "end_card": end_card_view(inputs),
        "chest_rerolls": chest_check.max_rerolls_from_env(), "lanes": lanes_view(),
        "quote": quote(rows, inputs),
    }


# --------------------------------------------------------------------------- #
# Start: guard, owned files, live lanes, price check, debit (story8's shared path)
# --------------------------------------------------------------------------- #
def check_files(session: Session, user_id: str, inputs: Inputs) -> None:
    """Uploads must be the caller's own; a chosen voice take must be one of theirs."""
    from app.domains.media.service import MediaDomainError, require_owned_asset

    for field, key in (("garment_ref", inputs.garment_ref), ("logo_ref", inputs.logo_ref)):
        if key:
            try:
                require_owned_asset(session, user_id=user_id, key=key)
            except MediaDomainError as exc:
                raise story8.Story8Error(403, field, "use a file you uploaded") from exc
    if inputs.take_key:
        from . import very_time_voice

        if not very_time_voice.owns_take(user_id, inputs.take_key):
            raise story8.Story8Error(403, "take_not_yours", "pick one of your own voice takes")


def check_lanes(inputs: Inputs, mode: str, *, with_refs: bool) -> dict[str, str]:
    """Pick the providers for this job from the keys that are configured; refuse what cannot run."""
    from . import very_time_lanes as lanes

    image = lanes.image_model(with_refs) or lanes.image_model(False)
    if not image:
        raise story8.Story8Error(503, "lane_unavailable", "making pictures is not available right now")
    video = ""
    if mode == story8.MODE_ANIMATED:
        override = (os.getenv(VIDEO_MODEL_ENV) or "").strip()
        video = override or lanes.video_model(with_refs) or lanes.video_model(False) or ""
        if not video:
            raise story8.Story8Error(503, "lane_unavailable", "the animated version is not available right now")
    if inputs.voice_engine == VOICE_PREMIUM and lanes.voice_backend() == "free":
        raise story8.Story8Error(503, "voice_unavailable", "the studio voice is not available right now; "
                                                           "the free voice still works")
    if inputs.sfx and not lanes.sfx_backend():
        raise story8.Story8Error(503, "sfx_unavailable", "sound effects are not available right now")
    return {"image_model": image, "reference_image_model": lanes.image_model(True) or "", "video_model": video,
            "voice_backend": lanes.voice_backend(), "sfx_backend": lanes.sfx_backend() if inputs.sfx else "",
            "lipsync_backend": lanes.lipsync_backend()}


def start(session: Session, user_id: str, inputs: Inputs, *, mode: str, quoted: Mapping[str, int],
          request_id: str = "") -> Any:
    from app.domains.film import chest_check

    check(inputs)  # before the character lookup, the price check and any debit
    if mode not in story8.MODES:
        raise story8.Story8Error(400, "mode", f"mode is one of {', '.join(story8.MODES)}")
    check_files(session, user_id, inputs)
    character = story8._character(session, user_id, inputs.character_id)
    rows = build_frames(inputs, character)
    story8.moderate([r["prompt"] for r in rows])
    refs = list((character or {}).get("reference_images") or [])
    sheet = _character_sheet(session, inputs.character_id) if character else None
    identity = sheet or (refs[0] if refs else None)
    with_refs = bool(identity or inputs.garment_ref or inputs.brand_preset)
    picked = check_lanes(inputs, mode, with_refs=with_refs)
    price = quote(rows, inputs)
    payoff = inputs.payoff if mode == story8.MODE_ANIMATED else PAYOFF_VOICEOVER
    extra = {
        "look": inputs.look, "place_word": inputs.place_word, "ritual": inputs.ritual, "line": inputs.line,
        "reply_line": inputs.reply_line, "duration_s": inputs.duration_s,
        "brand": {"garment": inputs.garment, "chest_text": inputs.chest_text, "preset": inputs.brand_preset,
                  "cta": inputs.cta, "garment_ref": inputs.garment_ref or None, "logo_ref": inputs.logo_ref or None},
        "caption_style": caption_style(inputs.look), **picked,
        "character_ref": identity, "end_card": end_card_view(inputs),
        "voice": {"engine": inputs.voice_engine, "delivery": inputs.delivery, "take_key": inputs.take_key or None},
        "sound": {"sfx": inputs.sfx, "room_tone": inputs.room_tone and mode == story8.MODE_ANIMATED},
        "payoff": payoff, "chest_rerolls": chest_check.max_rerolls_from_env(), "extras": price["extras"],
    }
    return story8.start_frames(session, user_id, frames=rows, mode=mode, quoted=quoted, preset_name=PRESET_NAME,
                               character=character, language=inputs.language, request_id=request_id, extra=extra,
                               price=price[mode])


def _character_sheet(session: Session, character_id: str | None) -> str | None:
    if not character_id:
        return None
    from app.domains.characters.turnaround import sheet_key

    return sheet_key(session, character_id)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class BrandBody(BaseModel):
    preset: str = Field("", max_length=16)
    garment: str = Field("", max_length=MAX_GARMENT)
    chest_text: str = Field("", max_length=MAX_CHEST)
    garment_ref: str = Field("", max_length=300)
    logo_ref: str = Field("", max_length=300)
    cta: str = Field("", max_length=MAX_CTA)


class VoiceBody(BaseModel):
    engine: str = Field(VOICE_FREE, max_length=16)
    delivery: str = Field("deadpan", max_length=16)
    take_key: str = Field("", max_length=200)
    reply_line: str = Field("", max_length=MAX_LINE)


class SoundBody(BaseModel):
    sfx: bool = False
    room_tone: bool = False


class PlanRequest(BaseModel):
    place_word: str = Field(..., max_length=MAX_PLACE)
    ritual: str = Field(..., max_length=MAX_RITUAL)
    line: str | None = Field(default=None, max_length=MAX_LINE)
    look: str = Field("console", max_length=16)
    character_id: str | None = Field(default=None, max_length=32)
    brand: BrandBody | None = None
    language: str = Field("", max_length=MAX_LANGUAGE)
    duration_s: int = Field(DEFAULT_DURATION, ge=1, le=60)
    voice: VoiceBody | None = None
    sound: SoundBody | None = None
    payoff: str = Field(PAYOFF_NATIVE, max_length=16)

    def inputs(self) -> Inputs:
        return clean_inputs(place_word=self.place_word, ritual=self.ritual, line=self.line, look=self.look,
                            brand=self.brand.model_dump() if self.brand else None, language=self.language,
                            character_id=self.character_id, duration_s=self.duration_s,
                            voice=self.voice.model_dump() if self.voice else None,
                            sound=self.sound.model_dump() if self.sound else None, payoff=self.payoff)


class StartRequest(PlanRequest):
    mode: str = Field(story8.MODE_FRAMES, max_length=16)
    quoted: story8.QuotedCredits


def _http(exc: story8.Story8Error, request_id: str) -> HttpException:
    data: dict[str, Any] = {"code": exc.code}
    if isinstance(exc, GuardBlocked):
        data["terms"] = exc.terms
    return HttpException(task_id=request_id, status_code=exc.status_code, message=f"{request_id}: {exc}", data=data)


@router.post("/film/very-time/plan", summary="Plan a Very ___ Time video: five shots, one line, both prices")
def plan_very_time(request: Request, body: PlanRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            inputs = body.inputs()
            check(inputs)  # before the character lookup and any provider call
            check_files(session, str(user.id), inputs)
            view = plan_view(inputs, story8._character(session, str(user.id), inputs.character_id))
        except story8.Story8Error as exc:
            raise _http(exc, request_id) from exc
    return utils.get_response(200, view)


@router.post("/film/very-time", summary="Make the Very ___ Time video (guard-rail and price checked first)")
def start_very_time(request: Request, body: StartRequest):
    request_id = base.get_task_id(request)
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        try:
            inputs = body.inputs()
            job = start(session, str(user.id), inputs, mode=body.mode, quoted=body.quoted.model_dump(),
                        request_id=request_id)
        except story8.Story8Error as exc:
            raise _http(exc, request_id) from exc
        job_id = job.id
    story8.enqueue_or_refund(job_id, request_id)
    return utils.get_response(200, {"job_id": job_id, "state": story8.TASK_STATE_PROCESSING})


__all__ = ["BRAND_PRESETS", "DURATIONS", "GuardBlocked", "Inputs", "LOOKS", "PRESET_NAME", "PRESET_REF",
           "beat_lengths", "brand_asset_key", "brand_asset_path", "brand_preset", "build_frames", "check",
           "clean_inputs", "fold", "guard", "plan_view", "quote", "router", "start"]
