"""Count full H.264 encodes per reel (M1.2 acceptance metric).

``stage_compose`` opens a :func:`tally` around one reel; every step that writes
a full video encode calls :func:`count` with a short kind (``scene``,
``loop_mix``, ``compose``, ``broll``, ``screen_prep``). Outside a tally the
calls are no-ops, so tools and tests that call the builders directly pay
nothing. Stream copies, the poster JPEG and still plates are not counted.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Iterator

_ACTIVE: ContextVar[dict[str, int] | None] = ContextVar("menivor_encode_tally", default=None)


@contextlib.contextmanager
def tally() -> Iterator[dict[str, int]]:
    """Collect ``{kind: count}`` for the encodes run inside the block."""
    counts: dict[str, int] = {}
    token = _ACTIVE.set(counts)
    try:
        yield counts
    finally:
        _ACTIVE.reset(token)


def count(kind: str) -> None:
    """Record one full encode of ``kind`` in the active tally (if any)."""
    counts = _ACTIVE.get()
    if counts is not None:
        counts[kind] = counts.get(kind, 0) + 1


def total(counts: dict[str, int]) -> int:
    """All full encodes in ``counts``."""
    return sum(int(value) for value in counts.values())


__all__ = ["count", "tally", "total"]
