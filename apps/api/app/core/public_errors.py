"""Turn internal error text into a short sentence that is safe to show people.

Route handlers historically build ``HttpException`` messages such as
``"<request_id>: invalid bearer token: <exc>"`` or
``"<request_id>: persistence layer is not available"``. That text is useful in
logs (``HttpException`` already logs it with the request id) but it should
never reach a user: it leaks request ids, header names, exception text and
provider errors.

``public_message`` is applied once, in the global exception handler, so every
route gets the same treatment without touching hundreds of raise sites. The
request id travels in its own ``request_id`` response field instead.

Rules:
- the ``"<request_id>: "`` prefix and ``"(correlation ...)"`` suffix are dropped;
- 401 always becomes a fixed sign-in sentence (auth failures never explain why);
- 5xx keeps only curated copy (a full sentence starting with a capital letter
  and ending in punctuation); anything else becomes a calm default;
- other 4xx keep the server text when it already reads like a plain sentence,
  otherwise its human head (the part before ``": <detail>"``) or a fixed
  sentence for the status code.
"""

from __future__ import annotations

import re
from typing import Iterable

DEFAULT_MESSAGE = "Something went wrong. Please try again."
MAX_PUBLIC_LENGTH = 200

_STATUS_MESSAGES: dict[int, str] = {
    400: "That request could not be used. Check it and try again.",
    401: "Please sign in to continue.",
    # Keep "not enough credits": mobile GenerationErrorNotice matches it to
    # offer the credit top-up.
    402: "Not enough credits. Add credits to keep going.",
    403: "You don't have access to this.",
    404: "We couldn't find that. It may have been removed.",
    405: "That action isn't available here.",
    408: "That took too long. Please try again.",
    409: "That changed while you were working. Refresh and try again.",
    410: "That is no longer available.",
    413: "That file is too large.",
    415: "That file type isn't supported.",
    416: "That part of the file isn't available.",
    422: "Some details aren't valid. Check them and try again.",
    423: "That is locked right now. Try again in a moment.",
    429: "Too many requests. Wait a moment and try again.",
    502: "A partner service didn't respond. Please try again in a moment.",
    503: "This is temporarily unavailable. Please try again in a few minutes.",
    504: "That took too long. Please try again.",
}
_SERVER_ERROR_MESSAGE = "Something went wrong on our side. Please try again in a moment."

# A leading "<id>: " prefix: uuids, hex ids and other opaque tokens that
# contain at least one digit (so ordinary words such as "Checkout:" survive).
_ID_PREFIX = re.compile(r"^\s*(?=[A-Za-z0-9._-]*\d)[A-Za-z0-9._-]{8,}:\s+")
_CORRELATION_SUFFIX = re.compile(r"\s*\(correlation[^)]*\)\s*$", re.IGNORECASE)
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")

# Text that marks a message as technical detail rather than a sentence.
_TECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{8,}\b", re.IGNORECASE),  # ids, hashes
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE),  # uuids
    re.compile(r"\bx-[a-z0-9-]+\b", re.IGNORECASE),  # header names (x-api-key)
    re.compile(r"\b(header|headers|bearer|authorization|jwt|jwks|token)\b", re.IGNORECASE),
    re.compile(r"\b(traceback|stack|exception|errno|assert)\b", re.IGNORECASE),
    re.compile(r"\b[A-Z][A-Za-z]*(Error|Exception|Warning)\b"),  # ValueError, ...
    re.compile(r"\bFile \"|\bline \d+\b"),  # python frames
    re.compile(r"\b(None|True|False|NaN|null|undefined)\b"),
    re.compile(r"[{}\[\]<>=`\\|]"),  # JSON, markup, code, key=value
    re.compile(r"https?://|www\.", re.IGNORECASE),
    re.compile(
        r"\b(sql|sqlalchemy|postgres|psycopg|redis|celery|enqueue|database|db|"
        r"persistence|orchestration|internal|backend|upstream|http \d{3}|status \d{3})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b"),  # snake_case identifiers
    re.compile(r"\b[a-z]+[A-Z][A-Za-z]+\b"),  # camelCase identifiers
    re.compile(r"\b\w+\.\w+\(|\w+\(\)"),  # calls such as mod.func( / func()
)


def status_message(status_code: int) -> str:
    """The fixed, human sentence for an HTTP status code."""
    if status_code in _STATUS_MESSAGES:
        return _STATUS_MESSAGES[status_code]
    if status_code >= 500:
        return _SERVER_ERROR_MESSAGE
    return DEFAULT_MESSAGE


def is_human_readable(text: str) -> bool:
    """True when ``text`` reads like a short sentence meant for people."""
    trimmed = text.strip()
    if not trimmed or len(trimmed) > MAX_PUBLIC_LENGTH:
        return False
    if "\n" in trimmed:
        return False
    return not any(pattern.search(trimmed) for pattern in _TECHNICAL_PATTERNS)


def _looks_curated(text: str) -> bool:
    """Deliberate user copy: a capitalised sentence with closing punctuation."""
    return bool(text) and text[0].isupper() and text.rstrip()[-1:] in ".!?"


def strip_request_ids(message: str, request_ids: Iterable[str] = ()) -> str:
    """Remove every known request id plus the generic ``"<id>: "`` prefix."""
    text = str(message or "")
    for raw_id in request_ids:
        request_id = str(raw_id) if raw_id is not None else ""
        if request_id:
            text = text.replace(f"{request_id}: ", "").replace(request_id, "")
    previous = None
    while previous != text:
        previous = text
        text = _ID_PREFIX.sub("", text)
    return _CORRELATION_SUFFIX.sub("", text).strip()


def _capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _human_candidate(text: str) -> str | None:
    """The message itself, or its human head, when it is safe to show."""
    candidates = [text]
    without_paren = _TRAILING_PAREN.sub("", text).strip()
    if without_paren and without_paren != text:
        candidates.append(without_paren)
    if ": " in text:
        candidates.append(text.split(": ", 1)[0].strip())
    for candidate in candidates:
        if candidate and is_human_readable(candidate):
            return _capitalise(candidate)
    return None


def public_message(
    status_code: int, message: str | None, request_ids: Iterable[str] = ()
) -> str:
    """Short, human text for an error response. Never empty."""
    text = strip_request_ids(message or "", request_ids)
    if status_code == 401:
        return status_message(401)
    if status_code >= 500:
        if _looks_curated(text) and is_human_readable(text):
            return text
        return status_message(status_code)
    candidate = _human_candidate(text) if text else None
    return candidate or status_message(status_code)
