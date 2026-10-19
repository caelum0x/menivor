"""Onboarding lifecycle mail copy (MR3): Day 0, 1, 3 and 7.

Rules (every template is linted in ``test_we_m5_lifecycle.py``):

* Denylist ``2026-09-29.2`` passes on every subject, line and button.
* No feature behind an off flag: no presenter, lip-sync or publishing copy.
  Everything named here works today (link or topic to three reels, captions
  on your own video, download the MP4).
* Prices come from plan config (``services/billing/plans.py`` for packs,
  ``creator_plans.py`` for the monthly plan, shown only while on sale).
* The Day 7 comparison line is dropped unless a source is attached
  (:data:`DAY7_COMPARISON` stays ``None`` until one is).
* Every email carries the one-click unsubscribe link (MG5's token and
  consent, so one opt-out stops both).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DAY0, DAY1, DAY3, DAY7 = "day0", "day1", "day3", "day7"
STEPS: tuple[str, ...] = (DAY0, DAY1, DAY3, DAY7)
OFFSET_DAYS: dict[str, int] = {DAY0: 0, DAY1: 1, DAY3: 3, DAY7: 7}

REASON = "You received this because you created a Menivor account. You can stop these tips at any time."


@dataclass(frozen=True)
class Comparison:
    """A sourced comparison line for Day 7 (text plus the page it was read from)."""

    text: str
    source_url: str


#: No sourced comparison yet, so Day 7 carries none.
DAY7_COMPARISON: Comparison | None = None


def _money(usd: float) -> str:
    return f"${usd:.0f}" if float(usd).is_integer() else f"${usd:.2f}"


#: Lines built from plan config carry this source (CLAIMS-RULES 4.4 copy-source).
PLAN_COPY_SOURCE = "copy-source: services/billing/plans.py, services/billing/creator_plans.py"


def plan_lines() -> list[str]:
    """Pack and monthly-plan lines read from plan config (see :data:`PLAN_COPY_SOURCE`)."""
    from app.services.billing import creator_plans
    from app.services.billing.plans import list_plans as list_packs

    lines: list[str] = []
    packs = sorted(list_packs(purchasable_only=True), key=lambda p: p.price_usd)
    if packs:
        pack = packs[0]
        name = pack.display_name if "pack" in pack.display_name.lower() else f"{pack.display_name} pack"
        lines.append(
            f"The {name} is {pack.credits} reels for {_money(pack.price_usd)}, one time. "
            "Pack credits never expire."
        )
    on_sale = [row for row in creator_plans.catalog() if row["available"].get("month")]
    if on_sale:
        row = min(on_sale, key=lambda r: r["monthly_cents"])
        lines.append(
            f"The {row['name']} plan is {row['monthly_reels']} reels a month for "
            f"{_money(row['monthly_cents'] / 100)}, and you can cancel at any time."
        )
    return lines


def content(step: str, *, web_url: str, unsubscribe_url: str, comparison: Comparison | None = None) -> Any:
    """The :class:`EmailContent` for ``step``."""
    from app.services.email_templates import EmailAction, EmailContent

    create = f"{web_url}/create"
    if step == DAY0:
        return EmailContent(
            subject="Your first reel starts with one link",
            preheader="Paste a link or type a topic. Three reels come back.",
            title="Make your first reel",
            paragraphs=(
                "Paste a link to your product, your store or an article, or type a topic.",
                "Menivor writes a hook-first script, adds an AI voiceover and word-by-word "
                "captions, and renders three versions with different opening hooks.",
            ),
            action=EmailAction("Make my first reel", create),
            reason=REASON,
            unsubscribe_url=unsubscribe_url,
        )
    if step == DAY1:
        return EmailContent(
            subject="Pick the hook that sounds like you",
            preheader="Every run gives you three openings to choose from.",
            title="Three openings, one run",
            paragraphs=(
                "Each run gives you three versions of the same reel, each with a different "
                "opening line.",
                "Keep the one that sounds like you, or post one each day and see which one "
                "people watch to the end.",
            ),
            action=EmailAction("Make my next reels", create),
            reason=REASON,
            unsubscribe_url=unsubscribe_url,
        )
    if step == DAY3:
        return EmailContent(
            subject="Captions for a video you already have",
            preheader="Upload your own clip and get word-by-word captions.",
            title="Caption your own video",
            paragraphs=(
                "Already recorded something? Upload it and Menivor adds word-by-word captions "
                "in English or Turkish, ready for a vertical feed.",
                "You download the finished MP4 and post it wherever you like.",
            ),
            action=EmailAction("Add captions", create),
            reason=REASON,
            unsubscribe_url=unsubscribe_url,
        )
    if step == DAY7:
        paragraphs = [
            "Your free reels are a start. When you want more, pick what fits how often you post.",
            *plan_lines(),
            "A render that fails gives its credit back.",
        ]
        if comparison is not None and comparison.source_url.startswith("https://"):
            paragraphs.append(f"{comparison.text} (source: {comparison.source_url})")
        return EmailContent(
            subject="Keep making reels",
            preheader="One-time packs or a monthly plan.",
            title="Keep making reels",
            paragraphs=tuple(paragraphs),
            action=EmailAction("See plans and packs", f"{web_url}/pricing"),
            reason=REASON,
            unsubscribe_url=unsubscribe_url,
        )
    raise ValueError(f"unknown onboarding step {step!r}")
