"""PURE license-class metadata + commercial-use gate for lipsync providers.

The single source of truth mapping a lipsync ``provider_key`` to its
:class:`LicenseClass`. A paid/commercial talking-video output must NEVER be
produced on research-only weights, so :func:`require_commercial_ok` fails closed
for a research-only provider before any credit is debited or job enqueued
(SHARED CONTRACT §8 — license-class gate).

Deterministic, no I/O — 100% unit-testable. This module never touches the DB,
network, or config; it is a static table plus predicates so the controller gate
and any deploy-time license check share one source of truth.

License classes (most-permissive → most-restricted)::

    open_commercial   Apache/MIT-style open weights — commercial output OK
    source_available  source-available license with commercial terms — OK
    non_commercial    non-commercial weights or dependencies — BLOCK for paid output
    research_only     research-only weights — BLOCK for paid output

MO1 (2026-09-29): ``latentsync`` is ``non_commercial`` until the MO12b fork
ships. Its ``face_detector.py`` uses InsightFace (non-commercial models) and the
1.6 weights are OpenRAIL++. The free/research path keeps it; paid output fails
closed. ``docs/THIRD_PARTY_MODELS.md`` is the human-readable register.
"""

from __future__ import annotations

from enum import Enum


class LicenseClass(str, Enum):
    """A lipsync model's license class, ordered most- → least-permissive."""

    OPEN_COMMERCIAL = "open_commercial"
    SOURCE_AVAILABLE = "source_available"
    NON_COMMERCIAL = "non_commercial"
    RESEARCH_ONLY = "research_only"


class LicenseClassError(ValueError):
    """A commercial/paid lipsync render was attempted on non-commercial weights."""

    def __init__(self, provider_key: str, license_class: "LicenseClass") -> None:
        self.provider_key = provider_key
        self.license_class = license_class
        super().__init__(
            f"lipsync provider {provider_key!r} is {license_class.value}; "
            "blocked for commercial/paid output"
        )


# License classes that permit a paid/commercial output.
_COMMERCIAL_OK: frozenset[LicenseClass] = frozenset(
    {LicenseClass.OPEN_COMMERCIAL, LicenseClass.SOURCE_AVAILABLE}
)

# provider_key -> LicenseClass. MuseTalk (MIT code and weights, no InsightFace)
# is the commercial-safe lipsync provider. ``latentsync`` is non-commercial until
# the MO12b MediaPipe-only fork ships (MO1). ``wav2lip`` is research-only and can
# never be selected for a paid render.
_PROVIDER_LICENSE: dict[str, LicenseClass] = {
    "musetalk": LicenseClass.OPEN_COMMERCIAL,
    "latentsync": LicenseClass.NON_COMMERCIAL,
    "wav2lip": LicenseClass.RESEARCH_ONLY,
}


def license_class_for(provider_key: str) -> LicenseClass | None:
    """Return the :class:`LicenseClass` for ``provider_key`` (or ``None``)."""
    return _PROVIDER_LICENSE.get(str(provider_key or "").strip().lower())


def is_commercial_ok(provider_key: str) -> bool:
    """True when a PAID/commercial output may be produced on this provider.

    An unknown provider is fail-closed (``False``) — a paid render can never run
    on a provider whose license class has not been reviewed and recorded here.
    """
    lic = license_class_for(provider_key)
    if lic is None:
        return False
    return lic in _COMMERCIAL_OK


def require_commercial_ok(provider_key: str) -> None:
    """Raise :class:`LicenseClassError` when ``provider_key`` is not commercial-safe.

    Called on the paid/commercial speak path BEFORE debit/enqueue so a research
    -only lipsync model can never back a paid talking-video render.
    """
    if not is_commercial_ok(provider_key):
        lic = license_class_for(provider_key) or LicenseClass.RESEARCH_ONLY
        raise LicenseClassError(str(provider_key or ""), lic)


def commercial_provider_keys() -> frozenset[str]:
    """The set of provider keys whose license class permits paid output."""
    return frozenset(k for k, v in _PROVIDER_LICENSE.items() if v in _COMMERCIAL_OK)


def known_provider_keys() -> frozenset[str]:
    """Every provider key with a recorded license class (any class)."""
    return frozenset(_PROVIDER_LICENSE)
