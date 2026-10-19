"""URL → reel ingestion: turn a product/article URL into a ready reel draft.

Fetches a page, extracts its title/description/key points, and assembles a UGC
reel draft (subject + hook-first script + b-roll prompts) the client submits to
``POST /jobs``. Fetch + optional LLM rewrite are injectable seams; extraction and
the template script are pure and tested.
"""

from .router import router

__all__ = ["router"]
