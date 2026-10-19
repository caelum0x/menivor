"""Repurposing engine: long video -> transcript -> LLM-ranked highlight clips.

A creator submits a long recording; ReelForge transcribes it, ranks transcript
windows for virality, and surfaces the top non-overlapping short-form cuts — each
promotable into a reel/generation job. Transcription and ranking are seams
(injectable); the highlight selection is a pure, exhaustively-tested policy.
"""

from .router import router

__all__ = ["router"]
