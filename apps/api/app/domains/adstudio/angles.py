"""Ad angles: hook / pain / proof / offer / CTA for a product.

Two paths share one output shape:

* :func:`template_angles` — deterministic, offline, always available. Built only
  from facts that were actually extracted (no invented ratings or discounts).
* :func:`llm_angles` — the configured LLM provider (``app.services.llm``) writes
  punchier copy from the same facts. Every LLM field passes an honesty guard:
  a field that mentions a number which does not appear in the product facts is
  replaced by the template field, so the model cannot fabricate prices,
  percentages or review counts. Any provider failure or timeout falls back to
  the template angles.
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any, Callable

ANGLE_KINDS: tuple[str, ...] = ("problem_solution", "social_proof", "offer", "demo", "before_after")
FIELDS: tuple[str, ...] = ("hook", "pain", "proof", "offer", "cta")
FIELD_MAX = 220
LLM_TIMEOUT_S = 45
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CURRENCY_SIGN = {"USD": "$", "EUR": "€", "GBP": "£"}

LABELS = {
    "en": {"problem_solution": "Problem / solution", "social_proof": "Social proof", "offer": "Offer", "demo": "Feature demo", "before_after": "Before / after"},
    "tr": {"problem_solution": "Sorun / çözüm", "social_proof": "Sosyal kanıt", "offer": "Kampanya", "demo": "Özellik tanıtımı", "before_after": "Önce / sonra"},
}


def format_price(value: float | None, currency: str, language: str) -> str:
    if not value:
        return ""
    if language == "tr" or currency == "TRY":
        whole, _, frac = f"{value:,.2f}".partition(".")
        text = f"{whole.replace(',', '.')},{frac}"
        text = text[:-3] if text.endswith(",00") else text
        return f"{text} TL" if currency in ("TRY", "") else f"{text} {currency}"
    text = f"{value:,.2f}".removesuffix(".00")
    sign = _CURRENCY_SIGN.get(currency)
    return f"{sign}{text}" if sign else f"{text} {currency}".strip()


def short_name(product: dict[str, Any]) -> str:
    title = str(product.get("title") or "").strip()
    brand = str(product.get("brand") or "").strip()
    words = title.split()
    if brand and title.lower().startswith(brand.lower()):
        rest = title[len(brand):].split()
        words = rest if len(rest) >= 2 else words
    name = " ".join(words[:6]).strip(" ,-|")
    return name or title[:60] or "this product"


def _benefits(product: dict[str, Any], limit: int = 3) -> list[str]:
    items = [str(b).strip().rstrip(".") for b in product.get("bullets") or [] if str(b).strip()]
    if not items and product.get("description"):
        first = re.split(r"(?<=[.!?])\s+", str(product["description"]))[0]
        items = [first.strip().rstrip(".")[:140]]
    return [i[:140] for i in items[:limit]]


def _facts(product: dict[str, Any], language: str) -> dict[str, str]:
    tr = language == "tr"
    price = format_price(product.get("price"), str(product.get("currency") or ""), language)
    original = format_price(product.get("original_price"), str(product.get("currency") or ""), language)
    rating = product.get("rating")
    count = product.get("review_count")
    review = next((r for r in product.get("reviews") or [] if 12 <= len(r) <= 140), "")
    if rating and count:
        proof = f"{count} değerlendirmede {rating:.1f}/5 puan." if tr else f"Rated {rating:.1f}/5 across {count} reviews."
    elif rating:
        proof = f"Alıcılardan {rating:.1f}/5 puan." if tr else f"Buyers rate it {rating:.1f}/5."
    elif review:
        proof = f"Bir alıcı: “{review}”" if tr else f"One buyer said: “{review}”"
    else:
        proof = ""
    if price and original:
        offer = f"{original} yerine şimdi {price}." if tr else f"Now {price}, down from {original}."
    elif price:
        offer = f"Sadece {price}." if tr else f"Just {price}."
    else:
        offer = ""
    return {"price": price, "original": original, "proof": proof, "offer": offer, "review": review}


def _template(kind: str, product: dict[str, Any], language: str) -> dict[str, str]:
    tr = language == "tr"
    name = short_name(product)
    benefits = _benefits(product)
    first = benefits[0] if benefits else ""
    facts = _facts(product, language)
    proof = facts["proof"] or (f"{first}." if first else "")
    offer = facts["offer"] or ("Stoklar tükenmeden al." if tr else "Available now while stock lasts.")
    cta = "Linke dokun, hemen sipariş ver." if tr else "Tap the link and get yours today."
    if kind == "problem_solution":
        hook = f"{name} olmadan bunu yapmayı bırak." if tr else f"Stop struggling without {name}."
        pain = "Her gün aynı sorunla uğraşmaktan yoruldun mu?" if tr else "Tired of dealing with the same problem every day?"
    elif kind == "social_proof":
        hook = f"Herkes neden {name} alıyor?" if tr else f"Why is everyone buying {name}?"
        pain = "Yorumları okumadan karar vermek zor." if tr else "Hard to trust a product before you see real buyers."
    elif kind == "offer":
        hook = f"{name} için bu fiyatı kaçırma." if tr else f"Don't miss this price on {name}."
        pain = "İyi ürünler genelde pahalıya gelir." if tr else "Good products usually cost a lot more."
    elif kind == "before_after":
        hook = f"{name} öncesi ve sonrası." if tr else f"Before and after {name}."
        pain = "Önce: zaman kaybı ve memnuniyetsizlik." if tr else "Before: wasted time and results you don't love."
    else:  # demo
        hook = f"{name} gerçekte böyle çalışıyor." if tr else f"Here is what {name} actually does."
        pain = (f"Bilmen gereken tek şey: {first}." if first else "Detaylar önemli.") if tr else (f"The one thing to know: {first}." if first else "The details matter.")
    return {"hook": hook, "pain": pain, "proof": proof, "offer": offer, "cta": cta}


def build_script(angle: dict[str, str], product: dict[str, Any], language: str) -> str:
    """Voiceover script: hook -> pain -> 1-2 benefits -> proof -> offer -> CTA."""
    benefits = _benefits(product, 2)
    parts = [angle.get("hook", ""), angle.get("pain", "")]
    parts += [f"{b}." for b in benefits if b and b.lower() not in angle.get("pain", "").lower()]
    parts += [angle.get("proof", ""), angle.get("offer", ""), angle.get("cta", "")]
    return " ".join(p.strip() for p in parts if p and p.strip())[:1200]


def _finish(kind: str, fields: dict[str, str], product: dict[str, Any], language: str, source: str, index: int) -> dict[str, Any]:
    angle = {f: str(fields.get(f) or "").strip()[:FIELD_MAX] for f in FIELDS}
    return {
        "id": f"a{index + 1}",
        "kind": kind,
        "label": LABELS.get(language, LABELS["en"]).get(kind, kind),
        **angle,
        "benefits": _benefits(product),
        "script": build_script(angle, product, language),
        "source": source,
    }


finish_angle = _finish


def template_angles(product: dict[str, Any], language: str, count: int = 5) -> list[dict[str, Any]]:
    kinds = ANGLE_KINDS[: max(3, min(count, len(ANGLE_KINDS)))]
    return [_finish(k, _template(k, product, language), product, language, "template", i) for i, k in enumerate(kinds)]


def _facts_text(product: dict[str, Any], language: str) -> str:
    facts = _facts(product, language)
    lines = [
        f"Product: {product.get('title', '')}",
        f"Brand: {product.get('brand', '')}",
        f"Price: {facts['price']}",
        f"Original price: {facts['original']}",
        f"Rating: {product.get('rating') or ''} ({product.get('review_count') or ''} reviews)",
        "Features: " + " | ".join(_benefits(product, 6)),
        "Description: " + str(product.get("description") or "")[:500],
        "Buyer reviews: " + " | ".join(str(r) for r in (product.get("reviews") or [])[:4]),
    ]
    return "\n".join(lines)


def build_prompt(product: dict[str, Any], language: str, kinds: tuple[str, ...]) -> str:
    lang_name = "Turkish" if language == "tr" else "English"
    return (
        "You write short-form video ad copy (TikTok / Reels / Shorts) for e-commerce products.\n"
        f"Write one ad angle for each of these angle kinds, in {lang_name}: {', '.join(kinds)}.\n"
        "Each angle has: hook (max 12 words, scroll-stopping), pain (the problem), proof "
        "(credibility), offer (price or reason to act now), cta (call to action).\n"
        "STRICT RULES: use ONLY the facts below. Never invent numbers, ratings, review counts, "
        "discounts, awards or medical/health claims. If a fact is missing, write copy without it.\n"
        'Reply with ONLY a JSON array like [{"kind":"...","hook":"...","pain":"...","proof":"...",'
        '"offer":"...","cta":"..."}].\n\n'
        f"FACTS:\n{_facts_text(product, language)}\n"
    )


def _norm_number(token: str) -> str:
    try:
        return f"{float(token.replace(',', '.')):g}"
    except ValueError:
        return token


# Tiny counting words ("3 reasons", "in 2 minutes") and the "/5" rating scale
# are not factual claims on their own.
_ALWAYS_ALLOWED_NUMBERS = frozenset({"1", "2", "3", "5"})


def _numbers(text: str) -> set[str]:
    return {_norm_number(n) for n in _NUMBER_RE.findall(text)}


def parse_llm_response(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if not text or text.startswith("Error:"):
        return []
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def merge_llm(items: list[dict[str, Any]], product: dict[str, Any], language: str, count: int) -> list[dict[str, Any]]:
    """Honesty-guarded merge of LLM angles over the template angles."""
    allowed = _numbers(_facts_text(product, language)) | _ALWAYS_ALLOWED_NUMBERS
    by_kind = {str(i.get("kind") or "").strip().lower(): i for i in items}
    kinds = ANGLE_KINDS[: max(3, min(count, len(ANGLE_KINDS)))]
    out: list[dict[str, Any]] = []
    for index, kind in enumerate(kinds):
        template = _template(kind, product, language)
        llm = by_kind.get(kind) or (items[index] if index < len(items) else {})
        fields: dict[str, str] = {}
        used_llm = False
        for field in FIELDS:
            value = " ".join(str(llm.get(field) or "").split())[:FIELD_MAX]
            if value and _numbers(value) <= allowed:
                fields[field] = value
                used_llm = True
            else:
                fields[field] = template[field]
        out.append(_finish(kind, fields, product, language, "llm" if used_llm else "template", index))
    return out


def _default_generate(prompt: str) -> str:
    from app.services.llm import _generate_response

    return _generate_response(prompt)


def llm_angles(
    product: dict[str, Any],
    language: str,
    count: int = 5,
    *,
    generate: Callable[[str], str] | None = None,
    timeout_s: float = LLM_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """LLM angles with a deterministic fallback; never raises."""
    kinds = ANGLE_KINDS[: max(3, min(count, len(ANGLE_KINDS)))]
    call = generate or _default_generate
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        raw = pool.submit(call, build_prompt(product, language, kinds)).result(timeout=timeout_s)
    except Exception:  # noqa: BLE001 - timeout / provider error -> template copy
        raw = ""
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    items = parse_llm_response(raw)
    if not items:
        return template_angles(product, language, count)
    return merge_llm(items, product, language, count)


__all__ = [
    "ANGLE_KINDS",
    "build_script",
    "finish_angle",
    "format_price",
    "llm_angles",
    "merge_llm",
    "parse_llm_response",
    "template_angles",
]
