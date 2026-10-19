"""Original narrator characters (M2.3): the fixed roster.

Each narrator has an invented name, a personality line, one fixed voice (a
Kokoro voice with an edge-tts fallback) and a ``look`` the procedural artist
(:mod:`app.domains.characters.narrator_art`) draws. The roster lives in
``apps/api/assets/characters/roster.json``; ``sheet_sha256`` in the lock file
pins each character's reference sheet so the same character renders
identically in every episode.

No real people and no third-party characters: :func:`denylist_hits` checks
names and personality text against :data:`DENYLIST` (tested for every entry).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

__all__ = [
    "DENYLIST",
    "LOCK_PATH",
    "ROSTER_PATH",
    "NarratorCharacter",
    "NarratorLook",
    "denylist_hits",
    "get_narrator",
    "list_narrators",
    "load_lock",
    "narrator_for_seed",
]

_ASSETS = Path(__file__).resolve().parents[3] / "assets" / "characters"
ROSTER_PATH: Path = _ASSETS / "roster.json"
LOCK_PATH: Path = _ASSETS / "sheets.lock.json"

BODIES = ("round", "tall", "pear", "square")
EYES = ("dot", "oval", "glasses")
TOPS = ("none", "tuft", "cap", "bun", "beanie", "antenna")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: Real people and third-party characters/franchises a narrator must never be
#: named after or described as (case-insensitive whole-word match).
DENYLIST: tuple[str, ...] = (
    # Cartoon, game and film characters / franchises
    "mickey", "minnie", "donald duck", "goofy", "pikachu", "pokemon", "mario",
    "luigi", "sonic", "kirby", "zelda", "link", "shrek", "spongebob", "patrick star",
    "homer", "bart", "simpson", "garfield", "snoopy", "peanuts", "batman", "superman",
    "spider-man", "spiderman", "elsa", "olaf", "moana", "stitch", "pooh", "tigger",
    "bugs bunny", "scooby", "peppa", "bluey", "minion", "minions", "yoda", "darth",
    "harry potter", "hermione", "gandalf", "frodo", "barbie", "ken doll", "hello kitty",
    "doraemon", "naruto", "goku", "totoro", "among us", "fortnite", "minecraft",
    "roblox", "steve", "creeper", "pac-man", "pacman", "lara croft", "master chief",
    "optimus", "transformers", "marvel", "disney", "pixar", "nintendo", "dreamworks",
    "looney", "muppet", "kermit", "elmo", "sesame",
    # Real people (creators, celebrities, public figures)
    "mrbeast", "mr beast", "pewdiepie", "khaby", "charli", "addison rae",
    "taylor swift", "beyonce", "drake", "kanye", "rihanna", "elon", "musk",
    "zuckerberg", "bezos", "obama", "trump", "biden", "oprah", "kardashian",
    "joe rogan", "andrew tate", "hormozi", "gary vee", "vaynerchuk", "ronaldo",
    "messi", "lebron", "attenborough", "morgan freeman", "david goggins",
)


@dataclass(frozen=True)
class NarratorLook:
    body: str
    skin: str
    accent: str
    backdrop: str
    eyes: str
    top: str


@dataclass(frozen=True)
class NarratorCharacter:
    id: str
    name: str
    personality: str
    voice: str
    fallback_voice: str
    look: NarratorLook

    def public_view(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "personality": self.personality,
            "voice": self.voice,
        }


def denylist_hits(text: str) -> list[str]:
    """Denylisted terms found in ``text`` (whole-word, case-insensitive)."""
    kept = re.sub(r"[^a-z0-9-]+", " ", (text or "").lower())
    variants = (f" {kept} ", f" {kept.replace('-', ' ')} ")
    return [term for term in DENYLIST if any(f" {term} " in v for v in variants)]


def _parse_look(raw: Mapping) -> NarratorLook:
    look = NarratorLook(
        body=str(raw.get("body", "")),
        skin=str(raw.get("skin", "")),
        accent=str(raw.get("accent", "")),
        backdrop=str(raw.get("backdrop", "")),
        eyes=str(raw.get("eyes", "")),
        top=str(raw.get("top", "")),
    )
    if look.body not in BODIES or look.eyes not in EYES or look.top not in TOPS:
        raise ValueError(f"narrator look has an unknown part: {look}")
    for colour in (look.skin, look.accent, look.backdrop):
        if not _HEX.match(colour):
            raise ValueError(f"narrator look colour must be #RRGGBB: {colour!r}")
    return look


@lru_cache(maxsize=1)
def _roster() -> Mapping[str, NarratorCharacter]:
    raw = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    out: dict[str, NarratorCharacter] = {}
    for entry in raw.get("characters", []):
        character = NarratorCharacter(
            id=str(entry["id"]),
            name=str(entry["name"]),
            personality=str(entry["personality"]),
            voice=str(entry["voice"]),
            fallback_voice=str(entry.get("fallback_voice", "")),
            look=_parse_look(entry.get("look") or {}),
        )
        if character.id in out:
            raise ValueError(f"duplicate narrator id {character.id!r}")
        out[character.id] = character
    return MappingProxyType(out)


def list_narrators() -> tuple[NarratorCharacter, ...]:
    return tuple(_roster().values())


def get_narrator(character_id: str) -> Optional[NarratorCharacter]:
    return _roster().get(str(character_id or "").strip().lower())


def narrator_for_seed(seed: str) -> NarratorCharacter:
    """A stable narrator for a series/topic seed (same seed, same narrator)."""
    import hashlib

    roster = list_narrators()
    digest = hashlib.sha256((seed or "").encode("utf-8")).digest()
    return roster[int.from_bytes(digest[:4], "big") % len(roster)]


def load_lock() -> Mapping[str, str]:
    """Character id -> locked reference-sheet SHA-256 (empty if no lock yet)."""
    if not LOCK_PATH.is_file():
        return MappingProxyType({})
    raw = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    sheets = raw.get("sheets") if isinstance(raw, dict) else None
    return MappingProxyType({str(k): str(v) for k, v in (sheets or {}).items()})
