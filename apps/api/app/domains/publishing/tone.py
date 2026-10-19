"""Deterministic tone rewrites + per-platform caption preview for the calendar.

The creator writes one caption, picks a tone, and sees exactly what each
platform will receive. The tones are plain rule-based rewrites (no model call,
so the preview is instant, free and always identical to what gets posted):

* ``as_written``   - unchanged.
* ``professional`` - no repeated/shouting punctuation, no ALL-CAPS words, no
                     chat fillers ("lol", "omg", ...), full forms ("don't" ->
                     "do not"), sentence case.
* ``casual``       - common contractions ("do not" -> "don't").
* ``concise``      - filler words removed, at most the first two sentences.

Each platform's limits come from :mod:`.extended.formats` (extended platforms
and Telegram / Discord / Mastodon) or the native rules below (TikTok,
Instagram, YouTube), fitted the same way: hashtags kept when they fit, the body
shortened at a word boundary, and every change reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extended.catalog import FormatRules, spec_for
from .extended.formats import FittedPost, FormatIssue, _shorten, fit, measure, normalize_tag

TONES: tuple[str, ...] = ("as_written", "professional", "casual", "concise")
TONE_LABELS: dict[str, str] = {
    "as_written": "As written",
    "professional": "Professional",
    "casual": "Casual",
    "concise": "Concise",
}

# Native platforms (not in the extended catalog). Limits per the platforms' docs.
NATIVE_RULES: dict[str, tuple[str, FormatRules]] = {
    "tiktok": ("TikTok", FormatRules(caption_max=2200, hashtags_max=30)),
    "instagram": ("Instagram", FormatRules(caption_max=2200, hashtags_max=30)),
    "youtube": ("YouTube", FormatRules(caption_max=5000, title_max=100, hashtags_max=15)),
}
_NATIVE_ALIASES = {"youtube_shorts": "youtube", "yt": "youtube"}

_CONTRACTIONS: tuple[tuple[str, str], ...] = (
    ("do not", "don't"), ("does not", "doesn't"), ("did not", "didn't"), ("is not", "isn't"),
    ("are not", "aren't"), ("was not", "wasn't"), ("were not", "weren't"), ("cannot", "can't"),
    ("can not", "can't"), ("will not", "won't"), ("would not", "wouldn't"), ("should not", "shouldn't"),
    ("could not", "couldn't"), ("have not", "haven't"), ("has not", "hasn't"), ("it is", "it's"),
    ("that is", "that's"), ("there is", "there's"), ("what is", "what's"), ("we are", "we're"),
    ("you are", "you're"), ("they are", "they're"), ("I am", "I'm"), ("we will", "we'll"),
    ("you will", "you'll"), ("I will", "I'll"), ("let us", "let's"), ("we have", "we've"),
    ("I have", "I've"),
)
_FILLERS = ("really", "very", "just", "actually", "basically", "literally", "honestly", "totally", "simply",
            "super")
_CHAT_FILLERS = ("lol", "lmao", "omg", "tbh", "ngl", "fr", "imo", "smh")
_HASHTAG_RE = re.compile(r"(?<![\w#])#\w+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _match_case(src: str, dst: str) -> str:
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def _replace_words(text: str, pairs: tuple[tuple[str, str], ...]) -> str:
    out = text
    for a, b in pairs:
        pattern = re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE)
        out = pattern.sub(lambda m, b=b: _match_case(m.group(0), b), out)
    return out


def _protect_hashtags(text: str) -> tuple[str, list[str]]:
    tags: list[str] = []

    def keep(m: re.Match) -> str:
        tags.append(m.group(0))
        return f"\u0000{len(tags) - 1}\u0000"

    return _HASHTAG_RE.sub(keep, text), tags


def _restore_hashtags(text: str, tags: list[str]) -> str:
    return re.sub(r"\u0000(\d+)\u0000", lambda m: tags[int(m.group(1))], text)


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.!?;:])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _sentence_case(text: str) -> str:
    def cap(m: re.Match) -> str:
        return m.group(1) + m.group(2).upper()

    text = re.sub(r"(^|[.!?]\s+|\n\s*)([a-z])", cap, text)
    return text


def professional(text: str) -> str:
    body, tags = _protect_hashtags(text)
    body = re.sub(r"!{2,}", "!", body)
    body = re.sub(r"\?{2,}", "?", body)
    body = re.sub(r"[!?]{2,}", "?", body)
    body = re.sub(r"\.{4,}", "...", body)
    # Shouting words (5+ capitals; shorter ones are usually acronyms) -> lowercase; sentence case fixes starts.
    body = re.sub(r"\b[A-Z]{5,}\b", lambda m: m.group(0).lower(), body)
    for filler in _CHAT_FILLERS:
        body = re.sub(rf"(?i)(^|\s){filler}\b[,.!]?", r"\1", body)
    for full, short in _CONTRACTIONS:
        if short in ("let's",):
            continue
        body = re.sub(rf"\b{re.escape(short)}\b", lambda m, full=full: _match_case(m.group(0), full), body,
                      flags=re.IGNORECASE)
    body = _sentence_case(_tidy(body))
    return _restore_hashtags(body, tags)


def casual(text: str) -> str:
    body, tags = _protect_hashtags(text)
    body = _replace_words(body, _CONTRACTIONS)
    return _restore_hashtags(_tidy(body), tags)


def concise(text: str) -> str:
    body, tags = _protect_hashtags(text)
    for filler in _FILLERS:
        body = re.sub(rf"(?i)\b{filler}\b\s*", "", body)
    body = _tidy(body)
    sentences = [s for s in _SENTENCE_RE.split(body) if s.strip()]
    if len(sentences) > 2:
        # Keep hashtags that lived in the dropped sentences.
        moved = re.findall(r"\u0000\d+\u0000", " ".join(sentences[2:]))
        body = " ".join(sentences[:2] + moved)
    return _restore_hashtags(_sentence_case(_tidy(body)), tags)


def apply_tone(text: str, tone: str) -> str:
    fn = {"professional": professional, "casual": casual, "concise": concise}.get(str(tone or "").strip().lower())
    return fn(str(text or "")) if fn else str(text or "")


def _fit_native(key: str, *, caption: str, title: str, hashtags: tuple[str, ...]) -> FittedPost:
    label, rules = NATIVE_RULES[key]
    issues: list[FormatIssue] = []
    tags: list[str] = []
    seen: set[str] = set()
    for raw in hashtags:
        tag = normalize_tag(raw)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    if len(tags) > rules.hashtags_max:
        issues.append(FormatIssue("warning", "hashtags",
                                  f"{label} allows up to {rules.hashtags_max} hashtags; kept the first "
                                  f"{rules.hashtags_max}."))
        tags = tags[: rules.hashtags_max]
    body = re.sub(r"[ \t]+", " ", caption).strip()
    tag_text = " ".join(f"#{t}" for t in tags)
    joiner = "\n\n" if body and tag_text else ""
    full = f"{body}{joiner}{tag_text}"
    if not full:
        issues.append(FormatIssue("warning", "caption", "No caption. The video posts without text."))
    if measure(full, rules) > rules.caption_max:
        room = rules.caption_max - measure(f"{joiner}{tag_text}", rules)
        full = f"{_shorten(body, room, rules)}{joiner}{tag_text}" if room >= 20 and body else \
            _shorten(full, rules.caption_max, rules)
        issues.append(FormatIssue("warning", "caption",
                                  f"Caption shortened to fit {label}'s {rules.caption_max}-character limit."))
    fitted_title = re.sub(r"\s+", " ", title).strip()
    if rules.title_max and len(fitted_title) > rules.title_max:
        fitted_title = _shorten(fitted_title, rules.title_max, rules)
        issues.append(FormatIssue("warning", "title", f"Title shortened to {rules.title_max} characters."))
    elif not rules.title_max:
        fitted_title = ""
    return FittedPost(platform=key, text=full, title=fitted_title, hashtags=tuple(tags),
                      length=measure(full, rules), limit=rules.caption_max, issues=tuple(issues))


def platform_label(platform: str) -> str:
    key = _NATIVE_ALIASES.get(platform, platform)
    if key in NATIVE_RULES:
        return NATIVE_RULES[key][0]
    spec = spec_for(key)
    return spec.label if spec else platform


@dataclass(frozen=True)
class Preview:
    platform: str
    label: str
    fitted: FittedPost

    def to_record(self) -> dict:
        return {**self.fitted.to_record(), "platform": self.platform, "label": self.label}


def preview(platforms: list[str], *, caption: str, tone: str = "as_written", title: str = "",
            hashtags: tuple[str, ...] = ()) -> tuple[str, list[Preview]]:
    """``(toned_caption, per-platform previews)``; unknown platforms raise ``ValueError``."""
    toned = apply_tone(caption, tone)
    out: list[Preview] = []
    for raw in platforms:
        plat = str(raw or "").strip().lower()
        key = _NATIVE_ALIASES.get(plat, plat)
        if key in NATIVE_RULES:
            fitted = _fit_native(key, caption=toned, title=title, hashtags=tuple(hashtags))
        elif spec_for(key) is not None:
            fitted = fit(key, caption=toned, title=title, hashtags=tuple(hashtags))
        else:
            raise ValueError(f"unknown platform {plat!r}")
        out.append(Preview(platform=plat, label=platform_label(plat), fitted=fitted))
    return toned, out
