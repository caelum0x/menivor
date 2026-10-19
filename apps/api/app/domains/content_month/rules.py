"""Deterministic post ideas from a :class:`SiteBrief` (no LLM needed).

Every format gets a builder that fills its hook and slides from what the site
says (one-liner, value lines, features, pricing) plus the category angle in
:mod:`.brief`. Builders take a ``variant`` so the second use of a format in a
month picks different lines. Nothing here states a number the site did not
publish, except small list counts that match the number of slides.
"""

from __future__ import annotations

from typing import Callable

from app.domains.content_month.brief import SiteBrief, clean
from app.domains.content_month.formats import KIND_REEL, Format

HOOK_MAX = 90
SLIDE_MAX = 150


def _pick(items: tuple[str, ...], index: int, fallback: str) -> str:
    return items[index % len(items)] if items else fallback


def _points(b: SiteBrief, variant: int, count: int) -> list[str]:
    """``count`` distinct product points (features first, then value lines)."""
    pool = [*b.features, *b.value_lines[1:], b.one_liner]
    pool = [p for p in dict.fromkeys(p for p in pool if p)]
    if not pool:
        pool = [b.one_liner or b.name]
    start = (variant * count) % len(pool)
    ordered = pool[start:] + pool[:start]
    out = [ordered[i % len(ordered)] for i in range(count)]
    return [clean(p.rstrip("."), SLIDE_MAX) for p in out]


def _cta(b: SiteBrief, variant: int) -> str:
    options = (f"Try {b.name} at {b.domain}", f"See it at {b.domain}", f"Start at {b.domain}")
    if b.pricing_hook and variant % 2:
        return clean(f"{b.pricing_hook}. {b.domain}", SLIDE_MAX)
    return options[variant % len(options)]


def _line(b: SiteBrief, variant: int) -> str:
    return clean(_pick(b.value_lines, variant, b.one_liner).rstrip("."), SLIDE_MAX)


def pov_problem(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"POV: you {b.pain}"
    return hook, [hook, f"Every week it is the same story: {b.old_habit}.",
                  f"Most {b.audience} just push through it.", "There is a simpler way.",
                  b.one_liner or _line(b, v), _cta(b, v)]


def mistakes_list(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"3 mistakes {b.audience} make with {b.topic}"
    fixes = _points(b, v, 3)
    mistakes = (b.old_habit.capitalize(), "Doing it all yourself", "Waiting until it is perfect")
    return hook, [hook, *[f"{m}. Fix: {f}" for m, f in zip(mistakes, fixes)], _cta(b, v)]


def how_to_steps(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"How to {b.outcome} in 3 steps"
    steps = [s for s in b.value_lines if s[:2].rstrip(".").isdigit()][:3] or _points(b, v, 3)
    steps = [s if s[:1].isdigit() else f"{i}. {s}" for i, s in enumerate(steps, 1)]
    return hook, [hook, *steps, _cta(b, v)]


def myth_fact(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Myth: {b.topic} has to be slow and hard"
    return hook, [hook, f"It feels true when you are {b.old_habit}.", f"Fact: {b.one_liner or _line(b, v)}",
                  *_points(b, v, 1), _cta(b, v)]


def before_after(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Before {b.name} vs after"
    return hook, [hook, f"Before: {b.old_habit}.", f"After: {_line(b, v)}",
                  f"What changed: {_points(b, v + 1, 1)[0]}", _cta(b, v)]


def stop_doing(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Stop {b.old_habit}. Do this instead."
    return hook, [hook, f"It costs {b.audience} hours every week.", f"Do this instead: {_line(b, v)}",
                  f"Start today: {_points(b, v, 1)[0]}", _cta(b, v)]


def checklist(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Save this: the {b.topic} checklist"
    items = _points(b, v, 4)
    return hook, [hook, *[f"[ ] {i}" for i in items], _cta(b, v)]


def wish_i_knew(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"What {b.audience} wish they knew about {b.topic}"
    lessons = _points(b, v, 3)
    return hook, [hook, *[f"Lesson {i}: {x}" for i, x in enumerate(lessons, 1)], _cta(b, v)]


def feature_spotlight(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    feature = _points(b, v, 1)[0]
    hook = clean(f"{b.name} does this: {feature}", HOOK_MAX)
    return hook, [hook, f"No more {b.old_habit}.", _line(b, v + 1), f"Made for {b.audience}.", _cta(b, v)]


def hot_take(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Unpopular opinion: {b.old_habit} is wasting your week"
    return hook, [hook, f"{b.audience.capitalize()} have better things to do.",
                  f"What to do instead: {_line(b, v)}", _cta(b, v)]


def nobody_tells_you(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Nobody tells you this about {b.topic}"
    return hook, [hook, f"Most {b.audience} {b.pain}.", f"The fix is simple: {_line(b, v)}",
                  _points(b, v, 1)[0], _cta(b, v)]


def three_reasons(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"3 reasons {b.audience} use {b.name}"
    reasons = _points(b, v, 3)
    return hook, [hook, *[f"Reason {i}: {r}" for i, r in enumerate(reasons, 1)], _cta(b, v)]


def watch_me(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Watch me {b.outcome} with {b.name}"
    return hook, [hook, f"Usually this means {b.old_habit}.", _line(b, v), _points(b, v, 1)[0], _cta(b, v)]


def question_hook(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"Are you still {b.old_habit}?"
    return hook, [hook, f"That is how {b.audience} {b.pain}.", f"The new way: {_line(b, v)}", _cta(b, v)]


def problem_solution(b: SiteBrief, v: int) -> tuple[str, list[str]]:
    hook = f"If you {b.pain}, watch this"
    return hook, [hook, f"The problem: {b.old_habit}.", f"The solution: {b.one_liner or _line(b, v)}",
                  _points(b, v, 1)[0], _cta(b, v)]


BUILDERS: dict[str, Callable[[SiteBrief, int], tuple[str, list[str]]]] = {
    "pov-problem": pov_problem, "mistakes-list": mistakes_list, "how-to-steps": how_to_steps,
    "myth-fact": myth_fact, "before-after": before_after, "stop-doing": stop_doing, "checklist": checklist,
    "wish-i-knew": wish_i_knew, "feature-spotlight": feature_spotlight, "hot-take": hot_take,
    "nobody-tells-you": nobody_tells_you, "three-reasons": three_reasons, "watch-me": watch_me,
    "question-hook": question_hook, "problem-solution": problem_solution,
}


def hashtags(b: SiteBrief) -> str:
    words = [w for w in f"{b.topic} {b.audience}".replace(",", " ").split() if w.isalpha() and len(w) > 3]
    tags = list(dict.fromkeys(["#" + w.lower() for w in words]))[:3]
    tags.append("#" + "".join(ch for ch in b.name.lower() if ch.isalnum()))
    return " ".join(t for t in tags if len(t) > 1)


def script_from(slides: list[str]) -> str:
    """Voiceover for a reel: the beats read in order."""
    return " ".join(s.rstrip(".?!") + ("?" if s.rstrip().endswith("?") else ".") for s in slides if s)


#: Second-and-later hooks per format, so a month never repeats a hook.
ALT_HOOKS: dict[str, tuple[Callable[[SiteBrief], str], ...]] = {
    "pov-problem": (lambda b: f"POV: it is Friday and you are still {b.old_habit}",
                    lambda b: f"POV: you found {b.name}"),
    "mistakes-list": (lambda b: f"3 {b.topic} mistakes I see every week",
                      lambda b: f"You are probably making these {b.topic} mistakes"),
    "how-to-steps": (lambda b: f"The 3-step way to {b.outcome}",
                     lambda b: f"How {b.audience} {b.outcome} without the busywork"),
    "myth-fact": (lambda b: f"Myth: you need a big team to {b.outcome}",
                  lambda b: f"Myth vs fact: {b.topic}"),
    "before-after": (lambda b: f"{b.topic.capitalize()}: the old way vs the new way",
                     lambda b: f"What changes when you stop {b.old_habit}"),
    "stop-doing": (lambda b: f"Please stop {b.old_habit}",
                   lambda b: f"{b.audience.capitalize()}, stop doing this"),
    "checklist": (lambda b: f"Your {b.topic} checklist for this week",
                  lambda b: f"Bookmark this before you {b.outcome}"),
    "wish-i-knew": (lambda b: f"I wish someone told me this about {b.topic}",
                    lambda b: f"{b.topic.capitalize()} lessons nobody teaches"),
    "feature-spotlight": (lambda b: f"The {b.name} feature {b.audience} keep asking about",
                          lambda b: f"One thing {b.name} does that saves your week"),
    "hot-take": (lambda b: f"Hot take: {b.topic} should take minutes, not days",
                 lambda b: f"Controversial: most {b.audience} overcomplicate {b.topic}"),
    "nobody-tells-you": (lambda b: f"The {b.topic} secret nobody shares",
                         lambda b: f"What I learned about {b.topic} the hard way"),
    "three-reasons": (lambda b: f"Why {b.audience} are switching to {b.name}",
                      lambda b: f"3 reasons to stop {b.old_habit}"),
    "watch-me": (lambda b: f"Watch how fast this is with {b.name}",
                 lambda b: f"Real time: {b.outcome} with {b.name}"),
    "question-hook": (lambda b: f"Do you {b.pain}?",
                      lambda b: f"Why are {b.audience} still {b.old_habit}?"),
    "problem-solution": (lambda b: f"{b.audience.capitalize()}: this fixes {b.topic}",
                         lambda b: f"The fix for {b.audience} who {b.pain}"),
}


def rule_idea(fmt: Format, b: SiteBrief, variant: int) -> dict:
    hook, slides = BUILDERS[fmt.id](b, variant)
    alts = ALT_HOOKS.get(fmt.id, ())
    if variant > 0 and alts:
        hook = alts[(variant - 1) % len(alts)](b)
    hook = clean(hook, HOOK_MAX)
    slides = [clean(s, SLIDE_MAX) for s in slides if s]
    slides[0] = hook
    caption = clean(f"{hook}. {b.one_liner} {b.domain} {hashtags(b)}", 300)
    return {
        "format": fmt.id, "kind": fmt.kind, "hook": hook, "slides": slides,
        "script": script_from(slides) if fmt.kind == KIND_REEL else "",
        "caption": caption, "source": "rules",
    }


__all__ = ["BUILDERS", "hashtags", "rule_idea", "script_from"]
