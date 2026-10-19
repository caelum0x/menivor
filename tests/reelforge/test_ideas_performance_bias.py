"""Tests for the SPARK ↔ Hook-Performance integration (app/services/ideas.py).

SPARK learns from a creator's own winning hooks: when a ``session`` + ``user_id``
are supplied, ``generate_ideas`` fetches ``hook_performance.winning_hooks`` and
appends the winning hook text to the LLM prompt so the engine re-suggests
patterns that convert.

The two load-bearing guarantees under test:

  (a) WITH performance data — the winning hook text is passed into the
      generation context (the prompt the LLM sees).
  (b) WITHOUT performance data — behaviour is byte-for-byte the prior path: the
      prompt is IDENTICAL to the baseline (no session/user_id) call, no new
      exception, and (when there is nothing to inject) winning_hooks is not even
      consulted for extra LLM cost.

No network is hit: ``_generate_response`` is always monkeypatched, and the
winning-hooks fetch is monkeypatched so no DB is required.
"""

from __future__ import annotations

import json

import app.services.ideas as ideas


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _valid_idea(title: str = "Idea", hook: str = "A scroll stopping hook") -> dict:
    return {
        "title": title,
        "hook": hook,
        "angle": "Curiosity gap into a quick win",
        "format": "talking head",
        "script_outline": ["Hook the viewer.", "Show it.", "Payoff."],
        "suggested_layout": "pip",
        "suggested_caption_style": "karaoke_yellow",
        "language": "en",
        "est_duration_s": 25,
    }


def _payload(ideas_list) -> str:
    return json.dumps({"ideas": ideas_list})


def _capture_prompt_generator(sink: dict):
    """Return a fake ``_generate_response`` that records the prompt it received."""

    def fake_generate(prompt, app_config=None, temperature=None):
        sink["prompt"] = prompt
        return _payload([_valid_idea()])

    return fake_generate


class _SessionSentinel:
    """Opaque stand-in for a SQLAlchemy Session (never touched directly)."""


# --------------------------------------------------------------------------- #
# (a) WITH winning hooks -> hook text is injected into the generation context
# --------------------------------------------------------------------------- #
def test_winning_hooks_text_is_injected_into_prompt(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    winners = [
        {"hook": "POV: you finally fixed your sleep", "win_score": 87.5},
        {"hook": "I tried this for 30 days", "win_score": 61.0},
    ]
    monkeypatch.setattr(
        ideas, "_fetch_winning_hooks_block", ideas._fetch_winning_hooks_block
    )

    def fake_winning_hooks(session, user_id, limit=10):
        assert session is not None
        assert user_id == "user-123"
        return winners

    # Patch the symbol where it is looked up (imported lazily inside the fetch).
    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks", fake_winning_hooks
    )

    result = ideas.generate_ideas(
        "a sleep-tracking app",
        count=3,
        session=_SessionSentinel(),
        user_id="user-123",
    )

    assert result is not None
    prompt = sink["prompt"]
    # Both winning hook texts must be present in what the LLM actually sees.
    assert "POV: you finally fixed your sleep" in prompt
    assert "I tried this for 30 days" in prompt
    # And a clearly-labelled bias section, not just the raw strings.
    assert "Proven Winning Hooks" in prompt


def test_winning_hooks_block_is_appended_to_the_baseline_prompt(monkeypatch):
    """The bias must be additive: baseline prompt is a strict prefix of the biased one."""
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    baseline = ideas.build_ideas_prompt("a sleep-tracking app", "", 3, "auto")

    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks",
        lambda session, user_id, limit=10: [{"hook": "winner hook", "win_score": 42.0}],
    )

    ideas.generate_ideas(
        "a sleep-tracking app",
        count=3,
        session=_SessionSentinel(),
        user_id="user-123",
    )

    biased = sink["prompt"]
    assert biased.startswith(baseline)
    assert len(biased) > len(baseline)
    assert "winner hook" in biased[len(baseline):]


def test_only_top_hooks_are_injected(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    many = [{"hook": f"hook number {i}", "win_score": float(i)} for i in range(12)]
    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks",
        lambda session, user_id, limit=10: many,
    )

    ideas.generate_ideas(
        "an app", count=3, session=_SessionSentinel(), user_id="u"
    )
    prompt = sink["prompt"]
    injected = sum(1 for i in range(12) if f"hook number {i}" in prompt)
    assert injected == ideas.MAX_WINNING_HOOKS_INJECTED


# --------------------------------------------------------------------------- #
# (b) WITHOUT performance data -> byte-for-byte the prior path
# --------------------------------------------------------------------------- #
def test_no_session_prompt_is_identical_to_baseline(monkeypatch):
    """No session/user -> prompt is byte-for-byte the baseline build_ideas_prompt."""
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    # Guard: winning_hooks must NEVER be consulted when there is no session/user
    # (no extra work / LLM cost on the no-data path).
    def explode(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("winning_hooks must not be called without a session")

    monkeypatch.setattr("app.services.hook_performance.winning_hooks", explode)

    result = ideas.generate_ideas("a sleep-tracking app", count=3)
    assert result is not None

    baseline = ideas.build_ideas_prompt("a sleep-tracking app", "", 3, "auto")
    assert sink["prompt"] == baseline


def test_empty_winning_hooks_prompt_is_identical_to_baseline(monkeypatch):
    """A creator with logged-but-empty ranking gets the exact baseline prompt."""
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks",
        lambda session, user_id, limit=10: [],
    )

    result = ideas.generate_ideas(
        "a sleep-tracking app",
        count=3,
        session=_SessionSentinel(),
        user_id="user-123",
    )
    assert result is not None

    baseline = ideas.build_ideas_prompt("a sleep-tracking app", "", 3, "auto")
    assert sink["prompt"] == baseline


def test_winning_hooks_failure_degrades_to_baseline(monkeypatch):
    """ANY error in the fetch degrades to the prior behaviour (no new failure)."""
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))

    def boom(session, user_id, limit=10):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("app.services.hook_performance.winning_hooks", boom)

    result = ideas.generate_ideas(
        "a sleep-tracking app",
        count=3,
        session=_SessionSentinel(),
        user_id="user-123",
    )
    # Same output shape as before; no exception propagated.
    assert result is not None
    baseline = ideas.build_ideas_prompt("a sleep-tracking app", "", 3, "auto")
    assert sink["prompt"] == baseline


def test_user_id_without_session_is_baseline(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))
    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not fetch without a session")
        ),
    )
    result = ideas.generate_ideas("an app", count=3, user_id="u")
    assert result is not None
    assert sink["prompt"] == ideas.build_ideas_prompt("an app", "", 3, "auto")


def test_session_without_user_id_is_baseline(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(ideas, "_generate_response", _capture_prompt_generator(sink))
    monkeypatch.setattr(
        "app.services.hook_performance.winning_hooks",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("must not fetch without a user_id")
        ),
    )
    result = ideas.generate_ideas("an app", count=3, session=_SessionSentinel())
    assert result is not None
    assert sink["prompt"] == ideas.build_ideas_prompt("an app", "", 3, "auto")


# --------------------------------------------------------------------------- #
# _winning_hooks_block unit behaviour (the pure renderer)
# --------------------------------------------------------------------------- #
def test_block_empty_for_no_winners():
    assert ideas._winning_hooks_block([]) == ""


def test_block_skips_blank_and_non_dict_entries():
    block = ideas._winning_hooks_block(
        [{"hook": "   "}, "not-a-dict", {"hook": "real hook", "win_score": 10.0}]
    )
    assert "real hook" in block
    # Only the one usable hook line is rendered.
    assert block.count("- ") == 1


def test_block_all_unusable_returns_empty():
    assert ideas._winning_hooks_block([{"hook": ""}, {"nope": 1}]) == ""


def test_block_tolerates_non_numeric_win_score():
    block = ideas._winning_hooks_block([{"hook": "h", "win_score": "oops"}])
    # Non-numeric score degrades to 0, still renders the hook.
    assert '"h"' in block
