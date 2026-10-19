"""Keyless faceless path: edge-tts WordBoundary cues become caption word timings."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import edge_tts

from app.services.reelforge import _submaker_words


def test_edge_cues_become_words():
    sub = edge_tts.SubMaker()
    sub.feed({"type": "WordBoundary", "offset": 0, "duration": 5_000_000, "text": "Hello"})
    sub.feed({"type": "WordBoundary", "offset": 5_000_000, "duration": 4_000_000, "text": "world"})
    assert _submaker_words(sub) == [["Hello", 0.0, 0.5], ["world", 0.5, 0.9]]


def test_elevenlabs_words_take_precedence():
    sub = SimpleNamespace(
        words=[SimpleNamespace(text="hi", start=0.0, end=0.2)],
        cues=[SimpleNamespace(content="ignored", start=timedelta(0), end=timedelta(seconds=1))],
    )
    assert _submaker_words(sub) == [["hi", 0.0, 0.2]]
