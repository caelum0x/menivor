"""Multi-reference video requests and the structured shot brief (pure, no I/O).

Image-to-video and reference-to-video models (Seedance 2.0 i2v/r2v) follow a
prompt far better when it is written as a short brief than as a paragraph. The
brief order follows the Very ___ Time method (Kapwing formula)::

    Format: 9:16, 5 s, 720p.
    Reference roles: @Image1 is the first frame. @Image2 locks the subject's ...
    Action: one small action, cause then effect.
    Camera: locked-off.
    Continuity: same shirt, same glasses.
    Audio: room tone + one diegetic SFX; no music.
    Constraints: no new people, no text appearing.

References are numbered ``@Image1``, ``@Image2`` ... in the order returned by
:func:`ordered_references` (the first frame always comes first). Callers must
send the provider the reference URLs in that same order so the names in the
brief point at the right images.

A reference is either a public ``https`` URL or an internal storage (R2) key.
URL checks here are syntactic: scheme, credentials, blocked host names and
literal private, loopback, link-local or reserved addresses. Keys are only
syntax-checked here; the caller checks ownership and presigns them.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

ROLE_FIRST_FRAME = "first_frame"
ROLE_IDENTITY = "identity"
ROLE_STYLE = "style"
ROLE_GARMENT = "garment"
ROLES: tuple[str, ...] = (ROLE_FIRST_FRAME, ROLE_IDENTITY, ROLE_STYLE, ROLE_GARMENT)

MAX_REFERENCES = 4
MAX_URL_LENGTH = 1000
MAX_FIELD_CHARS = 600
MAX_BRIEF_CHARS = 2000
BRIEF_FIELDS: tuple[str, ...] = ("format", "action", "camera", "continuity", "audio", "constraints")

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.\-]{0,499}$")
_BLOCKED_HOSTS = frozenset({
    "localhost", "metadata", "metadata.google.internal", "metadata.goog",
    "instance-data", "instance-data.ec2.internal",
})
_BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".lan", ".home.arpa")


class BriefError(ValueError):
    """A reference list or brief is not usable; the message is safe to show a user."""


@dataclass(frozen=True)
class Reference:
    """One reference image and the narrow job it has in the shot."""

    url: str   # https URL, or an internal storage key before presigning
    role: str  # first_frame | identity | style | garment

    def __post_init__(self) -> None:
        role = str(self.role or "").strip().lower()
        if role not in ROLES:
            raise BriefError(f"reference role must be one of {', '.join(ROLES)}")
        url = str(self.url or "").strip()
        if not url:
            raise BriefError("a reference needs a url or a storage key")
        if not (is_storage_key(url) or _is_public_https(url)):
            raise BriefError("a reference must be a public https URL or one of your uploaded files")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "url", url)

    @property
    def is_key(self) -> bool:
        return is_storage_key(self.url)


def is_storage_key(value: str) -> bool:
    """True for an internal object key such as ``uploads/u1/still.png`` (no scheme, no ``..``)."""
    text = str(value or "")
    return "://" not in text and ".." not in text and "//" not in text and bool(_KEY_RE.match(text))


def _is_public_https(url: str) -> bool:
    if len(url) > MAX_URL_LENGTH or any(ord(ch) < 33 or ch == "\\" for ch in url):
        return False
    try:
        parsed = urlparse(url)
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.strip().lower().rstrip(".")
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return False
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return True  # a host name; the provider, not this server, fetches it
    return literal.is_global


def public_https_url(url: str) -> bool:
    """Public wrapper used by the gateway for a plain ``image_url``."""
    return _is_public_https(str(url or "").strip())


def parse_references(raw: Sequence[Mapping[str, Any] | Reference] | None) -> tuple[Reference, ...]:
    """Validate a client reference list; at most :data:`MAX_REFERENCES` and one first frame."""
    items = list(raw or [])
    if len(items) > MAX_REFERENCES:
        raise BriefError(f"at most {MAX_REFERENCES} reference images per shot")
    refs: list[Reference] = []
    for item in items:
        if isinstance(item, Reference):
            refs.append(item)
            continue
        if not isinstance(item, Mapping):
            raise BriefError("each reference must be an object with url and role")
        url = item.get("url") if item.get("url") is not None else item.get("key")
        refs.append(Reference(url=str(url or ""), role=str(item.get("role") or "")))
    if sum(1 for r in refs if r.role == ROLE_FIRST_FRAME) > 1:
        raise BriefError("only one reference can be the first frame")
    return tuple(refs)


def ordered_references(refs: Sequence[Reference]) -> tuple[Reference, ...]:
    """The first frame first, the rest in the order given (this is the @ImageN order)."""
    first = [r for r in refs if r.role == ROLE_FIRST_FRAME]
    rest = [r for r in refs if r.role != ROLE_FIRST_FRAME]
    return (*first, *rest)


def _clean(text: str, cap: int = MAX_FIELD_CHARS) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:cap].rstrip()


def _role_line(index: int, ref: Reference) -> str:
    name = f"@Image{index}"
    if ref.role == ROLE_FIRST_FRAME:
        return f"{name} is the first frame."
    if ref.role == ROLE_IDENTITY:
        return (f"{name} locks the subject's face, hair and clothing; "
                f"do not copy {name}'s background.")
    if ref.role == ROLE_GARMENT:
        return (f"{name} shows the garment: copy its cut, colour, fabric and print exactly; "
                f"ignore {name}'s background and anyone wearing it.")
    return (f"{name} sets the look only (palette, texture, lighting); "
            f"do not copy {name}'s subject or layout.")


def build_brief_prompt(
    *,
    format: str,  # noqa: A002 - the method doc calls this block "Format"
    references: Sequence[Reference],
    action: str,
    camera: str = "",
    continuity: str = "",
    audio: str = "",
    constraints: str = "",
) -> str:
    """Render the structured brief (Format / Reference roles / Action / Camera / ...).

    ``format`` and ``action`` are required. Empty optional blocks are left out.
    Each block is flattened to one line and capped at :data:`MAX_FIELD_CHARS`;
    the whole brief is capped at :data:`MAX_BRIEF_CHARS`.
    """
    fmt, act = _clean(format), _clean(action)
    if not fmt:
        raise BriefError("the brief needs a format (for example: 9:16, 5 s, 720p)")
    if not act:
        raise BriefError("the brief needs an action")
    refs = ordered_references(parse_references(references))
    lines = [f"Format: {fmt}"]
    if refs:
        roles = " ".join(_role_line(i, r) for i, r in enumerate(refs, start=1))
        lines.append(f"Reference roles: {roles}")
    lines.append(f"Action: {act}")
    for label, value in (("Camera", camera), ("Continuity", continuity),
                         ("Audio", audio), ("Constraints", constraints)):
        text = _clean(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)[:MAX_BRIEF_CHARS].rstrip()


def brief_from_mapping(brief: Mapping[str, Any], references: Sequence[Reference]) -> str:
    """:func:`build_brief_prompt` from a ``{format, action, camera, ...}`` mapping."""
    if not isinstance(brief, Mapping):
        raise BriefError("brief must be an object")
    unknown = set(brief) - set(BRIEF_FIELDS)
    if unknown:
        raise BriefError(f"unknown brief field(s): {', '.join(sorted(unknown))}")
    values = {name: str(brief.get(name) or "") for name in BRIEF_FIELDS}
    return build_brief_prompt(references=references, **values)


__all__ = [
    "BRIEF_FIELDS", "BriefError", "MAX_BRIEF_CHARS", "MAX_FIELD_CHARS", "MAX_REFERENCES", "ROLES",
    "ROLE_FIRST_FRAME", "ROLE_GARMENT", "ROLE_IDENTITY", "ROLE_STYLE", "Reference", "brief_from_mapping",
    "build_brief_prompt", "is_storage_key", "ordered_references", "parse_references", "public_https_url",
]
