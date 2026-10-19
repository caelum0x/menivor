"""Reddit thread → reel story domain (HTTP facade re-exports the router).

Fetches a Reddit thread via an injectable HTTP transport, cleans + narrates it
into a single word-capped script, and binds it to the ``minecraft-reddit-split``
template — emitting a submittable reel draft per the shared story contract. Fetch
is the only impure seam; parsing, the narration builder and the draft/param fold
are pure and unit-tested.
"""

from .router import router

__all__ = ["router"]
