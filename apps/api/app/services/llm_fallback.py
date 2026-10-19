"""LLM degrade path (MG8): the configured chain first, then free fallbacks,
then a deterministic script built from the page facts.

Order for every ``llm._generate_response`` call:

1. The configured provider, through Relay on Claude credits when Relay is set
   (``llm._railyard_chat``), else directly.
2. :func:`fallback_chain`: the providers in ``MENIVOR_LLM_FALLBACK_CHAIN``
   (default ``ollama,pollinations,groq``: local first, then free tiers) that
   are actually configured in ``[app]``. ``none`` turns the chain off. No new
   paid service is ever added here; an unconfigured provider is skipped.
3. For reel scripts and search terms only: :func:`deterministic_script` and
   :func:`deterministic_terms`, so a paid reel never fails because every LLM
   is down. The script says only what the subject and the page facts say.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable, Mapping

DEFAULT_CHAIN: tuple[str, ...] = ("ollama", "pollinations", "groq")
_WORD_RE = re.compile(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'&+-]*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_STOP = {
    "the", "a", "an", "and", "or", "for", "with", "your", "you", "our", "of", "to", "in",
    "on", "is", "are", "at", "by", "from", "that", "this", "it", "be", "as", "how", "why",
    "what", "ve", "bir", "ile", "icin", "için",
}
MAX_FACTS = 3
MAX_FACT_CHARS = 180


def is_error(text: Any) -> bool:
    return not isinstance(text, str) or not text.strip() or text.startswith("Error: ")


def _chain_ids() -> list[str]:
    raw = os.environ.get("MENIVOR_LLM_FALLBACK_CHAIN")
    if raw is None:
        return list(DEFAULT_CHAIN)
    if raw.strip().lower() in {"", "none", "off", "0"}:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def is_configured(provider_id: str, app_config: Mapping[str, Any]) -> bool:
    from app.models.llm_provider import get_llm_provider

    spec = get_llm_provider(provider_id)
    if spec is None or spec.adapter not in {"openai_compatible"}:
        return False
    if spec.requires_api_key and not str(app_config.get(spec.config_key("api_key"), "") or "").strip():
        return False
    base_url = spec.resolve_base_url(str(app_config.get(spec.config_key("base_url"), "") or ""))
    if spec.requires_base_url and not base_url:
        return False
    model = spec.resolve_model_name(str(app_config.get(spec.config_key("model_name"), "") or ""))
    return not (spec.requires_model_name and not model)


def fallback_chain(primary: str, app_config: Mapping[str, Any]) -> list[str]:
    """Configured fallback providers, in order, excluding the primary.

    Empty in production (``RAILYARD_LIVE=1``): every LLM call goes through
    Relay, so the free direct providers are skipped and the deterministic
    fallbacks answer instead (Wave P PM1.5).
    """
    from app.integrations.railyard.provider_clients import relay_only

    if relay_only():
        return []
    primary = (primary or "").lower()
    seen: set[str] = set()
    chain: list[str] = []
    for pid in _chain_ids():
        if pid == primary or pid in seen:
            continue
        seen.add(pid)
        if is_configured(pid, app_config):
            chain.append(pid)
    return chain


def overlay(app_config: Mapping[str, Any], provider_id: str) -> dict[str, Any]:
    """A copy of ``app_config`` pointing at ``provider_id`` (never mutates the original)."""
    return {**dict(app_config), "llm_provider": provider_id}


# --------------------------------------------------------------------------- #
# Deterministic last resort
# --------------------------------------------------------------------------- #
def _clean(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip().strip("-*# ")
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def facts_from(texts: Iterable[str]) -> list[str]:
    """Up to :data:`MAX_FACTS` short sentences from the page facts, in order."""
    out: list[str] = []
    for text in texts:
        for part in _SENTENCE_RE.split(str(text or "")):
            sentence = _clean(part, MAX_FACT_CHARS)
            if len(sentence.split()) < 3 or sentence in out:
                continue
            out.append(sentence if sentence[-1] in ".!?" else f"{sentence}.")
            if len(out) >= MAX_FACTS:
                return out
    return out


def deterministic_script(subject: str, facts: Iterable[str] = (), language: str = "") -> str:
    """A plain narration from the subject and page facts (no invented claims)."""
    name = _clean(subject, 120) or "this"
    lines = facts_from(facts)
    if str(language or "").lower().startswith("tr"):
        opening, closing = f"{name} hakkında kısa bir bakış.", f"Daha fazlası için {name} sayfasına göz atın."
    else:
        opening, closing = f"Here is a quick look at {name}.", f"See more about {name} on its page."
    return "\n\n".join([opening, *lines, closing])


def deterministic_terms(subject: str, script: str = "", amount: int = 5) -> list[str]:
    """Stock-footage search terms from the subject's words (English-ish, 1-3 words)."""
    words = [w for w in _WORD_RE.findall(f"{subject} {script}") if w.lower() not in _STOP and len(w) > 2]
    head = " ".join(words[:2]) or "product"
    terms: list[str] = [head]
    for word in words[2:]:
        term = f"{words[0]} {word}" if words else word
        if term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
        if len(terms) >= amount:
            break
    for generic in ("close up hands", "person using phone", "city street", "office desk"):
        if len(terms) >= amount:
            break
        terms.append(generic)
    return terms[: max(1, amount)]


__all__ = [
    "DEFAULT_CHAIN",
    "deterministic_script",
    "deterministic_terms",
    "facts_from",
    "fallback_chain",
    "is_configured",
    "is_error",
    "overlay",
]
