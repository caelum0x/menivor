"""Newly written lines for a clone: an LLM writer (Relay credits) with a deterministic fallback bank.

Lines are written FOR our brand from the hook pattern and beat roles. The source's words are
never given to the fallback bank, and the LLM is told not to reuse them; ipguard checks both.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

MAX_LINE_CHARS = 90
VARIATIONS = ("a", "b", "c")


@dataclass(frozen=True)
class Slot:
    index: int  # story beat index in the brief
    role: str
    framing: str  # close | wide
    seconds: float


@dataclass(frozen=True)
class Line:
    slot: int
    speaker: str
    text: str


# Each bank: hook (H), setups (H), reaction (O, deadpan), turn (H). Everyday Turkish life, affectionate.
_BANK: dict[str, dict[str, dict[str, object]]] = {
    "price_shock": {
        "a": {"hook": "Simit is twenty-five lira now.",
              "setups": ["Tea went up again. Twice this month.", "The bakkal writes the prices in pencil now.",
                         "He said it's temporary, abi.", "My cousin pays for bread in instalments."],
              "reaction": "He said that last year.", "turn": "So I buy one thing that never goes up.", "after": ["Forty pieces. Numbered. Mine is twelve."]},
        "b": {"hook": "One glass of tea. Fifteen lira.",
              "setups": ["The dolmuş driver wants exact change and a reason.", "Parking is a monthly subscription now.",
                         "My mother asked me to split the electricity.", "Even the pigeons look worried."],
              "reaction": "The pigeons are fine.", "turn": "So I put my money somewhere safe. On my chest.", "after": ["Forty numbered pieces. Then it is gone."]},
        "c": {"hook": "Lahmacun costs more than my haircut.",
              "setups": ["My barber now accepts gold.", "The neighbour sold his car to buy tomatoes.",
                         "Rent went up while I was reading the message.", "I said I'll think about it. He said think faster."],
              "reaction": "He's not wrong.", "turn": "Some things only happen once.", "after": ["Forty pieces. Each one numbered."]},
    },
    "question": {
        "a": {"hook": "Why does every Turkish uncle own the same jacket?",
              "setups": ["Nobody knows where they buy it.", "Nobody has ever seen the shop."],
              "reaction": "There is no shop.", "turn": "So we made our own.", "after": ["Forty of them. Numbered."]},
        "b": {"hook": "Have you ever been offered tea at a car crash?",
              "setups": ["Both drivers. Same thermos.", "Then they argued for an hour. Politely."],
              "reaction": "Good tea, though.", "turn": "That is the energy we put on a shirt.", "after": ["Forty pieces. Numbered."]},
        "c": {"hook": "What do you call a Turk who is on time?",
              "setups": ["Early.", "He has been waiting since yesterday."],
              "reaction": "He brought simit.", "turn": "Dress for the very Turkish moments.", "after": ["Forty pieces. Numbered."]},
    },
}
_GENERIC = {
    "a": {"hook": "Nobody warned me about Turkish breakfast.",
          "setups": ["Thirty plates. One table. Four hours.", "Then lunch was at noon.", "My aunt said I look thin."],
          "reaction": "You do look thin.", "turn": "So I dressed for it.", "after": ["Forty pieces. Numbered."]},
    "b": {"hook": "This is my third tea and it is nine a.m.",
          "setups": ["The fourth one is already brewing.", "Saying no is not an option here."],
          "reaction": "It never was.", "turn": "Some days are just very Turkish.", "after": ["Forty pieces. Numbered."]},
    "c": {"hook": "My grandmother can find you anywhere.",
          "setups": ["She called the bakkal. He saw me.", "Then the bakkal's cousin saw me."],
          "reaction": "She already knows.", "turn": "If you can't hide, dress well.", "after": ["Forty pieces. Numbered."]},
}


def bank(pattern: str, variation: str) -> dict[str, object]:
    return (_BANK.get(pattern) or {}).get(variation) or _GENERIC[variation]


@dataclass(frozen=True)
class BriefContext:
    """What the template writer knows about THIS link (see :mod:`storyline`)."""

    topic: str = "everyday"
    pattern: str = "statement"
    seed: int = 0
    avoid_terms: tuple[str, ...] = ()
    source_texts: tuple[str, ...] = ()


def _rotated(items: list[str], by: int) -> list[str]:
    if not items:
        return []
    k = by % len(items)
    return items[k:] + items[:k]


def _pool(topic: str, field: str, by: int) -> list[str]:
    """The topic's lines first (rotated per link/variation), then everyday ones, then the other topics."""
    from .topicbank import TOPICS

    order = [topic, "everyday", *sorted(t for t in TOPICS if t not in (topic, "everyday"))]
    out: list[str] = []
    for i, name in enumerate(order):
        lines = list(TOPICS.get(name, TOPICS["everyday"]).get(field) or [])  # type: ignore[union-attr]
        out.extend(_rotated(lines, by if i == 0 else 0))
    return out


def _hook_pool(ctx: BriefContext) -> list[str]:
    from .topicbank import PATTERN_HOOK, TOPICS

    kind = PATTERN_HOOK.get(ctx.pattern, "claim")
    topic = TOPICS.get(ctx.topic, TOPICS["everyday"])
    own = list(topic["hooks"].get(kind) or [])  # type: ignore[union-attr]
    same_kind = _rotated(own, ctx.seed) + list(TOPICS["everyday"]["hooks"].get(kind) or [])  # type: ignore[union-attr]
    others = [h for k, hooks in topic["hooks"].items() if k != kind for h in hooks]  # type: ignore[union-attr]
    return same_kind + others


class _Picker:
    """Hands out lines from pools, never the same line twice, never a banned or copied one."""

    def __init__(self, ctx: BriefContext) -> None:
        self.ctx = ctx
        self.used: set[str] = set()

    def ok(self, text: str) -> bool:
        from . import ipguard

        key = " ".join(text.lower().split())
        if key in self.used:
            return False
        if any(ipguard._term_hit(text, t) for t in self.ctx.avoid_terms if t):
            return False
        return not (self.ctx.source_texts and ipguard.copied_lines([text], self.ctx.source_texts))

    def take(self, *pools: list[str]) -> str:
        for pool in pools:
            for text in pool:
                if self.ok(text):
                    self.used.add(" ".join(text.lower().split()))
                    return text
        n = len(self.used) + 1
        while True:  # every pool is spent: a numbered beat line is still new wording
            text = f"And that was only moment number {n}."
            if self.ok(text):
                self.used.add(text.lower())
                return text
            n += 1


def _context_lines(slots: list[Slot], variation: str, ctx: BriefContext) -> list[Line]:
    vi = VARIATIONS.index(variation)
    by = ctx.seed + vi * 3
    pick = _Picker(ctx)
    b = bank(ctx.pattern, variation)
    setups, after = _pool(ctx.topic, "setups", by), _pool(ctx.topic, "after", by)
    reactions, turns = _pool(ctx.topic, "reactions", by), _pool(ctx.topic, "turns", by)
    spare = [*setups, *[str(x) for x in b["setups"]]]  # type: ignore[union-attr]
    n = len(slots)
    turn = next((i for i, s in enumerate(slots) if s.role == "turn" and i > 0), n - 1 if n >= 3 else None)
    out: list[Line] = []
    for i, slot in enumerate(slots):
        if i == 0:
            usable = [h for h in _hook_pool(ctx) if pick.ok(h)]  # variations differ even after filtering
            out.append(Line(slot.index, "H", pick.take(usable[vi:] + usable[:vi], spare)))
        elif turn is not None and i == turn:
            out.append(Line(slot.index, "H", pick.take(turns, spare)))
        elif turn is not None and i == turn - 1 and n >= 4:
            out.append(Line(slot.index, "O", pick.take(reactions, spare)))
        elif turn is not None and i > turn:
            out.append(Line(slot.index, "H", pick.take(after, spare)))
        else:
            out.append(Line(slot.index, "H", pick.take(setups, spare)))
    return out


def fallback_lines(slots: list[Slot], pattern: str, variation: str,
                   context: BriefContext | None = None) -> list[Line]:
    """One new line per story slot, following the source's beat roles; no line repeats in a plan.

    hook -> our hook; the beat before the turn (the source's exasperation) -> OXHAN's deadpan
    reaction; turn -> our turn; beats after the turn -> "after" lines; the rest -> setups in order.
    With a :class:`BriefContext` the lines come from the link's own topic and hook device
    (:mod:`topicbank`), so different links get different stories.
    """
    if not slots:
        return []
    if context is not None:
        return _context_lines(slots, variation, context)
    b = bank(pattern, variation)
    n = len(slots)
    turn = next((i for i, s in enumerate(slots) if s.role == "turn" and i > 0), n - 1 if n >= 3 else None)
    pick = _Picker(BriefContext(pattern=pattern))
    setups = [str(x) for x in b["setups"]]  # type: ignore[union-attr]
    after = [str(x) for x in (b.get("after") or [])]  # type: ignore[union-attr]
    spare = _pool("everyday", "setups", 0)
    out: list[Line] = []
    for i, slot in enumerate(slots):
        if i == 0:
            out.append(Line(slot.index, "H", pick.take([str(b["hook"])], spare)))
        elif turn is not None and i == turn:
            out.append(Line(slot.index, "H", pick.take([str(b["turn"])], spare)))
        elif turn is not None and i == turn - 1 and n >= 4:
            out.append(Line(slot.index, "O", pick.take([str(b["reaction"])], spare)))
        elif turn is not None and i > turn and after:
            out.append(Line(slot.index, "H", pick.take(after, setups, spare)))
        else:
            out.append(Line(slot.index, "H", pick.take(setups, spare)))
    return out


def writer_prompt(slots: list[Slot], *, pattern: str, hook_summary: str, preset: dict, variation: str,
                  language: str, avoid_text: str, avoid_terms: tuple[str, ...] = (), premise: str = "") -> str:
    chars = {k: {"name": c["name"], "persona": c.get("persona", "")} for k, c in preset["characters"].items()}
    rows = [{"slot": s.index, "role": s.role, "framing": s.framing, "seconds": round(s.seconds, 1)} for s in slots]
    return (
        f"Write ORIGINAL lines for a short vertical ad for {preset['brand_name']} ({preset['product']}).\n"
        f"Copy only the STRUCTURE of a winning ad: hook pattern '{pattern}' ({hook_summary}), one line per slot: "
        f"{json.dumps(rows)}.\nCharacters: {json.dumps(chars)}. HERO (H) carries most lines; OXHAN (O) gets at most "
        f"one flat deadpan line; N at most one.\nRules: every line is new wording; never reuse any 3+ word phrase "
        f"from this source text: {avoid_text[:800]!r}; never name these source brands/accounts: "
        f"{', '.join(avoid_terms[:40]) or 'none'}; no real people, brands or slurs; affectionate everyday "
        f"Turkish life, no flags, sultans or costumes; each line <= {MAX_LINE_CHARS} characters and speakable in "
        f"the slot's seconds; do NOT write the closing line (it is fixed: {preset['cta']['text']!r}). "
        f"Language: {language}. Story premise for this ad: {premise or 'from the hook'}. "
        f"Variation '{variation}': take a different angle from the other variations.\n"
        "Reply with JSON only: {\"lines\": [{\"slot\": int, \"speaker\": \"H\"|\"O\"|\"N\", \"text\": str}]}"
    )


def llm_lines(slots: list[Slot], llm: Callable[[str], str], **kwargs) -> list[Line] | None:
    """Validated LLM lines, or None (caller falls back to the bank)."""
    try:
        text = llm(writer_prompt(slots, **kwargs))
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        rows = data["lines"]
    except Exception:  # noqa: BLE001 - optional step
        return None
    allowed = set(kwargs["preset"]["characters"])
    by_slot = {s.index for s in slots}
    out = []
    for row in rows if isinstance(rows, list) else []:
        text_ = " ".join(str(row.get("text") or "").split())
        if row.get("slot") in by_slot and row.get("speaker") in allowed and 0 < len(text_) <= MAX_LINE_CHARS:
            out.append(Line(int(row["slot"]), str(row["speaker"]), text_))
    if [ln.slot for ln in out] != [s.index for s in slots]:
        return None
    return out
