"""Unit: stories.script — cold-open first, CTA appended, word cap, deterministic."""

from __future__ import annotations

from app.domains.stories.parse import RedditThread
from app.domains.stories.script import DEFAULT_MAX_WORDS, build_story_script

_CTA = "Comment if you want Part 2."


def _thread(body: str, title: str = "AITA") -> RedditThread:
    return RedditThread(title=title, subreddit="AITA", author="op", body=body, top_comments=())


def test_cta_appended():
    script = build_story_script(_thread("Something happened. Then more happened."))
    assert script.endswith(_CTA)


def test_spicy_sentence_is_cold_open():
    body = "Some boring setup context. Did she really do that?! It escalated fast."
    script = build_story_script(_thread(body))
    # The '?!' sentence is promoted to the cold open even though it is not first.
    assert script.startswith("Did she really do that?!")


def test_first_sentence_when_no_spicy_marker():
    body = "This is the opener. This is the middle. This is the end."
    script = build_story_script(_thread(body))
    assert script.startswith("This is the opener.")


def test_word_cap_enforced_on_wall_of_text():
    body = " ".join(f"word{i}." for i in range(500))
    script = build_story_script(_thread(body), max_words=130)
    assert len(script.split()) <= 130
    assert script.endswith(_CTA)


def test_custom_max_words_respected():
    body = " ".join(f"token{i}" for i in range(200)) + "."
    script = build_story_script(_thread(body), max_words=40)
    assert len(script.split()) <= 40


def test_deterministic_output():
    t = _thread("First shocking line! Then the rest of the story unfolds slowly.")
    assert build_story_script(t) == build_story_script(t)


def test_default_max_words_constant():
    assert DEFAULT_MAX_WORDS == 130


def test_falls_back_to_title_when_body_blank():
    script = build_story_script(_thread("   ", title="Wild story title"))
    assert _CTA in script
    assert "Wild story title" in script
