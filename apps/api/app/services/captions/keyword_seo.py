"""Caption keyword-SEO — front-load the words viewers search for.

Research (docs/reelforge/vision2026): IG Reels + YT Shorts index the on-screen
caption text + description as a discovery/search signal, so a caption should
front-load the query-relevant keywords and carry a small set of specific hashtags
(broad tags are noise). This module extracts the content keywords from the reel's
script/topic, ranks them by frequency, and builds a platform-tuned caption +
hashtag set. Pure + deterministic (no LLM) so it is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

_STOPWORDS = frozenset(
    """a an and the to of in on at for with is are was were be been being it its this that these those
    i you he she we they me him her us them my your his our their as but or if so no not do does did
    have has had will would can could should just about into over under out up down off then than
    what when where who how why which am pm ok okay yeah your youre im dont cant wont
    this thats will get got make made way day time thing things really very much""".split()
)

# Per-platform caption tuning (max hashtags is the meaningful lever — more is noise).
_PLATFORM = {
    "tiktok": {"max_hashtags": 5, "max_caption_chars": 150},
    "reels": {"max_hashtags": 8, "max_caption_chars": 125},
    "shorts": {"max_hashtags": 5, "max_caption_chars": 100},
    "x": {"max_hashtags": 3, "max_caption_chars": 240},
}
_FALLBACK = {"max_hashtags": 5, "max_caption_chars": 150}


@dataclass(frozen=True)
class SeoCaption:
    """A platform-optimized caption + hashtag set + the ranked keywords."""

    caption: str
    hashtags: tuple[str, ...]
    keywords: tuple[str, ...]


def _tokens(text: str) -> list[str]:
    word = []
    out = []
    for ch in str(text).lower():
        if ch.isalnum():
            word.append(ch)
        else:
            if word:
                out.append("".join(word))
                word = []
    if word:
        out.append("".join(word))
    return out


def extract_keywords(text: str, *, limit: int = 10) -> list[str]:
    """Content keywords ranked by frequency (stopword-filtered, ≥3 chars).

    Ties are broken by first-appearance order so the result is deterministic.
    """
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for i, tok in enumerate(_tokens(text)):
        if len(tok) < 3 or tok in _STOPWORDS or tok.isdigit():
            continue
        counts[tok] = counts.get(tok, 0) + 1
        order.setdefault(tok, i)
    ranked = sorted(counts, key=lambda w: (-counts[w], order[w]))
    return ranked[:limit]


def build_seo_caption(
    text: str, *, platform: str = "tiktok", base_caption: str = ""
) -> SeoCaption:
    """Build a keyword-front-loaded caption + a capped set of specific hashtags.

    ``base_caption`` (the creator's hook line) leads; the top keywords are appended
    as hashtags, capped per platform. When no base is given, the keywords form the
    caption so the searchable text is never empty.
    """
    cfg = _PLATFORM.get(str(platform or "").strip().lower(), _FALLBACK)
    keywords = extract_keywords(text, limit=cfg["max_hashtags"] + 4)
    hashtags = tuple(f"#{k}" for k in keywords[: cfg["max_hashtags"]])

    lead = (base_caption or "").strip()
    if not lead:
        # Front-load the searchable keywords as the caption itself.
        lead = " ".join(keywords[:6]).strip()
    caption = lead[: cfg["max_caption_chars"]].rstrip()
    return SeoCaption(caption=caption, hashtags=hashtags, keywords=tuple(keywords))
