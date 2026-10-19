"""Deterministic labels for inbound comments and DMs (the autopilot's rules input).

Labels, checked in this order (the first that matches wins):

* ``spam``          - promo links, "check my profile", follow-for-follow, crypto
                      or giveaway bait, the creator's own blocked words.
* ``abuse``         - insults, slurs, threats aimed at the creator or others.
* ``buying_intent`` - asks about price, availability, ordering, shipping, links
                      to buy, bulk or wholesale.
* ``negative``      - complaints (refunds, broken, scam claims).
* ``question``      - anything else phrased as a question.
* ``positive``      - praise and thanks.
* ``neutral``       - everything else.

Confidence is a plain measure of how many independent signals matched, so the
UI can say "matched: price, link" instead of an invented probability. Word
matching is on whole words; the comment text is never executed or trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPAM = "spam"
ABUSE = "abuse"
BUYING_INTENT = "buying_intent"
NEGATIVE = "negative"
QUESTION = "question"
POSITIVE = "positive"
NEUTRAL = "neutral"
LABELS = (SPAM, ABUSE, BUYING_INTENT, NEGATIVE, QUESTION, POSITIVE, NEUTRAL)

_URL = re.compile(r"(https?://|www\.|\b[\w-]+\.(?:com|net|io|xyz|ru|top|link|shop|site|biz|info)\b)", re.I)
_HANDLE_PROMO = re.compile(r"@\w{3,}")
_REPEAT = re.compile(r"(.)\1{7,}")

_SPAM_PHRASES = (
    "check my profile", "check out my profile", "check my page", "visit my page", "link in my bio",
    "link in bio", "follow for follow", "f4f", "follow back", "sub4sub", "sub for sub", "dm me for",
    "dm for promo", "promote your", "promotion for", "free followers", "get followers", "buy followers",
    "crypto", "bitcoin", "forex", "investment opportunity", "earn money", "make money from home",
    "giveaway winner", "you have been selected", "claim your prize", "whatsapp me", "telegram me",
    "onlyfans", "hot singles", "click the link", "cash app", "binary options",
)
_ABUSE_WORDS = (
    "idiot", "stupid", "moron", "dumb", "loser", "trash", "garbage", "pathetic", "ugly", "disgusting",
    "shut up", "kill yourself", "kys", "hate you", "go to hell", "worthless", "retard", "clown",
    "fuck you", "f*** you", "screw you", "bitch", "bastard", "asshole",
)
_BUY_WORDS = (
    "price", "prices", "pricing", "cost", "costs", "how much", "buy", "purchase", "place an order", "can i order",
    "ordering",
    "shipping", "ship to", "deliver", "delivery", "in stock", "available", "availability", "discount",
    "coupon", "promo code", "where can i get", "where can i buy", "where to buy", "link to buy",
    "wholesale", "bulk", "quote", "invoice", "book a", "booking", "demo", "trial", "subscribe", "sign up",
    "pay", "payment", "checkout",
)
_NEGATIVE_WORDS = (
    "refund", "scam", "fake", "broken", "doesn't work", "does not work", "didn't work", "not working",
    "worst", "terrible", "awful", "disappointed", "waste of money", "never arrived", "rip off", "ripoff",
    "complaint", "bad quality",
)
_QUESTION_STARTS = ("how", "what", "where", "when", "why", "which", "who", "can", "could", "do", "does",
                    "is", "are", "will", "would", "should")
_POSITIVE_WORDS = (
    "love", "loved", "great", "amazing", "awesome", "nice", "cool", "fire", "best", "thank", "thanks",
    "helpful", "beautiful", "perfect", "good", "brilliant", "excellent", "incredible", "wow", "congrats",
    "congratulations", "well done", "so good", "legend", "inspiring", "useful", "fantastic", "gorgeous",
    "obsessed", "stunning",
)


@dataclass(frozen=True)
class Classification:
    label: str
    confidence: float
    signals: tuple[str, ...] = field(default_factory=tuple)

    def to_record(self) -> dict:
        return {"label": self.label, "confidence": self.confidence, "signals": list(self.signals)}


def _words_present(lowered: str, words: tuple[str, ...] | list[str]) -> list[str]:
    hits: list[str] = []
    for word in words:
        w = str(word or "").strip().lower()
        if not w:
            continue
        pattern = r"(?<![\w])" + re.escape(w) + r"(?![\w])"
        if re.search(pattern, lowered):
            hits.append(w)
    return hits


def _confidence(hits: int) -> float:
    return {0: 0.0, 1: 0.6, 2: 0.8}.get(hits, 0.9)


def classify(text: str, *, kind: str = "comment", blocked_words: tuple[str, ...] | list[str] = ()) -> Classification:
    """Label one inbound message. ``kind`` is ``comment`` or ``dm``."""
    raw = str(text or "")
    lowered = " ".join(raw.lower().split())
    if not lowered:
        return Classification(NEUTRAL, 0.0)

    blocked = _words_present(lowered, list(blocked_words))
    if blocked:
        return Classification(SPAM, 0.9, tuple(f"blocked word: {w}" for w in blocked[:3]))

    spam_hits = _words_present(lowered, _SPAM_PHRASES)
    has_link = bool(_URL.search(raw))
    spam_signals = list(spam_hits)
    if has_link and kind == "comment":
        spam_signals.append("link")
    if _REPEAT.search(lowered):
        spam_signals.append("repeated characters")
    if kind == "comment" and len(_HANDLE_PROMO.findall(raw)) >= 3:
        spam_signals.append("many @mentions")
    # A lone link in a DM is common and not spam by itself.
    if spam_hits or (kind == "comment" and len(spam_signals) >= 2):
        return Classification(SPAM, _confidence(len(spam_signals)), tuple(spam_signals[:4]))

    abuse = _words_present(lowered, _ABUSE_WORDS)
    if abuse:
        return Classification(ABUSE, _confidence(len(abuse)), tuple(abuse[:4]))

    buy = _words_present(lowered, _BUY_WORDS)
    if buy:
        return Classification(BUYING_INTENT, _confidence(len(buy)), tuple(buy[:4]))

    negative = _words_present(lowered, _NEGATIVE_WORDS)
    if negative:
        return Classification(NEGATIVE, _confidence(len(negative)), tuple(negative[:4]))

    first = lowered.split(" ", 1)[0].strip(",.!")
    if "?" in lowered or first in _QUESTION_STARTS:
        return Classification(QUESTION, 0.6, ("question",))

    positive = _words_present(lowered, _POSITIVE_WORDS)
    if positive:
        return Classification(POSITIVE, _confidence(len(positive)), tuple(positive[:4]))

    return Classification(NEUTRAL, 0.3)


def lead_score(c: Classification, *, kind: str) -> int:
    """0-100 for sorting the Leads view: DMs and more buying signals rank higher."""
    if c.label != BUYING_INTENT:
        return 0
    base = 50 if kind == "dm" else 30
    return min(100, base + 15 * len(c.signals))
