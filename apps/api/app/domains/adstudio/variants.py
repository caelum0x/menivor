"""Pure variant planning: formats x angles x aspects -> render storyboards.

Formats:

* ``showcase``     — product images with camera motion + caption cards
                     (hook -> benefits -> proof -> offer -> CTA). Rendered locally
                     with FFmpeg: free, no provider.
* ``before_after`` — a desaturated "before" beat carrying the pain point, then
                     vivid "after" beats with benefits, proof and CTA. Local FFmpeg.
* ``ugc_avatar``   — a talking-avatar UGC reel: a caption-free product montage is
                     rendered locally as the background, then the existing reel
                     pipeline (``POST /jobs``) lip-syncs the chosen avatar reading
                     the angle's script over it. Uses the caller's normal reel
                     credits and avatar provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domains.adstudio.angles import format_price
from app.domains.adstudio.cards import Card

FORMATS: tuple[str, ...] = ("showcase", "before_after", "ugc_avatar")
ASPECTS: dict[str, tuple[int, int]] = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
MOTIONS: tuple[str, ...] = ("zoom_in", "pan_right", "zoom_out", "pan_left")
MONTAGE_SECONDS = 36.0
MONTAGE_SHOT_SECONDS = 3.0
MAX_VARIANTS_PER_REQUEST = 30

_WORDS = {
    "en": {"before": "BEFORE", "after": "AFTER", "reviews": "What buyers say", "shop": "Shop now"},
    "tr": {"before": "ÖNCE", "after": "SONRA", "reviews": "Alıcılar ne diyor", "shop": "Hemen al"},
}


@dataclass(frozen=True)
class Segment:
    image_index: int
    seconds: float
    motion: str
    card: Card | None = None
    grade: str = "normal"  # normal | before | after


def _words(language: str) -> dict[str, str]:
    return _WORDS.get(language, _WORDS["en"])


def _offer_card(angle: dict[str, Any], product: dict[str, Any], language: str) -> Card | None:
    price = format_price(product.get("price"), str(product.get("currency") or ""), language)
    original = format_price(product.get("original_price"), str(product.get("currency") or ""), language)
    if price:
        was = (f"{original} yerine" if language == "tr" else f"was {original}") if original else ""
        return Card(text=price, style="price", subtext=was)
    if angle.get("offer"):
        return Card(text=angle["offer"], style="body")
    return None


def showcase_segments(angle: dict[str, Any], product: dict[str, Any], language: str) -> list[Segment]:
    cards: list[tuple[Card, float]] = [(Card(text=angle.get("hook", ""), style="hook"), 2.4)]
    for benefit in (angle.get("benefits") or [])[:2]:
        cards.append((Card(text=benefit, style="body"), 2.6))
    if angle.get("proof"):
        cards.append((Card(text=angle["proof"], style="body"), 2.8))
    offer = _offer_card(angle, product, language)
    if offer:
        cards.append((offer, 2.4))
    cards.append((Card(text=angle.get("cta") or _words(language)["shop"], style="cta"), 2.6))
    return [
        Segment(image_index=i, seconds=secs, motion=MOTIONS[i % len(MOTIONS)], card=card)
        for i, (card, secs) in enumerate(cards)
        if card.text.strip()
    ]


def before_after_segments(angle: dict[str, Any], product: dict[str, Any], language: str) -> list[Segment]:
    words = _words(language)
    benefits = angle.get("benefits") or []
    segments = [
        Segment(0, 3.0, "zoom_in", Card(text=angle.get("pain", ""), style="body", label=words["before"]), "before"),
        Segment(0, 3.0, "zoom_out", Card(text=benefits[0] if benefits else angle.get("hook", ""), style="hook", label=words["after"]), "after"),
    ]
    if len(benefits) > 1:
        segments.append(Segment(1, 2.6, "pan_right", Card(text=benefits[1], style="body"), "after"))
    if angle.get("proof"):
        segments.append(Segment(2, 2.6, "pan_left", Card(text=angle["proof"], style="body"), "after"))
    offer = _offer_card(angle, product, language)
    if offer:
        segments.append(Segment(3, 2.4, "zoom_in", offer, "after"))
    segments.append(Segment(0, 2.6, "zoom_out", Card(text=angle.get("cta") or words["shop"], style="cta"), "after"))
    return [s for s in segments if s.card is None or s.card.text.strip()]


def montage_segments(image_count: int) -> list[Segment]:
    shots = max(1, int(MONTAGE_SECONDS // MONTAGE_SHOT_SECONDS))
    return [
        Segment(i % max(1, image_count), MONTAGE_SHOT_SECONDS, MOTIONS[i % len(MOTIONS)])
        for i in range(shots)
    ]


def segments_for(fmt: str, angle: dict[str, Any], product: dict[str, Any], language: str, image_count: int) -> list[Segment]:
    if fmt == "showcase":
        return showcase_segments(angle, product, language)
    if fmt == "before_after":
        return before_after_segments(angle, product, language)
    if fmt == "ugc_avatar":
        return montage_segments(image_count)
    raise ValueError(f"unknown ad format: {fmt}")


def build_job_request(
    *,
    angle: dict[str, Any],
    product: dict[str, Any],
    language: str,
    aspect: str,
    montage_key: str,
    avatar_id: str,
    voice_id: str = "",
    caption_style: str = "",
) -> dict[str, Any]:
    """The exact ``POST /jobs`` body for a UGC avatar variant."""
    title = str(product.get("title") or "Product")[:120]
    params: dict[str, Any] = {
        "video_subject": title,
        "video_script": angle.get("script", ""),
        "avatar_id": avatar_id,
        "layout": "pip",
        "aspect": aspect,
        "language": language if language in ("tr", "en") else "auto",
        "target_duration_s": 30,
        "platforms": [],
        "screen_recording_key": montage_key,
    }
    body: dict[str, Any] = {"params": params, "avatar_id": avatar_id, "variants": 1, "tos_disclosure": True}
    if voice_id:
        body["voice_id"] = voice_id
    if caption_style:
        body["caption_style"] = caption_style
    return body


def plan_matrix(angle_ids: list[str], formats: list[str], aspects: list[str]) -> list[tuple[str, str, str]]:
    """Validated (angle_id, format, aspect) combinations in a stable order."""
    unknown_formats = [f for f in formats if f not in FORMATS]
    if unknown_formats:
        raise ValueError(f"unknown ad format(s): {', '.join(unknown_formats)}")
    unknown_aspects = [a for a in aspects if a not in ASPECTS]
    if unknown_aspects:
        raise ValueError(f"unsupported aspect ratio(s): {', '.join(unknown_aspects)}")
    combos = [(a, f, r) for a in dict.fromkeys(angle_ids) for f in dict.fromkeys(formats) for r in dict.fromkeys(aspects)]
    if not combos:
        raise ValueError("pick at least one angle, format and aspect ratio")
    if len(combos) > MAX_VARIANTS_PER_REQUEST:
        raise ValueError(f"at most {MAX_VARIANTS_PER_REQUEST} variants per batch")
    return combos


__all__ = [
    "ASPECTS",
    "FORMATS",
    "MAX_VARIANTS_PER_REQUEST",
    "Segment",
    "build_job_request",
    "plan_matrix",
    "segments_for",
]
