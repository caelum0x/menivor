"""PURE deterministic lipsync provider selection.

:func:`choose_lipsync_provider` picks a lipsync ``provider_key`` from the set of
adapters the routing registry currently has ``available``, honoring the
commercial-use requirement. It is deterministic given its inputs: the same
``(image_meta, audio_meta, commercial, available)`` always yields the same key.

No DB, no network, no config — this mirrors the deterministic-core testing bias
used by ``consistency.py`` so the selection policy is exhaustively unit-testable.
The actual license/commercial classes come from :mod:`.licensing` (the single
source of truth), so selection and the controller gate can never disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domains.speak.licensing import is_commercial_ok

# Deterministic preference order. MuseTalk leads (fastest, real-time-class,
# open-commercial); LatentSync follows (higher fidelity, source-available).
# Selection walks this list in order so the choice is stable and explainable.
_PREFERENCE_ORDER: tuple[str, ...] = ("musetalk", "latentsync")


class NoLipsyncProviderError(RuntimeError):
    """No available lipsync provider satisfies the request constraints."""


def _normalize_available(available: Any) -> frozenset[str]:
    if not available:
        return frozenset()
    return frozenset(str(k).strip().lower() for k in available if str(k).strip())


def candidate_order(available: Any, *, commercial: bool) -> list[str]:
    """Return the ordered, filtered candidate keys for the given constraints.

    The result is the preference order intersected with ``available``, further
    filtered to commercial-safe providers when ``commercial`` is ``True``. Any
    available provider NOT in the preference list is appended (sorted) after the
    curated ones so a newly-registered provider is still reachable deterministically.
    """
    avail = _normalize_available(available)
    ordered = [k for k in _PREFERENCE_ORDER if k in avail]
    ordered += sorted(avail - set(_PREFERENCE_ORDER))
    if commercial:
        ordered = [k for k in ordered if is_commercial_ok(k)]
    return ordered


def choose_lipsync_provider(
    image_meta: Mapping[str, Any] | None,
    audio_meta: Mapping[str, Any] | None,
    *,
    commercial: bool,
    available: Any,
) -> str:
    """Choose a lipsync provider key deterministically, or raise.

    Args:
        image_meta: Reference-image metadata (reserved for future
            fidelity/aspect-aware routing; the selection is stable regardless).
        audio_meta: Driving-audio metadata (reserved, as above).
        commercial: When ``True`` only commercial-safe providers are eligible so
            a paid output can never route to research-only weights.
        available: The provider keys currently registered/available (set/list).

    Returns:
        The selected ``provider_key``.

    Raises:
        NoLipsyncProviderError: no available provider satisfies the constraints.
    """
    _ = (image_meta, audio_meta)  # reserved inputs; selection is metadata-stable
    ordered = candidate_order(available, commercial=commercial)
    if not ordered:
        raise NoLipsyncProviderError(
            "no available lipsync provider"
            + (" satisfies commercial licensing" if commercial else "")
        )
    return ordered[0]
