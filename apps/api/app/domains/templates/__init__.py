"""Genre shot-template engine — Higgsfield-class one-click viral formats.

Turns named viral genres (Minecraft×Reddit split, ASMR loop, movie recap, fake
podcast…) into pipeline-ready reels: each template is a versioned segment-slot
graph (Hook / Rising / Payoff / Loop) that the compiler expands into a timed
RenderSpec and the ``instantiate`` bridge maps onto the existing reel pipeline.

The package ``__init__`` re-exports the APIRouter (mirroring other domains) so
``from app.domains.templates import router`` yields the router module attribute.
"""

from __future__ import annotations

from .router import router

__all__ = ["router"]
