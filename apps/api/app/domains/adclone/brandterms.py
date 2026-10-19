"""Brand names the source ad shows or says: never allowed in our script (pure, no I/O).

Domains alone missed real brands (the source's "Velvele" reached a plan), so names come from:

* the creator handle in the link (``@velvele.official`` -> ``velvele``) and any ``@mention``;
* domains, and words marked with a trademark sign;
* printed text that is not a caption (logo / shirt print / product card: short overlay text);
* names after brand cues ("use code X at Y", "from Y", "Y ile") in OCR text and the transcript;
* capitalised names said or shown at least twice, or matching the handle.

Over-blocking only constrains our own writer (it picks other lines), so the rules lean wide.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

MIN_LEN = 3
_HANDLE_URL = re.compile(r"/@([A-Za-z0-9._-]{2,40})")
_MENTION = re.compile(r"@([A-Za-z0-9._]{3,40})")
_DOMAIN = re.compile(r"\b(?:www\.)?([\w-]{3,})\.(?:com|co|net|org|shop|store|io|com\.tr|tr|app|me)\b", re.I)
_TRADEMARK = re.compile(r"([A-Za-zÇĞİÖŞÜçğıöşü][\w'&-]{2,})\s?[®™©]")
_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü'&-]*")
_NAME = r"([A-ZÇĞİÖŞÜ][\w'&-]{2,}(?:\s+[A-ZÇĞİÖŞÜ][\w'&-]{2,}){0,2})"
_CUES = (
    re.compile(r"\b(?:at|from|by|on|visit|shop|wearing|wear|with|code\s+\S+\s+at)\s+" + _NAME),
    re.compile(_NAME + r"(?:'(?:den|dan|ten|tan|de|da|te|ta|nin|nın|nun|nün|in|ın|un|ün))?\s+(?:ile|markası|mağazası)\b"),
)
_HANDLE_JUNK = {"official", "store", "shop", "shopping", "tr", "turkey", "turkiye", "co", "the", "real", "app",
                "global", "world", "tv", "hq", "studio", "brand", "clothing", "wear", "fashion", "online", "com"}

# Common words that are capitalised at a sentence start or in shouty captions; never brand names.
_COMMON = set("""
a about after again all also am an and any are as at away back be because been before being best big
bro but by can check come could day did do does doing done don't down even every everything first for
from get go going gonna good got great guys had has have he hello here hey hi his how i if i'm in into
is it it's its just know last let life like look love made make man me more most much my need never new
next no not now of off oh ok okay on once one only or our out over people please pov price prices real
really right said same say see she so some still stop such take than thank thanks that that's the their
them then there these they thing think this those time to today too two up us use very wait want was way
we well were what when where which while who why will with wow yeah yes yet you you're your
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december god tiktok instagram youtube reels fyp foryou viral
bu bir ve ile da de ama çok cok ne bu şu su o ben sen biz siz onlar abi abla hadi evet hayır hayir
yok var gibi için icin daha en mi mı mu mü ki şimdi simdi bugün bugun yarın yarin dün dun her hiç hic
neden nasıl nasil kim kaç kac fiyat fiyatlar zam kira para lira tl anne baba teyze hala amca dayı dayi
""".split())


def _fold(text: str) -> str:
    """Lowercase ASCII fold (Rüya -> ruya, İ -> i) for comparisons."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def handle_from_url(url: str) -> str:
    m = _HANDLE_URL.search(url or "")
    return m.group(1) if m else ""


def handle_terms(handle: str) -> set[str]:
    """``velvele.official`` -> {velvele}; ``kumas_house`` -> {kumas, house, kumashouse}."""
    h = (handle or "").strip().lstrip("@").lower()
    if not h:
        return set()
    parts = [p for p in re.split(r"[._\-\d]+", h) if len(p) >= MIN_LEN and p not in _HANDLE_JUNK]
    out = set(parts)
    compact = re.sub(r"[^a-z]", "", h)
    for junk in sorted(_HANDLE_JUNK, key=len, reverse=True):
        if compact.endswith(junk) and len(compact) - len(junk) >= MIN_LEN:
            compact = compact[: -len(junk)]
    if len(compact) >= MIN_LEN and compact not in _HANDLE_JUNK:
        out.add(compact)
    return out


def _is_common(term: str) -> bool:
    words = _fold(term).split()
    return not words or all(w in _COMMON for w in words)


def _cue_names(text: str) -> set[str]:
    out = set()
    for rx in _CUES:
        for m in rx.finditer(text or ""):
            name = m.group(1).strip()
            if not _is_common(name):
                out.add(name)
    return out


def _capitalised(texts: Iterable[str]) -> Counter:
    """Capitalised words not at a sentence start, counted per occurrence."""
    counts: Counter = Counter()
    for text in texts:
        for sentence in re.split(r"(?<=[.!?…])\s+|\n", text or ""):
            words = _WORD.findall(sentence)
            for w in words[1:]:
                if w[:1].isupper() and not w.isupper() and len(w) >= MIN_LEN and not _is_common(w):
                    counts[w] += 1
    return counts


def _overlay_names(texts: Iterable[str]) -> set[str]:
    """Short printed text that is not a caption (logo, shirt print, card): its uncommon words."""
    out = set()
    for text in texts:
        words = _WORD.findall(text or "")
        if 1 <= len(words) <= 3:
            for w in words:
                if len(w) >= MIN_LEN and not _is_common(w):
                    out.add(w)
    return out


def extract(*, url: str = "", ocr_texts: Iterable[str] = (), overlay_texts: Iterable[str] = (),
            transcript: str = "", extra: Iterable[str] = ()) -> tuple[str, ...]:
    """Every brand-like name the source shows or says (lowercase, sorted, de-duplicated)."""
    ocr = [t for t in ocr_texts if t]
    texts = [*ocr, transcript or ""]
    terms: set[str] = {t.strip() for t in extra if t and t.strip()}
    handles = set()
    h = handle_from_url(url)
    if h:
        handles.add(h)
    for text in texts:
        handles.update(m.group(1) for m in _MENTION.finditer(text))
        terms.update(m.group(1) for m in _DOMAIN.finditer(text))
        terms.update(m.group(1) for m in _TRADEMARK.finditer(text))
        terms.update(_cue_names(text))
    handle_words: set[str] = set()
    for handle in handles:
        handle_words |= handle_terms(handle)
    terms |= handle_words
    terms |= _overlay_names(overlay_texts)
    counts = _capitalised(texts)
    for word, n in counts.items():
        folded = _fold(word)
        if n >= 2 or any(difflib.SequenceMatcher(None, folded, hw).ratio() >= 0.8 for hw in handle_words):
            terms.add(word)
    # Words matching the handle anywhere (OCR is often lower or upper case).
    for text in texts:
        for w in _WORD.findall(text):
            folded = _fold(w)
            if len(folded) >= 4 and any(difflib.SequenceMatcher(None, folded, hw).ratio() >= 0.85
                                        for hw in handle_words):
                terms.add(w)
    out = {_fold(t).strip() for t in terms}
    return tuple(sorted(t for t in out if len(t.replace(" ", "")) >= MIN_LEN and not _is_common(t)))


__all__ = ["extract", "handle_from_url", "handle_terms"]
