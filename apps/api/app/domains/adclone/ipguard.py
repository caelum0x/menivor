"""IP-safety guard for Ad Clone plans. Runs before any plan is returned or rendered.

Hard rules (owner, 2026-10-06):
* never reproduce the source's character design (e.g. white hair / goggles / red coat: Capcom's Dante);
* never reuse source footage, frames, audio or voice;
* never clone a real person's voice;
* script lines are newly written: no verbatim copying of the source's spoken or on-screen words.
Only structure, pacing and the hook pattern carry over. The brand's own CTA line is allow-listed.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from typing import Any

NGRAM = 4
MAX_SIMILARITY = 0.72
ALLOWED_REF_PREFIXES = ("sheet/", "brand/", "mj/", "stills/")
MEDIA_EXT = (".mp4", ".mov", ".m4a", ".mp3", ".wav", ".aac", ".webm", ".mkv", ".flac", ".ogg")
VOICE_FORBIDDEN_KEYS = ("clone", "cloned", "reference_audio", "reference_audio_base64", "sample", "samples",
                        "source_audio")
_VOICE_IMITATION = re.compile(
    r"\b(clone|cloned|cloning|imitat\w*|impersonat\w*|impression of|sounds? (exactly )?like|voice of|"
    r"in the style of|celebrity|famous)\b", re.I)


class IPGuardError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("blocked by the IP guard: " + "; ".join(problems))
        self.status_code = 422
        self.problems = problems


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^\w$%' ]+", " ", (text or "").lower().replace("’", "'")).split()


def _ngrams(words: list[str], n: int = NGRAM) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


COMPACT_MIN = 6


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _term_hit(text: str, term: str) -> bool:
    """The term as words (any spacing), or, for long names, with the spaces taken out on either side:
    a domain name ``childrenofkhan`` also catches "Children of Khan"."""
    words = [re.escape(w) for w in re.split(r"[\s\-_]+", term.lower()) if w]
    if not words:
        return False
    if re.search(r"(?<![a-z0-9])" + r"[\s\-_]*".join(words) + r"(?![a-z0-9])", text.lower()) is not None:
        return True
    compact = _compact(term)
    return len(compact) >= COMPACT_MIN and compact in _compact(text)


def copied_lines(lines: Iterable[str], source_texts: Iterable[str], allow: Iterable[str] = ()) -> list[str]:
    """Our lines that copy the source: a shared 4-word run, or near-identical wording."""
    allowed = [_norm_words(a) for a in allow if a]
    src_texts = [t for t in source_texts if t and t.strip()]
    src_grams = set().union(*(_ngrams(_norm_words(t)) for t in src_texts)) if src_texts else set()
    for a in allowed:
        src_grams -= _ngrams(a)
    hits = []
    for line in lines:
        words = _norm_words(line)
        if any(" ".join(words) in " ".join(a) for a in allowed if words):
            continue  # our own brand line (or a part of it)
        if _ngrams(words) & src_grams:
            hits.append(line)
            continue
        joined = " ".join(words)
        if len(words) >= 3 and any(difflib.SequenceMatcher(None, joined, " ".join(_norm_words(s))).ratio()
                                   >= MAX_SIMILARITY for s in src_texts):
            hits.append(line)
    return hits


def check_voice_description(description: str) -> None:
    if not (description or "").strip():
        raise IPGuardError(["describe the voice (age, tone, accent)"])
    if _VOICE_IMITATION.search(description):
        raise IPGuardError(["voice designs are original: no cloning or imitating a real or famous person"])


def _texts(plan: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = [("set", str(plan.get("set") or "")), ("title", str(plan.get("title") or ""))]
    for k, c in (plan.get("characters") or {}).items():
        out.append((f"character {k}", f"{c.get('name', '')} {c.get('desc', '')}"))
    for s in plan.get("stills") or []:
        out.append((f"still {s.get('id')}", str(s.get("prompt") or "")))
    for s in plan.get("shots") or []:
        out.append((f"shot {s.get('id')}", f"{s.get('prompt') or ''} {s.get('audio') or ''}"))
    for ln in plan.get("lines") or []:
        out.append((f"line {ln.get('id')}", f"{ln.get('text') or ''} {ln.get('tts') or ''}"))
    return out


def _refs(plan: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = []
    for kind in ("stills", "shots"):
        for s in plan.get(kind) or []:
            for r in list(s.get("refs") or []) + ([s["first"]] if s.get("first") else []):
                out.append((f"{kind[:-1]} {s.get('id')}", str(r)))
    for k, c in (plan.get("characters") or {}).items():
        if c.get("sheet"):
            out.append((f"character {k}", str(c["sheet"])))
    return out


def _ref_problem(ref: str, source_markers: list[str]) -> str | None:
    low = ref.lower()
    if any(m and m.lower() in low for m in source_markers):
        return "points at the source video"
    if low.endswith(MEDIA_EXT):
        return "is a video/audio file (source footage or audio cannot be reused)"
    if ref.startswith("@") or "/" not in ref:
        return None
    if ref.startswith("/") or ".." in ref or not ref.startswith(ALLOWED_REF_PREFIXES):
        return f"must be one of our own assets under {', '.join(ALLOWED_REF_PREFIXES)}"
    return None


def check_plan(plan: Mapping[str, Any], *, banned_terms: Iterable[str], source_texts: Iterable[str],
               source_markers: Iterable[str] = (), allow_lines: Iterable[str] = ()) -> list[str]:
    """Every IP problem in a raw plan dict (empty list = clean)."""
    problems: list[str] = []
    terms = sorted({t.strip() for t in banned_terms if t and t.strip()})
    for where, text in _texts(plan):
        for term in terms:
            if _term_hit(text, term):
                problems.append(f"{where}: uses the source's design/brand term {term!r}")
    markers = [m for m in source_markers if m]
    for where, ref in _refs(plan):
        why = _ref_problem(ref, markers)
        if why:
            problems.append(f"{where}: ref {ref!r} {why}")
    for k, c in (plan.get("characters") or {}).items():
        voice = c.get("voice") or {}
        if isinstance(voice, Mapping) and any(key in voice for key in VOICE_FORBIDDEN_KEYS):
            problems.append(f"character {k}: voice may not be cloned from audio")
    lines = [str(ln.get("text") or "") for ln in plan.get("lines") or []]
    for line in copied_lines(lines, list(source_texts), allow_lines):
        problems.append(f"line copies the source wording: {line!r}")
    return problems


def enforce(plan: Mapping[str, Any], **kwargs: Any) -> None:
    problems = check_plan(plan, **kwargs)
    if problems:
        raise IPGuardError(problems)
