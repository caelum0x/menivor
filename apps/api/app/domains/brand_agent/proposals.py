"""Setup-step proposals: site analysis + search results -> one draft per memory section.

Deterministic first (only what the site and the search results say), then an
optional single LLM pass through Relay that may improve wording. Every proposal
is normalized by :func:`memory.normalize` (bounded, scrubbed) before it is shown.

Market framing: a competitor the brand's own site names (for example "drop-in
compatible with X", "migrate from X") is marked ``relationship="switch_source"``
- the place its customers are likeliest to come from - not only a rival.
Comparisons stay to facts both sites publish, with no affiliation implied.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse

from app.domains.adstudio.extract import clean_text
from app.domains.brand_agent import copy_rules, memory

_TITLE_SPLIT_RE = re.compile(r"\s+[|\-–—:·]\s+|:\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_JSON_RE = re.compile(r"\{.*\}", re.S)
_SKIP_HOSTS = ("wikipedia.org", "youtube.com", "reddit.com", "linkedin.com", "facebook.com", "x.com",
               "twitter.com", "medium.com", "g2.com", "capterra.com", "producthunt.com", "github.com")

#: (cue regex, pain) - read from the site's own words, never invented.
PAIN_CUES: tuple[tuple[str, str], ...] = (
    (r"lock-?in|export|yours to (?:take|keep)|own your data", "Vendor lock-in with no easy way to export their data"),
    (r"\bflat\b|no usage|surprise|predictable", "Unpredictable usage-based bills"),
    (r"\bagents?\b|\bmcp\b|\bcli\b", "Backend setup that slows their coding agent down"),
    (r"one command|minutes|before you sign up|no setup", "Too many setup steps before the first deploy"),
    (r"free (?:trial|plan|tier)|start free", "Paying before they can try it"),
    (r"compatib|drop-?in|migrat", "Switching tools means rewriting their app"),
)
FALLBACK_PAIN = "Too little time to do everything themselves"

SEGMENTS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "Developer tools: backend platform": ("Founders building with coding agents", "Small teams shipping web and mobile apps",
                                          "App studios running many client projects"),
    "Marketing: AI video and ads": ("Founders marketing their own product", "Small marketing teams", "App studios"),
    "Mobile app": ("Mobile app developers", "App studios", "Early-stage founders"),
}
DEFAULT_SEGMENTS = ("Early-stage founders", "Small teams")


def _host(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def positioning(analysis: dict[str, Any]) -> dict[str, Any]:
    logo = analysis.get("logo") or {}
    return memory.normalize(memory.SECTION_POSITIONING, {
        "name": analysis.get("name", ""),
        "category": analysis.get("category", ""),
        "one_liner": analysis.get("one_liner", ""),
        "pricing_hook": analysis.get("pricing_hook", ""),
        "colors": analysis.get("colors", []),
        "fonts": analysis.get("fonts", []),
        "logo_url": logo.get("url", "") if isinstance(logo, dict) else "",
    })


def product(analysis: dict[str, Any]) -> dict[str, Any]:
    features = list(analysis.get("features") or []) or list(analysis.get("headings") or [])[1:6]
    return memory.normalize(memory.SECTION_PRODUCT, {"products": [{
        "name": analysis.get("name", ""),
        "what_it_is": analysis.get("description") or analysis.get("one_liner", ""),
        "key_features": features,
    }]})


def market_queries(analysis: dict[str, Any]) -> list[str]:
    name = analysis.get("name", "")
    category = str(analysis.get("category", "")).split(":")[-1].strip()
    queries = [f"{name} alternatives" if name else "", f"best {category}" if category else ""]
    return [q for q in queries if q]


def _corpus(analysis: dict[str, Any]) -> str:
    parts: list[str] = [analysis.get("description", ""), analysis.get("one_liner", "")]
    for key in ("sample_lines", "headings", "features"):
        parts.extend(analysis.get(key) or [])
    return " ".join(str(p) for p in parts).lower()


def _competitor_name(title: str) -> str:
    return clean_text(_TITLE_SPLIT_RE.split(title or "")[0], 120)


def market(analysis: dict[str, Any], results: Iterable[dict[str, str]], *, search_enabled: bool) -> dict[str, Any]:
    own = _host(analysis.get("website_url", ""))
    corpus = _corpus(analysis)
    competitors: list[dict[str, str]] = []
    seen: set[str] = set()
    insights: list[str] = []
    sources: list[str] = []
    for item in results:
        host = _host(item.get("url", ""))
        if not host or host == own or host.endswith("." + own) or any(host.endswith(s) for s in _SKIP_HOSTS):
            continue
        if host in seen:
            continue
        seen.add(host)
        name = _competitor_name(item.get("title", ""))
        if not name:
            continue
        named_on_site = name.split()[0].lower() in corpus
        competitors.append({
            "name": name,
            "url": f"https://{host}/",
            "note": clean_text(_SENTENCE_RE.split(item.get("snippet", ""))[0], 200),
            "relationship": "switch_source" if named_on_site else "competitor",
        })
        sources.append(item.get("url", ""))
    switch = [c["name"] for c in competitors if c["relationship"] == "switch_source"]
    if switch:
        insights.append(f"Your site names {', '.join(switch)}: teams already using them are the likeliest switchers.")
    if competitors:
        insights.append("Compare only on facts both sites publish (price, features, export), and never imply "
                        "an affiliation.")
    elif not search_enabled:
        insights.append("Web search is off on this server, so add the competitors you know and I'll keep them.")
    else:
        insights.append("The search found no clear competitors; add the ones you know.")
    return memory.normalize(memory.SECTION_MARKET, {"competitors": competitors, "insights": insights,
                                                    "sources": sources})


def _tone(lines: list[str]) -> list[str]:
    tone: list[str] = []
    if lines and sum(len(line.split()) for line in lines) / len(lines) <= 14:
        tone.append("Short, direct sentences")
    if any(re.search(r"\byou(?:r)?\b", line, re.I) for line in lines):
        tone.append("Speaks to the reader as \"you\"")
    if any(re.search(r"[$€£]\s?\d|\d+%|\b\d+\b", line) for line in lines):
        tone.append("Concrete numbers")
    return tone or ["Plain and factual"]


def pains_from(analysis: dict[str, Any]) -> list[str]:
    corpus = _corpus(analysis)
    pains = [pain for cue, pain in PAIN_CUES if re.search(cue, corpus, re.I)]
    return pains[:4] or [FALLBACK_PAIN]


def voice_audience(analysis: dict[str, Any]) -> dict[str, Any]:
    lines = list(analysis.get("sample_lines") or [])[:6]
    names = SEGMENTS_BY_CATEGORY.get(str(analysis.get("category", "")), DEFAULT_SEGMENTS)
    pains = pains_from(analysis)
    return memory.normalize(memory.SECTION_VOICE, {
        "sample_lines": lines,
        "tone": _tone(lines),
        "segments": [{"name": name, "pains": pains[:3]} for name in names],
    })


def build_all(analysis: dict[str, Any], results: list[dict[str, str]], *, search_enabled: bool) -> dict[str, Any]:
    return {
        memory.SECTION_POSITIONING: positioning(analysis),
        memory.SECTION_PRODUCT: product(analysis),
        memory.SECTION_MARKET: market(analysis, results, search_enabled=search_enabled),
        memory.SECTION_VOICE: voice_audience(analysis),
    }


# --------------------------------------------------------------------------- #
# LLM pass (Relay only) and edits
# --------------------------------------------------------------------------- #
def parse_json(text: str) -> dict[str, Any]:
    match = _JSON_RE.search(text or "")
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def merge(section: str, base: dict[str, Any], override: Any) -> dict[str, Any]:
    """``base`` with the non-empty keys of ``override`` (new dict, normalized)."""
    if not isinstance(override, dict):
        return dict(base)
    combined = {**base, **{k: v for k, v in override.items() if v not in (None, "", [], {})}}
    return memory.normalize(section, combined)


def enrich(llm: Any, analysis: dict[str, Any], results: list[dict[str, str]],
           drafts: dict[str, Any]) -> dict[str, Any]:
    """One optional LLM pass over all drafts; any failure keeps the drafts."""
    if llm is None:
        return drafts
    prompt = (
        "Improve these brand-setup drafts using only the website facts and search results below. "
        "Keep every fact verifiable. Reply with JSON only, shaped like the drafts (omit a section to keep it).\n"
        f"WEBSITE FACTS: {json.dumps(_facts(analysis))[:6000]}\n"
        f"SEARCH RESULTS: {json.dumps(results[:8])[:4000]}\n"
        f"DRAFTS: {json.dumps(drafts)[:6000]}"
    )
    reply = parse_json(llm.complete(copy_rules.SYSTEM_PROMPT, prompt))
    return {section: merge(section, drafts[section], reply.get(section)) for section in drafts}


def _facts(analysis: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "website_url", "description", "one_liner", "category", "pricing_hook", "sample_lines",
            "headings", "features")
    return {k: analysis.get(k) for k in keys}


_KEY_ALIASES = {
    "one-liner": "one_liner", "one liner": "one_liner", "positioning": "one_liner", "pricing": "pricing_hook",
    "price": "pricing_hook", "category": "category", "colors": "colors", "colours": "colors", "fonts": "fonts",
    "name": "name", "competitors": "competitors", "audience": "segments", "segments": "segments",
    "tone": "tone", "features": "key_features", "what it is": "what_it_is",
    "switch from": "switch_sources", "switchers from": "switch_sources", "switch sources": "switch_sources",
}
_AUDIENCE_LEAD_RE = re.compile(
    r"^(?:no[,.]?\s*)?(?:change it to|change the audience to|change our audience to|"
    r"(?:our|the|my)\s+(?:target\s+)?audience\s+(?:is|are|should be)|audience\s*(?:is|are|:)|"
    r"it(?:'s| is) for|target)\s*",
    re.I,
)
_CALLED_RE = re.compile(r"\b(?:called|named|name is)\s+(.+)$", re.I)


def _split_list(value: str) -> list[str]:
    return [clean_text(p, 160) for p in re.split(r"[;\n]|,\s*(?![^()]*\))", value) if clean_text(p, 160)]


def _key_values(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in re.split(r"[\n;]+", text):
        key, sep, value = line.partition(":")
        alias = _KEY_ALIASES.get(key.strip().lower())
        if sep and alias and value.strip():
            out[alias] = value.strip()
    return out


def audience_segments(text: str, keep_pains: list[str]) -> list[dict[str, Any]]:
    """Free-text audience correction -> segments (one per line / semicolon)."""
    body = _AUDIENCE_LEAD_RE.sub("", text.strip()).strip().rstrip(".")
    names = [n.strip() for n in re.split(r"[;\n]+", body) if n.strip()] or [body]
    return [{"name": clean_text(n[:1].upper() + n[1:], 120), "pains": keep_pains[:3]} for n in names if n]


def _with_switch_sources(proposal: dict[str, Any], names: list[str]) -> dict[str, Any]:
    """Mark ``names`` as where switchers come from (added when missing); others stay competitors."""
    wanted = {n.lower(): n for n in names}
    competitors = []
    for comp in proposal.get("competitors", []):
        key = next((k for k in wanted if comp.get("name", "").lower().startswith(k)), None)
        if key:
            competitors.append({**comp, "relationship": "switch_source"})
            wanted.pop(key)
        else:
            competitors.append(dict(comp))
    added = [{"name": n, "url": "", "note": "added by you", "relationship": "switch_source"}
             for n in wanted.values()]
    insight = (f"Teams already on {' and '.join(names)} are the likeliest switchers. Compare only on facts both "
               "sites publish, and never imply an affiliation.")
    stale = ("likeliest switchers", "found no clear competitors", "Web search is off")
    insights = [insight, *[i for i in proposal.get("insights", []) if not any(x in i for x in stale)]]
    return memory.normalize(memory.SECTION_MARKET, {**proposal, "competitors": [*added, *competitors],
                                                    "insights": insights})


def apply_feedback(section: str, proposal: dict[str, Any], text: str) -> dict[str, Any]:
    """Deterministic revision from the user's correction (no LLM needed)."""
    pairs = _key_values(text)
    if section == memory.SECTION_VOICE:
        pains = [p for seg in proposal.get("segments", []) for p in seg.get("pains", [])]
        unique_pains = list(dict.fromkeys(pains))
        if "tone" in pairs:
            return memory.normalize(section, {**proposal, "tone": _split_list(pairs["tone"])})
        source = pairs.get("segments", text)
        return memory.normalize(section, {**proposal, "segments": audience_segments(source, unique_pains)})
    if section == memory.SECTION_PRODUCT:
        products = [dict(p) for p in proposal.get("products", [])] or [{"name": "", "what_it_is": "",
                                                                       "key_features": []}]
        first = dict(products[0])
        called = _CALLED_RE.search(text)
        if "name" in pairs or called:
            first["name"] = pairs.get("name") or called.group(1).strip().rstrip(".")
        if "what_it_is" in pairs:
            first["what_it_is"] = pairs["what_it_is"]
        if "key_features" in pairs:
            first["key_features"] = _split_list(pairs["key_features"])
        if not (pairs or called):
            first["what_it_is"] = text
        return memory.normalize(section, {"products": [first, *products[1:]]})
    if section == memory.SECTION_MARKET:
        if "switch_sources" in pairs:
            return _with_switch_sources(proposal, _split_list(pairs["switch_sources"]))
        if "competitors" in pairs:
            names = _split_list(pairs["competitors"])
            return memory.normalize(section, {**proposal, "competitors": [
                {"name": n, "url": "", "note": "added by you", "relationship": "competitor"} for n in names]})
        return memory.normalize(section, {**proposal, "insights": [text, *proposal.get("insights", [])]})
    updates: dict[str, Any] = {}
    for key, value in pairs.items():
        updates[key] = _split_list(value) if key in {"colors", "fonts"} else value
    if not updates:
        updates = {"one_liner": text}
    return memory.normalize(section, {**proposal, **updates})


def revise(llm: Any, section: str, proposal: dict[str, Any], feedback: str) -> dict[str, Any]:
    """LLM revision when Relay is configured, else :func:`apply_feedback`."""
    if llm is not None:
        prompt = (f"Revise the '{section}' brand memory draft using the user's correction. Keep facts "
                  f"verifiable. Reply with JSON only, same shape.\nDRAFT: {json.dumps(proposal)[:6000]}\n"
                  f"CORRECTION: {feedback[:2000]}")
        reply = parse_json(llm.complete(copy_rules.SYSTEM_PROMPT, prompt))
        if reply:
            return merge(section, proposal, reply.get(section, reply))
    return apply_feedback(section, proposal, feedback)


__all__ = [
    "apply_feedback",
    "audience_segments",
    "build_all",
    "enrich",
    "market",
    "market_queries",
    "merge",
    "pains_from",
    "parse_json",
    "positioning",
    "product",
    "revise",
    "voice_audience",
]
