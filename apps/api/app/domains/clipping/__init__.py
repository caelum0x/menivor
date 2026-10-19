"""Long-form -> short-form auto-clipping domain (ReelForge).

A thin orchestrator that turns one long recording into several vertical,
caption-burned short clips:

    transcribe (WhisperX word timings)
      -> detect viral moments / rank segments (reuse repurpose policy)
      -> plan cut points snapped to word boundaries
      -> reframe each window to vertical + burn captions (reuse services/compose)
      -> optionally stitch with cross-fades (services/compose/transitions)
      -> persist a draft (+ optional publish handoff).

The brain / audio / asset-manager stages of the upstream ai-shorts-generator are
deliberately NOT re-ported here — those responsibilities are already covered by
``services/script``, ``services/tts`` and ``services/broll``. This package only
adds the clipping-specific orchestration + pure planning logic.
"""

from .router import router

__all__ = ["router"]
