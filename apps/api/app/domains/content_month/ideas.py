"""A month of post ideas for one website: LLM first, deterministic rules as the floor.

:func:`month_ideas` assigns a format to every slot (:func:`formats.rotation`),
asks the LLM (Menivor's chain: Relay first, then free fallbacks) for the slots
in parallel batches, validates every answer and fills any slot the LLM missed
or got wrong with :func:`rules.rule_idea`. It never raises and always returns
about ``count`` ideas (duplicate hooks are dropped).

Validation (per idea): known format, hook and slides present and short, no
emoji, and no number that the website does not state (small list counts up to
10 are allowed so "3 mistakes" works).
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any, Callable

from loguru import logger

from app.domains.content_month import formats as fm
from app.domains.content_month.brief import SiteBrief, clean, numbers_in
from app.domains.content_month.rules import HOOK_MAX, SLIDE_MAX, hashtags, rule_idea, script_from

DEFAULT_COUNT = 30
MAX_COUNT = 40
BATCH = 5
LLM_TIMEOUT_S = 50.0  # whole plan stays well under the ~100 s edge request limit
MIN_SLIDES = 3
MAX_SLIDES = 8
SCRIPT_MAX = 900
CAPTION_MAX = 300
LIST_COUNTS = frozenset(str(n) for n in range(1, 11))

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")

Generate = Callable[[str], str]


def _default_generate(prompt: str) -> str:
    from app.services.llm import _generate_response

    return _generate_response(prompt)


def build_prompt(brief: SiteBrief, slots: list[fm.Format]) -> str:
    wanted = [{"slot": i, "format": f.id, "kind": f.kind, "hook_pattern": f.hook_pattern, "beats": list(f.beats)}
              for i, f in enumerate(slots)]
    return (
        "You plan short-form social posts for a brand, using proven viral formats.\n"
        f"Brand facts (JSON, the only facts you may use): {json.dumps(brief.facts(), ensure_ascii=False)}\n"
        f"Audience: {brief.audience}. Their typical pain: {brief.pain}.\n"
        f"Write one post per slot (JSON): {json.dumps(wanted, ensure_ascii=False)}\n"
        "Rules:\n"
        "- Follow the slot's hook pattern and beats. The hook stops the scroll in under 2 seconds.\n"
        "- Carousel: 4 to 7 slides; slide 1 is the hook, the last slide is a call to action naming the website.\n"
        "- Reel: 4 to 6 beats (one spoken sentence each); slide 1 is the hook, the last beat is the call to action.\n"
        "- Plain words a 12 year old understands. Max 16 words per slide.\n"
        "- Never invent numbers, prices, ratings, user counts, testimonials or results. Use only numbers in the facts.\n"
        "- Never name other companies or competitors. No emoji. No hashtags inside slides.\n"
        "- Every post must be different: vary the angle, the pain and the product point.\n"
        'Reply with JSON only: {"posts": [{"slot": 0, "hook": "...", "slides": ["..."], '
        '"caption": "one or two sentences plus up to 4 hashtags"}]}'
    )


def parse_posts(raw: str) -> list[dict]:
    """Post objects from the reply; complete posts are kept even when the JSON was cut off."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        posts = data.get("posts") if isinstance(data, dict) else None
        if isinstance(posts, list):
            return [p for p in posts if isinstance(p, dict)]
    except (ValueError, TypeError):
        pass
    return _salvage(text)


def _salvage(text: str) -> list[dict]:
    """Decode each complete ``{...}`` inside the ``posts`` array of a truncated reply."""
    anchor = text.find('"posts"')
    pos = text.find("[", anchor) + 1 if anchor >= 0 else 0
    if pos <= 0:
        return []
    decoder = json.JSONDecoder()
    out: list[dict] = []
    while True:
        pos = text.find("{", pos)
        if pos < 0:
            return out
        try:
            obj, pos = decoder.raw_decode(text, pos)
        except ValueError:
            return out
        if isinstance(obj, dict):
            out.append(obj)


_MARKDOWN_RE = re.compile(r"[`*_#]+")


def _ok_text(value: Any, limit: int, allowed: set[str]) -> str:
    # Slides are plain type: markdown marks (`code`, **bold**) would render literally.
    text = " ".join(_MARKDOWN_RE.sub("", _EMOJI_RE.sub("", clean(value, limit))).split())
    if not text or not numbers_in(text) <= allowed:
        return ""
    return text


def validate(post: dict, fmt: fm.Format, brief: SiteBrief) -> dict | None:
    """A clean idea dict, or ``None`` when the LLM answer cannot be used."""
    allowed = set(brief.allowed_numbers) | LIST_COUNTS
    hook = _ok_text(post.get("hook"), HOOK_MAX, allowed)
    raw_slides = post.get("slides") if isinstance(post.get("slides"), list) else []
    # A slide with an invented figure is dropped; the post survives if enough remain.
    slides = [s for s in (_ok_text(x, SLIDE_MAX, allowed) for x in raw_slides[:MAX_SLIDES]) if s]
    if not hook or len(slides) < MIN_SLIDES:
        return None
    if slides[0].lower().rstrip(".!?") != hook.lower().rstrip(".!?"):
        slides = [hook, *slides][:MAX_SLIDES]
    caption = " ".join(_EMOJI_RE.sub("", clean(post.get("caption"), CAPTION_MAX)).split())
    if not caption or not numbers_in(caption) <= allowed:
        caption = clean(f"{hook}. {brief.domain} {hashtags(brief)}", CAPTION_MAX)
    return {
        "format": fmt.id, "kind": fmt.kind, "hook": hook, "slides": slides,
        "script": clean(script_from(slides), SCRIPT_MAX) if fmt.kind == fm.KIND_REEL else "",
        "caption": caption, "source": "llm",
    }


def _batch(brief: SiteBrief, slots: list[fm.Format], generate: Generate) -> dict[int, dict]:
    raw = generate(build_prompt(brief, slots))
    if not isinstance(raw, str) or raw.startswith("Error: "):
        logger.warning(f"content month: LLM batch failed: {str(raw)[:200]}")
        return {}
    posts = parse_posts(raw)
    out: dict[int, dict] = {}
    for post in posts:
        try:
            slot = int(post.get("slot"))
        except (TypeError, ValueError):
            continue
        if 0 <= slot < len(slots) and slot not in out:
            idea = validate(post, slots[slot], brief)
            if idea is not None:
                out[slot] = idea
    logger.info(f"content month: LLM batch {len(raw)} chars, {len(posts)} posts, {len(out)}/{len(slots)} kept")
    return out


def _llm_slots(brief: SiteBrief, slots: list[fm.Format], generate: Generate, timeout_s: float) -> dict[int, dict]:
    batches = [list(range(i, min(i + BATCH, len(slots)))) for i in range(0, len(slots), BATCH)]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(batches)))
    futures = {pool.submit(_batch, brief, [slots[i] for i in idx], generate): idx for idx in batches}
    out: dict[int, dict] = {}
    try:
        for future in concurrent.futures.as_completed(futures, timeout=timeout_s):
            idx = futures[future]
            try:
                for local, idea in future.result().items():
                    out[idx[local]] = idea
            except Exception:  # noqa: BLE001 - one failed batch falls back to rules
                continue
    except concurrent.futures.TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return out


def _dedupe_hooks(ideas: list[dict], slots: list[fm.Format], brief: SiteBrief) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for index, idea in enumerate(ideas):
        key = idea["hook"].lower()
        if key in seen:
            idea = rule_idea(slots[index], brief, index + 7)
            key = idea["hook"].lower()
            if key in seen:
                continue
        seen.add(key)
        out.append(idea)
    return out


def month_ideas(brief: SiteBrief, *, count: int = DEFAULT_COUNT, use_llm: bool = True,
                generate: Generate | None = None, timeout_s: float = LLM_TIMEOUT_S) -> list[dict]:
    """About ``count`` validated ideas (LLM where it answered well, rules elsewhere). Never raises."""
    count = max(1, min(int(count or DEFAULT_COUNT), MAX_COUNT))
    slots = fm.rotation(count)
    llm = _llm_slots(brief, slots, generate or _default_generate, timeout_s) if use_llm else {}
    variants: dict[str, int] = {}
    ideas: list[dict] = []
    for index, fmt in enumerate(slots):
        variant = variants.get(fmt.id, 0)
        variants[fmt.id] = variant + 1
        ideas.append(llm.get(index) or rule_idea(fmt, brief, variant))
    return _dedupe_hooks(ideas, slots, brief)


__all__ = ["DEFAULT_COUNT", "Generate", "MAX_COUNT", "SCRIPT_MAX", "build_prompt", "month_ideas", "parse_posts",
           "validate"]
