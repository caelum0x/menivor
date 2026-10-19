"""ReelForge script-generation services.

Exposes the UGC-creator script generator that wraps MPT's single LLM
choke point (``app.services.llm._generate_response``).
"""

from app.services.script.ugc import (
    MAX_UGC_SUBJECT_LENGTH,
    UGC_SEGMENT_MAX,
    UGC_SEGMENT_MIN,
    UGC_WORDS_PER_SECOND,
    build_ugc_script_prompt,
    generate_ugc_script,
)

__all__ = [
    "MAX_UGC_SUBJECT_LENGTH",
    "UGC_SEGMENT_MAX",
    "UGC_SEGMENT_MIN",
    "UGC_WORDS_PER_SECOND",
    "build_ugc_script_prompt",
    "generate_ugc_script",
]
