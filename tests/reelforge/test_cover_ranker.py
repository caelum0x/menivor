"""Scroll-stopping Cover Ranker — unit tests.

Exercises :mod:`app.domains.growth.cover_ranker` and its wiring into
:mod:`app.services.cover` with a stub TypeSafe client (no network, no key):

* graceful degradation — with no client / no ``TYPESAFE_API_KEY`` the ranker is a
  pass-through (input order preserved, ``degraded=True``, first candidate
  recommended) and ``cover.recommend_cover_style`` returns the default style;
* live ranking — a stub Jev client makes the highest-composite candidate win and
  drives ``recommended_style``;
* the composite is exactly ``stop + 0.5*legibility - 0.75*generic``;
* the sync bridge returns the same ranking as the async path.
"""

from __future__ import annotations

import asyncio

import pytest

from app.domains.growth import cover_ranker as cr
from app.domains.growth.cover_ranker import (
    CoverCandidate,
    CoverContext,
    rank_covers,
    rank_covers_sync,
)
from app.services import cover


# =========================================================================== #
# Stub TypeSafe client
# =========================================================================== #
class _StubClient:
    """A fake ``TypeSafeClient`` returning canned answers keyed by candidate headline.

    ``by_headline`` maps a candidate headline to ``(stop_score, legibility_score,
    generic_noul, mood, confidence)`` using RAW score indices (0..3) so the ranker
    normalises them exactly as it would a live response.
    """

    def __init__(self, by_headline: dict[str, tuple]) -> None:
        self.by_headline = by_headline
        self.calls = 0

    async def system_one(self, state, questions, *, model=None):
        self.calls += 1
        headline = state["cover"]["headline"]
        stop, legibility, generic, mood, conf = self.by_headline[headline]
        return {
            "answers": {
                "primary_mood": {"choice": mood, "confidence": conf, "probabilities": {mood: conf}},
                "stop_power": {"score": stop},
                "legibility": {"score": legibility},
                "is_generic": {"noul": generic},
            }
        }


def _candidates() -> list[CoverCandidate]:
    return [
        CoverCandidate(id="classic", headline="Classic hook", style_name="Classic"),
        CoverCandidate(id="sunset", headline="Sunset hook", style_name="Sunset"),
        CoverCandidate(id="bold", headline="Bold hook", style_name="Bold Yellow"),
    ]


# =========================================================================== #
# Composite math
# =========================================================================== #
def test_composite_formula() -> None:
    # stop=1.0, legibility=1.0, generic=1.0 -> 1.0 + 0.5 - 0.75 = 0.75
    assert cr._compute_composite(1.0, 1.0, 1.0) == pytest.approx(0.75)
    # stop=1.0, legibility=0.0, generic=0.0 -> 1.0
    assert cr._compute_composite(1.0, 0.0, 0.0) == pytest.approx(1.0)


# =========================================================================== #
# Graceful degradation (no key)
# =========================================================================== #
def test_degrades_without_key(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)

    ranking = asyncio.run(rank_covers(_candidates(), CoverContext()))

    assert ranking.degraded is True
    # Input order preserved, nothing scored, first candidate recommended.
    assert [s.id for s in ranking.ranked] == ["classic", "sunset", "bold"]
    assert all(not s.scored for s in ranking.ranked)
    assert ranking.recommended_style == "classic"


def test_empty_candidates() -> None:
    ranking = asyncio.run(rank_covers([], CoverContext()))
    assert ranking.ranked == []
    assert ranking.winner is None
    assert ranking.degraded is False


# =========================================================================== #
# Live ranking with a stub client
# =========================================================================== #
def test_ranks_highest_composite_first() -> None:
    # Bold: strong stop + legible + not generic -> should win.
    # Classic: mediocre. Sunset: strong stop but flagged generic -> penalised.
    stub = _StubClient(
        {
            "Classic hook": (1, 2, 0.1, "premium_minimal", 0.8),   # 0.333 + 0.5*0.667 - 0.075
            "Sunset hook": (3, 2, 0.9, "bold_energetic", 0.7),     # 1.0 + 0.333 - 0.675
            "Bold hook": (3, 3, 0.05, "bold_energetic", 0.9),      # 1.0 + 0.5 - 0.0375 (best)
        }
    )

    ranking = asyncio.run(rank_covers(_candidates(), CoverContext(), client=stub))

    assert ranking.degraded is False
    assert stub.calls == 3
    assert ranking.winner is not None
    assert ranking.winner.id == "bold"
    assert ranking.recommended_style == "bold"
    # Strictly descending composite.
    composites = [s.composite for s in ranking.ranked]
    assert composites == sorted(composites, reverse=True)
    # Winner carries normalised signals.
    assert ranking.winner.stop_power == pytest.approx(1.0)
    assert ranking.winner.legibility == pytest.approx(1.0)
    assert ranking.winner.is_generic == pytest.approx(0.05)


def test_sync_bridge_matches_async() -> None:
    stub = _StubClient(
        {
            "Classic hook": (1, 1, 0.2, "premium_minimal", 0.8),
            "Sunset hook": (2, 2, 0.1, "warm_emotional", 0.7),
            "Bold hook": (3, 3, 0.0, "bold_energetic", 0.9),
        }
    )
    ranking = rank_covers_sync(_candidates(), CoverContext(), client=stub)
    assert ranking.degraded is False
    assert ranking.recommended_style == "bold"


# =========================================================================== #
# Wiring into cover.recommend_cover_style
# =========================================================================== #
def test_recommend_cover_style_degrades_to_default(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("typesafe_api_key", raising=False)

    style = cover.recommend_cover_style("Şunu izle", has_poster=True)
    assert style == cover.DEFAULT_STYLE_ID
    assert style in cover.COVER_STYLES


def test_recommend_cover_style_picks_winner(monkeypatch) -> None:
    # Force a client whose winner is a real catalog style id other than default.
    winner_id = "sunset"
    assert winner_id in cover.COVER_STYLES

    def _stub_rank(candidates, context, *, client=None):
        # Highest composite for the sunset style.
        return cr.CoverRanking(
            ranked=[],
            winner=cr.CoverSignals(
                id=winner_id,
                primary_mood="warm_emotional",
                mood_confidence=0.9,
                stop_power=1.0,
                legibility=1.0,
                is_generic=0.0,
                composite=1.5,
            ),
            recommended_style=winner_id,
            degraded=False,
        )

    monkeypatch.setattr(cr, "rank_covers_sync", _stub_rank)
    style = cover.recommend_cover_style("A great hook", has_poster=False)
    assert style == winner_id
