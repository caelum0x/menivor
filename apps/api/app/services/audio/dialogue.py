"""Per-character dialogue orchestration — script → ordered TTS turns.

Drives the two-host fake-podcast + any multi-speaker genre: parse a
``Speaker: line`` script into ordered turns, extract inline expressive tags
(``[laughs]``, ``(excited)``) that the expressive-TTS route (ElevenLabs v3 /
Chatterbox) consumes, and assign a stable voice per speaker. Pure + deterministic
(no TTS call here) so the parsing + voice-assignment logic is unit-testable; the
audio synthesis happens downstream per turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Inline tag forms: [tag] (bracket) or (tag) (paren) — both stripped from the
# spoken text and surfaced as expressive directives.
_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^)]+)\)")
# A speaker prefix "Name:" at the start of a line.
_SPEAKER_RE = re.compile(r"^\s*([A-Za-z0-9 _'-]{1,40}):\s*(.*)$")


@dataclass(frozen=True)
class DialogueTurn:
    """One speaker's line with its expressive tags + assigned voice."""

    speaker: str
    text: str                    # spoken text (tags removed)
    tags: tuple[str, ...] = ()   # expressive directives, lower-cased
    voice_id: str = ""


@dataclass(frozen=True)
class DialogueScript:
    """A parsed multi-speaker script."""

    turns: tuple[DialogueTurn, ...]
    speakers: tuple[str, ...] = field(default_factory=tuple)


def _extract_tags(line: str) -> tuple[str, list[str]]:
    tags: list[str] = []

    def _collect(m: re.Match) -> str:
        tag = (m.group(1) or m.group(2) or "").strip().lower()
        if tag:
            tags.append(tag)
        return ""

    cleaned = _TAG_RE.sub(_collect, line)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, tags


def parse_dialogue(script: str, *, voices: dict[str, str] | None = None,
                   default_voices: tuple[str, ...] = ("host_a", "host_b")) -> DialogueScript:
    """Parse a ``Speaker: line`` script into ordered :class:`DialogueTurn`s.

    Speakers are assigned a stable voice: an explicit ``voices`` mapping wins,
    otherwise speakers are cycled through ``default_voices`` in first-appearance
    order (so a 2-host podcast alternates host_a/host_b deterministically). A line
    with no ``Speaker:`` prefix continues the previous speaker.
    """
    voices = dict(voices or {})
    assigned: dict[str, str] = {}
    order: list[str] = []
    turns: list[DialogueTurn] = []
    current_speaker = ""

    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _SPEAKER_RE.match(line)
        if m:
            current_speaker = m.group(1).strip()
            content = m.group(2)
        else:
            content = line  # continuation of the previous speaker
        if not current_speaker:
            current_speaker = "narrator"

        if current_speaker not in assigned:
            order.append(current_speaker)
            if current_speaker in voices:
                assigned[current_speaker] = voices[current_speaker]
            elif default_voices:
                assigned[current_speaker] = default_voices[(len(order) - 1) % len(default_voices)]
            else:
                assigned[current_speaker] = ""

        text, tags = _extract_tags(content)
        if not text and not tags:
            continue
        turns.append(DialogueTurn(
            speaker=current_speaker, text=text, tags=tuple(tags),
            voice_id=assigned[current_speaker],
        ))

    return DialogueScript(turns=tuple(turns), speakers=tuple(order))
