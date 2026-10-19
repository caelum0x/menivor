"""Fit one caption/title/hashtag set to each platform's limits.

The creator writes one post; every platform gets a version that respects its
own caption length, title length and hashtag count. Nothing is silently lost:
each change is reported as an issue the UI shows next to that platform.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .catalog import FormatRules, spec_for

_ELLIPSIS = "..."
_TAG_RE = re.compile(r"[^\w]", re.UNICODE)


@dataclass(frozen=True)
class FormatIssue:
    level: str   # "warning" | "error"
    field: str   # "caption" | "title" | "hashtags" | "video"
    message: str

    def to_record(self) -> dict:
        return {"level": self.level, "field": self.field, "message": self.message}


@dataclass(frozen=True)
class FittedPost:
    platform: str
    text: str                       # caption + hashtags, ready to post
    title: str
    hashtags: tuple[str, ...]
    length: int
    limit: int
    issues: tuple[FormatIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def to_record(self) -> dict:
        return {
            "platform": self.platform,
            "text": self.text,
            "title": self.title,
            "hashtags": list(self.hashtags),
            "length": self.length,
            "limit": self.limit,
            "ok": self.ok,
            "issues": [i.to_record() for i in self.issues],
        }


def grapheme_len(text: str) -> int:
    """Approximate user-perceived characters (combining marks + ZWJ joins collapse)."""
    count = 0
    joined = False
    for ch in text:
        if ch == "\u200d":
            joined = True
            continue
        if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me") or ch in "\ufe0e\ufe0f":
            continue
        if joined:
            joined = False
            continue
        count += 1
    return count


def measure(text: str, rules: FormatRules) -> int:
    return grapheme_len(text) if rules.counts_graphemes else len(text)


def normalize_tag(tag: str) -> str:
    """``"#My Tag!"`` -> ``"MyTag"``; empty when nothing usable is left."""
    return _TAG_RE.sub("", str(tag or "").lstrip("#"))[:100]


def _shorten(text: str, limit: int, rules: FormatRules) -> str:
    """Cut ``text`` to ``limit`` (measured the platform's way) at a word boundary."""
    if measure(text, rules) <= limit:
        return text
    budget = max(0, limit - len(_ELLIPSIS))
    out = text
    while out and measure(out, rules) > budget:
        out = out[:-1]
    cut = out.rstrip()
    space = cut.rfind(" ")
    if space >= max(1, int(budget * 0.6)):
        cut = cut[:space].rstrip()
    return f"{cut}{_ELLIPSIS}" if cut else ""


def fit(platform: str, *, caption: str = "", title: str = "", hashtags: tuple[str, ...] | list[str] = ()) -> FittedPost:
    """Fit a post to ``platform``; raises ``ValueError`` for an unknown platform."""
    spec = spec_for(platform)
    if spec is None:
        raise ValueError(f"unknown platform {platform!r}")
    rules = spec.rules
    issues: list[FormatIssue] = []

    tags: list[str] = []
    seen: set[str] = set()
    for raw in hashtags or ():
        tag = normalize_tag(raw)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    if len(tags) > rules.hashtags_max:
        issues.append(FormatIssue(
            "warning", "hashtags",
            f"{spec.label} allows up to {rules.hashtags_max} hashtag{'s' if rules.hashtags_max != 1 else ''}; "
            f"kept the first {rules.hashtags_max}.",
        ))
        tags = tags[: rules.hashtags_max]

    body = re.sub(r"[ \t]+", " ", str(caption or "")).strip()
    tag_text = " ".join(f"#{t}" for t in tags)
    joiner = "\n\n" if body and tag_text else ""
    full = f"{body}{joiner}{tag_text}"

    if not body and not tag_text:
        issues.append(FormatIssue("warning", "caption", "No caption. The video posts without text."))

    if measure(full, rules) > rules.caption_max:
        # Keep the hashtags when they fit; shorten the caption body first.
        room = rules.caption_max - measure(f"{joiner}{tag_text}", rules)
        if room >= 20 and body:
            short = _shorten(body, room, rules)
            full = f"{short}{joiner}{tag_text}"
            issues.append(FormatIssue(
                "warning", "caption",
                f"Caption shortened to fit {spec.label}'s {rules.caption_max}-character limit.",
            ))
        else:
            full = _shorten(full, rules.caption_max, rules)
            issues.append(FormatIssue(
                "warning", "caption",
                f"Caption and hashtags shortened to fit {spec.label}'s {rules.caption_max}-character limit.",
            ))

    fitted_title = re.sub(r"\s+", " ", str(title or "")).strip()
    if rules.title_max:
        if len(fitted_title) > rules.title_max:
            fitted_title = _shorten(fitted_title, rules.title_max, rules)
            issues.append(FormatIssue(
                "warning", "title", f"Title shortened to {rules.title_max} characters for {spec.label}.",
            ))
    else:
        fitted_title = ""

    return FittedPost(
        platform=spec.key,
        text=full,
        title=fitted_title,
        hashtags=tuple(tags),
        length=measure(full, rules),
        limit=rules.caption_max,
        issues=tuple(issues),
    )


def check_video(platform: str, *, size_bytes: int | None, duration_s: float | None) -> tuple[FormatIssue, ...]:
    """Video-level limits we can verify before uploading (size always, duration when known)."""
    spec = spec_for(platform)
    if spec is None:
        return (FormatIssue("error", "video", f"unknown platform {platform!r}"),)
    rules = spec.rules
    out: list[FormatIssue] = []
    if size_bytes is not None and rules.max_bytes and size_bytes > rules.max_bytes:
        out.append(FormatIssue(
            "error", "video",
            f"The video is {size_bytes // (1024 * 1024)} MB; {spec.label} accepts up to "
            f"{rules.max_bytes // (1024 * 1024)} MB.",
        ))
    if duration_s is not None and duration_s > 0:
        if rules.video_max_seconds and duration_s > rules.video_max_seconds:
            out.append(FormatIssue(
                "error", "video",
                f"The video is {int(duration_s)}s; {spec.label} accepts up to {int(rules.video_max_seconds)}s.",
            ))
        if rules.video_min_seconds and duration_s < rules.video_min_seconds:
            out.append(FormatIssue(
                "error", "video",
                f"The video is {duration_s:.1f}s; {spec.label} needs at least {rules.video_min_seconds:g}s.",
            ))
    return tuple(out)
