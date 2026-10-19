"""Pure OpenGraph / twitter-card meta parsing plus small text heuristics.

No network. ``parse_meta`` reads ``<meta property|name|itemprop=... content=...>``
tags in any attribute order; the helpers derive a hook, topic keywords, niche
and voice from captions/bios. Everything here is deterministic and unit-tested.
"""

from __future__ import annotations

import html as _html
import re
from collections import Counter

_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', re.DOTALL)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_ISO_DURATION = re.compile(r"^P(?:T)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", re.IGNORECASE)
_HASHTAG = re.compile(r"#([A-Za-z][A-Za-z0-9_]{1,40})")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_URLISH = re.compile(r"https?://\S+|pic\.twitter\.com/\S+")

_MAX_HOOK = 140
_STOPWORDS = frozenset(
    "the and for you your with this that are was were have has had not but all can will just "
    "from they them their what when where who how why our out get got its it's i'm i've "
    "about into more most some than then there these those very really also like one two "
    "new now day days here make made been being over only even much many any every which "
    "would could should video post follow link bio watch shorts reel reels tiktok instagram "
    "youtube twitter facebook threads pinterest linkedin fyp foryou viral trending".split()
)
_NICHES = {
    "fitness": {"fitness", "gym", "workout", "training", "muscle", "health", "yoga", "run", "running"},
    "food": {"food", "recipe", "recipes", "cooking", "chef", "baking", "kitchen", "eat"},
    "beauty": {"beauty", "makeup", "skincare", "skin", "hair", "nails", "cosmetics"},
    "fashion": {"fashion", "style", "outfit", "outfits", "clothing", "wear", "streetwear"},
    "tech": {"tech", "software", "app", "apps", "ai", "code", "coding", "developer", "startup", "saas"},
    "finance": {"finance", "money", "invest", "investing", "stocks", "crypto", "budget", "wealth"},
    "travel": {"travel", "trip", "trips", "adventure", "explore", "wanderlust", "hotel"},
    "gaming": {"gaming", "gamer", "game", "games", "esports", "twitch", "streamer"},
    "education": {"learn", "learning", "education", "teacher", "study", "tips", "tutorial", "course"},
    "business": {"business", "marketing", "entrepreneur", "founder", "brand", "sales", "growth"},
    "home": {"home", "decor", "interior", "diy", "garden", "furniture"},
    "music": {"music", "musician", "singer", "producer", "artist", "songs", "band"},
}
_VOICE_WORDS = {
    "playful": {"lol", "fun", "vibes", "obsessed", "haha", "chaos", "silly", "cute", "!!"},
    "educational": {"learn", "tips", "how", "guide", "tutorial", "explained", "teach", "lessons"},
    "professional": {"official", "solutions", "services", "company", "enterprise", "team",
                     "leading", "platform", "customers", "industry"},
    "inspirational": {"dream", "believe", "motivation", "inspire", "journey", "mindset", "grow"},
}


def clean_text(text: str | None) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    without_tags = _TAG.sub(" ", text or "")
    return _WS.sub(" ", _html.unescape(without_tags)).strip()


def parse_meta(source: str) -> dict[str, str]:
    """Return lowercase meta keys (og:*, twitter:*, itemprop, name) -> first content."""
    found: dict[str, str] = {}
    for tag in _META_TAG.findall(source or ""):
        attrs = {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4) or "")
                 for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key and "content" in attrs and key not in found:
            found[key] = _html.unescape(attrs["content"]).strip()
    if "title" not in found:
        match = _TITLE.search(source or "")
        if match:
            found["title"] = clean_text(match.group(1))
    return found


def parse_duration(value: str | None) -> int | None:
    """Seconds from ``"63"`` or ISO-8601 ``"PT1M3S"``; ``None`` when unknown."""
    text = (value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    match = _ISO_DURATION.match(text)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def first_line_hook(caption: str) -> str:
    """First line or sentence of ``caption``, trimmed to a hook-sized string."""
    text = _URLISH.sub("", caption or "").strip()
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    sentence = _SENTENCE_END.split(line, maxsplit=1)[0].strip()
    sentence = _HASHTAG.sub("", sentence).strip() or sentence
    if len(sentence) > _MAX_HOOK:
        sentence = sentence[:_MAX_HOOK].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return sentence


def _keywords(text: str, limit: int) -> list[str]:
    tags = [t.lower() for t in _HASHTAG.findall(text or "") if t.lower() not in _STOPWORDS]
    body = _HASHTAG.sub(" ", _URLISH.sub(" ", text or ""))
    words = [w.lower().strip("'-") for w in _WORD.findall(body)]
    counts = Counter(w for w in words if w not in _STOPWORDS and len(w) > 2)
    ordered = list(dict.fromkeys(tags + [w for w, _ in counts.most_common()]))
    return ordered[:limit]


def topic_from(*texts: str, limit: int = 3) -> str:
    """Short topic phrase from hashtags first, then frequent content words."""
    words = _keywords(" ".join(t for t in texts if t), limit)
    return " ".join(words) if words else ""


def niche_from(*texts: str) -> str | None:
    words = set(_keywords(" ".join(t for t in texts if t), 40))
    best, best_hits = None, 0
    for niche, vocab in _NICHES.items():
        hits = len(words & vocab)
        if hits > best_hits:
            best, best_hits = niche, hits
    return best


def voice_from(*texts: str) -> str:
    """A simple tone heuristic: playful / educational / professional / inspirational / casual."""
    raw = " ".join(t for t in texts if t)
    lowered = raw.lower()
    words = set(_WORD.findall(lowered))
    scores = {voice: len(words & vocab) for voice, vocab in _VOICE_WORDS.items()}
    scores["playful"] += lowered.count("!!") + (1 if raw.count("!") >= 2 else 0)
    best = max(scores, key=lambda v: scores[v])
    return best if scores[best] > 0 else "casual"


__all__ = [
    "clean_text", "first_line_hook", "niche_from", "parse_duration", "parse_meta",
    "topic_from", "voice_from",
]
