"""Subtitles (MV16): transcript words to WebVTT cues, translations through Relay, HLS subtitle renditions.

* Cues end on sentence boundaries where possible, never run longer than 7 s
  or 84 characters (two lines of 42).
* Translation keeps the cue count and timing: the model gets the cue texts as
  a JSON array and must return an array of the same length (checked); every
  LLM call goes through Relay (``services.llm``).
* Each language becomes a WebVTT file plus a one-segment media playlist, and
  the title's HLS master gains an ``EXT-X-MEDIA:TYPE=SUBTITLES`` rendition in
  group ``subs`` (``SUBTITLES="subs"`` on every variant).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

MAX_CUE_S = 7.0
MAX_CUE_CHARS = 84
LINE_CHARS = 42
GROUP = "subs"
LANGUAGE_NAMES = {
    "en": "English", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português", "it": "Italiano",
    "tr": "Türkçe", "ja": "日本語", "ko": "한국어", "zh": "中文", "hi": "हिन्दी", "ar": "العربية", "ru": "Русский",
    "nl": "Nederlands", "pl": "Polski", "id": "Bahasa Indonesia",
}
_SENTENCE_END = re.compile(r"[.!?…]['\")\]]*$")

LLM = Callable[[str], str]


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _default_llm(prompt: str) -> str:
    from app.services import llm

    return llm._generate_response(prompt)


def cues_from_words(words: Sequence[object]) -> list[Cue]:
    """Group timed words (``.text``, ``.start``, ``.end``) into readable cues."""
    cues: list[Cue] = []
    current: list[object] = []

    def flush() -> None:
        if current:
            text = " ".join(str(getattr(w, "text", "")).strip() for w in current).strip()
            if text:
                cues.append(Cue(float(getattr(current[0], "start")), float(getattr(current[-1], "end")), text))
            current.clear()

    for word in words:
        token = str(getattr(word, "text", "")).strip()
        if not token:
            continue
        if current:
            length = len(" ".join(str(getattr(w, "text", "")) for w in current)) + 1 + len(token)
            span = float(getattr(word, "end")) - float(getattr(current[0], "start"))
            if length > MAX_CUE_CHARS or span > MAX_CUE_S:
                flush()
        current.append(word)
        if _SENTENCE_END.search(token):
            flush()
    flush()
    return cues


def sentences(cues: Sequence[Cue]) -> list[Cue]:
    """Merge cues into whole sentences (chapters start only on these)."""
    out: list[Cue] = []
    buffer: list[Cue] = []
    for cue in cues:
        buffer.append(cue)
        if _SENTENCE_END.search(cue.text):
            out.append(Cue(buffer[0].start, buffer[-1].end, " ".join(c.text for c in buffer)))
            buffer = []
    if buffer:
        out.append(Cue(buffer[0].start, buffer[-1].end, " ".join(c.text for c in buffer)))
    return out


def _stamp(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def _wrap(text: str) -> str:
    if len(text) <= LINE_CHARS:
        return text
    cut = text.rfind(" ", 0, LINE_CHARS + 1)
    cut = cut if cut > 0 else LINE_CHARS
    return f"{text[:cut].strip()}\n{text[cut:].strip()}"


def to_vtt(cues: Sequence[Cue]) -> str:
    blocks = ["WEBVTT", ""]
    for n, cue in enumerate(cues, start=1):
        blocks += [str(n), f"{_stamp(cue.start)} --> {_stamp(max(cue.end, cue.start + 0.5))}", _wrap(cue.text), ""]
    return "\n".join(blocks)


def parse_json_array(raw: str) -> list:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("no JSON array in the answer")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, list):
        raise ValueError("not a JSON array")
    return value


def translate(cues: Sequence[Cue], language: str, *, llm: LLM | None = None, batch: int = 60) -> list[Cue]:
    """The same cues in ``language``; raises ``ValueError`` when an answer does not keep the cue count."""
    call = llm or _default_llm
    name = LANGUAGE_NAMES.get(language, language)
    out: list[Cue] = []
    for start in range(0, len(cues), batch):
        chunk = list(cues[start:start + batch])
        prompt = (f"Translate each subtitle line into {name}. Keep the meaning, keep it short enough to read, "
                  f"do not merge or split lines. Answer with only a JSON array of {len(chunk)} strings, in order.\n"
                  + json.dumps([c.text for c in chunk], ensure_ascii=False))
        lines = parse_json_array(call(prompt))
        if len(lines) != len(chunk) or not all(isinstance(x, str) and x.strip() for x in lines):
            raise ValueError(f"the translation returned {len(lines)} lines for {len(chunk)} cues")
        out += [Cue(c.start, c.end, " ".join(t.split())) for c, t in zip(chunk, lines)]
    return out


def media_playlist(vtt_name: str, duration_s: float) -> str:
    target = max(1, math.ceil(duration_s))
    return "\n".join(["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}", "#EXT-X-MEDIA-SEQUENCE:0",
                      "#EXT-X-PLAYLIST-TYPE:VOD", f"#EXTINF:{duration_s:.3f},", vtt_name, "#EXT-X-ENDLIST", ""])


def _attr_quote(value: str) -> str:
    return value.replace('"', "'")


def add_rendition(master: str, *, kind: str, group: str, language: str, name: str, uri: str) -> str:
    """Add (or replace) one ``EXT-X-MEDIA`` rendition and point every variant at its group."""
    attribute = "SUBTITLES" if kind == "SUBTITLES" else "AUDIO"
    lines = [line for line in master.splitlines()
             if not (line.startswith("#EXT-X-MEDIA:") and f'TYPE={kind}' in line and f'GROUP-ID="{group}"' in line
                     and f'LANGUAGE="{language}"' in line)]
    media = (f'#EXT-X-MEDIA:TYPE={kind},GROUP-ID="{group}",LANGUAGE="{language}",NAME="{_attr_quote(name)}",'
             f'AUTOSELECT=YES,DEFAULT=NO,URI="{uri}"')
    out: list[str] = []
    inserted = False
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:") and not inserted:
            out.append(media)
            inserted = True
        if line.startswith("#EXT-X-STREAM-INF:") and f'{attribute}="' not in line:
            line = f'{line},{attribute}="{group}"'
        out.append(line)
    if not inserted:
        out.append(media)
    return "\n".join(out) + ("\n" if not out[-1].endswith("\n") else "")


__all__ = ["Cue", "GROUP", "LANGUAGE_NAMES", "add_rendition", "cues_from_words", "media_playlist",
           "parse_json_array", "sentences", "to_vtt", "translate"]
