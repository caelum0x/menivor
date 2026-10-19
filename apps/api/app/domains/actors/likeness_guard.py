"""No real-person likeness: AI actors are original synthetic people only.

Refused anywhere in an actor's name, look prompt, voice-design prompt or shot
template:

* a real person's name from ``policy/real-person-blocklist.json`` (whole words,
  case- and accent-insensitive; ``MENIVOR_LIKENESS_BLOCKLIST`` may point at an extra
  JSON file with the same ``names`` shape);
* asking for a lookalike, an impersonation, a face swap or "in the style of" a person;
* voice cloning (the Ad Clone voice rule: :func:`ipguard.check_voice_description`).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from loguru import logger

_REPO = Path(__file__).resolve().parents[5]
BLOCKLIST_FILE = _REPO / "policy" / "real-person-blocklist.json"
EXTRA_ENV = "MENIVOR_LIKENESS_BLOCKLIST"
#: Used only when the policy file is not shipped with the build.
BUILTIN = ("Taylor Swift", "Beyonce", "Kim Kardashian", "Cristiano Ronaldo", "Lionel Messi", "Elon Musk",
           "Donald Trump", "Barack Obama", "Tom Cruise", "Brad Pitt", "Zendaya", "MrBeast", "Oprah Winfrey",
           "Dwayne Johnson", "Keanu Reeves", "Scarlett Johansson", "Rihanna", "Selena Gomez", "Billie Eilish",
           "LeBron James", "Mark Zuckerberg", "Jeff Bezos", "Bill Gates", "Kylie Jenner", "Justin Bieber")
_IMPERSONATION = re.compile(
    r"\b(look\s*-?\s*alike|lookalike|looks?\s+(exactly\s+)?like|resembl\w*|double\s+of|doppelg\w*|"
    r"impersonat\w*|face\s*-?\s*swap|deep\s*-?\s*fake|in\s+the\s+style\s+of|clone\s+of|twin\s+of|"
    r"based\s+on\s+(a\s+)?real\s+person|real\s+person|celebrity|famous\s+(actor|actress|person|singer|athlete))\b",
    re.I,
)


class LikenessError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems
        self.message = problems[0] if problems else "not allowed"
        self.status_code = 422


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.lower()).split())


def _read(path: Path) -> list[str]:
    try:
        return [str(n) for n in json.loads(path.read_text(encoding="utf-8")).get("names", [])]
    except (OSError, ValueError) as exc:
        logger.warning(f"likeness blocklist {path.name} unreadable: {type(exc).__name__}")
        return []


@lru_cache(maxsize=1)
def blocked_names() -> tuple[str, ...]:
    names = _read(BLOCKLIST_FILE) if BLOCKLIST_FILE.exists() else list(BUILTIN)
    extra = os.environ.get(EXTRA_ENV, "").strip()
    if extra:
        names += _read(Path(extra))
    folded = {_fold(n) for n in names if _fold(n)}
    return tuple(sorted(folded))


def real_names_in(text: str) -> list[str]:
    hay = f" {_fold(text)} "
    return [n for n in blocked_names() if f" {n} " in hay]


def problems(fields: dict[str, str]) -> list[str]:
    out: list[str] = []
    for label, value in fields.items():
        if not value:
            continue
        hits = real_names_in(value)
        if hits:
            out.append(f"{label}: names a real person ({hits[0].title()}); AI actors are original people only")
        if _IMPERSONATION.search(value):
            out.append(f"{label}: no lookalikes, impersonations or real-person references")
    voice = fields.get("voice prompt", "")
    if voice:
        from app.domains.adclone.ipguard import IPGuardError, check_voice_description

        try:
            check_voice_description(voice)
        except IPGuardError as exc:
            out.extend(f"voice prompt: {p}" for p in exc.problems)
    return list(dict.fromkeys(out))


def enforce(**fields: str) -> None:
    labelled = {k.replace("_", " "): str(v or "") for k, v in fields.items()}
    found = problems(labelled)
    if found:
        raise LikenessError(found)


def check_all(texts: Iterable[str]) -> list[str]:
    return problems({f"text {i + 1}": t for i, t in enumerate(texts)})


__all__ = ["LikenessError", "blocked_names", "check_all", "enforce", "problems", "real_names_in"]
