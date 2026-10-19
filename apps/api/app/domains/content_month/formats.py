"""Proven short-form formats a month of content is built from.

Each :class:`Format` is a repeatable post shape that keeps working on TikTok,
Reels, Shorts and LinkedIn: a hook pattern, the job of each slide (carousels)
or beat (reels), and why it holds attention. Ideas are always mapped to one of
these, so a plan mixes formats instead of repeating one.

Carousels are photo-mode slideshows (rendered by :mod:`.slides`); reels go
through Menivor's reel pipeline (``POST /jobs``) with the script written here.
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_CAROUSEL = "carousel"
KIND_REEL = "reel"
KINDS = frozenset({KIND_CAROUSEL, KIND_REEL})


@dataclass(frozen=True)
class Format:
    id: str
    kind: str
    name: str
    hook_pattern: str
    #: What each slide (carousel) or beat (reel) does, in order.
    beats: tuple[str, ...]
    why: str


FORMATS: tuple[Format, ...] = (
    # ---- carousels (photo mode slideshows) -------------------------------- #
    Format("pov-problem", KIND_CAROUSEL, "POV problem",
           "POV: you {pain}",
           ("hook: the relatable moment", "the pain, in their words", "what most people try",
            "the turn: a better way", "how the product does it", "call to action"),
           "Viewers see themselves in slide one and swipe to find the fix."),
    Format("mistakes-list", KIND_CAROUSEL, "Mistakes list",
           "{n} mistakes {audience} make with {topic}",
           ("hook: the mistakes promise", "mistake 1 and the fix", "mistake 2 and the fix",
            "mistake 3 and the fix", "call to action"),
           "Loss aversion: nobody wants to be making the mistake."),
    Format("how-to-steps", KIND_CAROUSEL, "How-to steps",
           "How to {outcome} in {n} steps",
           ("hook: the outcome", "step 1", "step 2", "step 3", "call to action"),
           "Saves and shares: people keep step lists for later."),
    Format("myth-fact", KIND_CAROUSEL, "Myth vs fact",
           "Myth: {belief}",
           ("hook: the myth", "why people believe it", "the fact", "proof from the product", "call to action"),
           "Contradiction creates an open loop the viewer wants closed."),
    Format("before-after", KIND_CAROUSEL, "Before and after",
           "Before {product} vs after",
           ("hook: before vs after", "before: the old way", "after: the new way", "what changed",
            "call to action"),
           "A visible change is the fastest proof there is."),
    Format("stop-doing", KIND_CAROUSEL, "Stop doing this",
           "Stop {old_habit}. Do this instead.",
           ("hook: the command", "why the old habit hurts", "do this instead", "how to start today",
            "call to action"),
           "A direct command stops the scroll; the swap gives an easy win."),
    Format("checklist", KIND_CAROUSEL, "Save-this checklist",
           "Save this: the {topic} checklist",
           ("hook: save this", "item 1", "item 2", "item 3", "item 4", "call to action"),
           "Checklists earn saves, which push reach."),
    Format("wish-i-knew", KIND_CAROUSEL, "Things I wish I knew",
           "Things I wish I knew before {milestone}",
           ("hook: the regret", "lesson 1", "lesson 2", "lesson 3", "call to action"),
           "Hindsight framing feels honest and personal."),
    Format("feature-spotlight", KIND_CAROUSEL, "Feature spotlight",
           "This {product_type} does {feature}",
           ("hook: the surprising feature", "the problem it removes", "how it works", "who it is for",
            "call to action"),
           "Shows the product doing one clear thing; easy to understand in seconds."),
    Format("hot-take", KIND_CAROUSEL, "Hot take",
           "Unpopular opinion: {take}",
           ("hook: the opinion", "the reasoning", "what to do about it", "call to action"),
           "Mild controversy drives comments, and comments drive reach."),
    # ---- reels (voiced, captioned, 9:16) ----------------------------------- #
    Format("nobody-tells-you", KIND_REEL, "Nobody tells you",
           "Nobody tells you this about {topic}",
           ("hook", "the hidden truth", "why it matters", "what to do", "call to action"),
           "Insider framing promises information the viewer does not have."),
    Format("three-reasons", KIND_REEL, "Three reasons",
           "{n} reasons {audience} switch to {product}",
           ("hook", "reason 1", "reason 2", "reason 3", "call to action"),
           "A numbered list sets a clear watch-time contract."),
    Format("watch-me", KIND_REEL, "Watch me do it",
           "Watch me {outcome} in under a minute",
           ("hook", "the starting point", "the steps", "the result", "call to action"),
           "Speed demos make the product feel effortless."),
    Format("question-hook", KIND_REEL, "Question hook",
           "Are you still {old_habit}?",
           ("hook question", "the cost of the old way", "the new way", "call to action"),
           "A direct question makes the viewer answer in their head and stay."),
    Format("problem-solution", KIND_REEL, "Problem, then solution",
           "If {pain}, watch this",
           ("hook", "the problem", "the solution", "how to try it", "call to action"),
           "Qualifies the right viewer in the first second."),
)

BY_ID: dict[str, Format] = {f.id: f for f in FORMATS}
CAROUSEL_FORMATS: tuple[Format, ...] = tuple(f for f in FORMATS if f.kind == KIND_CAROUSEL)
REEL_FORMATS: tuple[Format, ...] = tuple(f for f in FORMATS if f.kind == KIND_REEL)

#: Share of a month that is carousels (the rest are reels).
CAROUSEL_SHARE = 0.6


def get(format_id: str) -> Format | None:
    return BY_ID.get(format_id)


def rotation(count: int) -> list[Format]:
    """``count`` formats mixing carousels and reels so no format runs twice in a row."""
    carousels = round(count * CAROUSEL_SHARE)
    reels = count - carousels
    out: list[Format] = []
    ci = ri = 0
    for index in range(count):
        # Every 5 posts: 3 carousels, 2 reels (keeps the feed varied).
        want_reel = index % 5 in (1, 3)
        if (want_reel and ri < reels) or ci >= carousels:
            out.append(REEL_FORMATS[ri % len(REEL_FORMATS)])
            ri += 1
        else:
            out.append(CAROUSEL_FORMATS[ci % len(CAROUSEL_FORMATS)])
            ci += 1
    return out


def catalog() -> list[dict]:
    return [{"id": f.id, "kind": f.kind, "name": f.name, "hook_pattern": f.hook_pattern,
             "beats": list(f.beats), "why": f.why} for f in FORMATS]


__all__ = ["CAROUSEL_FORMATS", "FORMATS", "Format", "KINDS", "KIND_CAROUSEL", "KIND_REEL", "REEL_FORMATS",
           "catalog", "get", "rotation"]
