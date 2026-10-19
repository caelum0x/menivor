"""Shared, JSON-serialisable job context passed between chain stages (§6.2).

The ``JobContext`` is a plain dict threaded through the Celery chain: each
stage task returns ``{**ctx, **stage_result}`` and that dict becomes the first
positional argument of the next task. It MUST stay JSON-safe at all times —
never place live objects (e.g. a ``SubMaker``) in it. ElevenLabs word timings
are flattened to ``list[[text, start_s, end_s]]`` before they enter the context.

This module owns:
  * the ``JobContext`` TypedDict (the authoritative shape),
  * ``new_context`` — seed the initial context from job id + params,
  * ``dumps_context`` / ``loads_context`` — explicit JSON (de)serialisation,
  * ``merge_partials`` — fan-in helper for the chord callback (avatar+captions).
"""

from __future__ import annotations

import json
from typing import Any, TypedDict


class JobContext(TypedDict, total=False):
    """JSON-serialisable state threaded through the Celery pipeline.

    ``total=False``: every key is optional and is populated by the stage that
    produces it. ``audio_duration`` is the SINGLE TIMING AUTHORITY (§8/§9).
    """

    job_id: str
    params: dict  # ReelForgeParams.__dict__
    # script stage
    script: str
    # tts stage (audio_duration is the SINGLE TIMING AUTHORITY, §9)
    audio_key: str
    audio_url: str  # public R2 URL (HeyGen needs a URL)
    audio_duration: float
    words: list  # [[text, start_s, end_s], ...] from ElevenLabs alignment
    # avatar stage (parallel)
    avatar_key: str
    avatar_video: str  # local path (re-hosted from HeyGen)
    avatar_duration: float
    # captions stage (parallel)
    ass_key: str
    ass_path: str  # local path
    # compose stage
    final_key: str
    final_video: str
    # upload stage
    upload_results: list
    request_id: str


# Keys produced by the parallel avatar/captions stages. The chord callback
# (compose) must union these across both partial contexts.
_AVATAR_KEYS: tuple[str, ...] = ("avatar_key", "avatar_video", "avatar_duration")
_CAPTION_KEYS: tuple[str, ...] = ("ass_key", "ass_path")


def new_context(job_id: str, params: dict, request_id: str = "") -> JobContext:
    """Seed the initial context for a pipeline run.

    Args:
        job_id: Owning ``Job.id``.
        params: ``ReelForgeParams.__dict__`` (already JSON-safe; ``platforms``
            is a tuple that json serialises as a list).

    Returns:
        A fresh ``JobContext`` carrying ``job_id``, ``params``, and the stable
        request correlation id when supplied.
    """
    context: JobContext = {"job_id": job_id, "params": dict(params)}
    if request_id:
        context["request_id"] = request_id
    return context


def dumps_context(ctx: dict) -> str:
    """Serialise a context dict to a compact JSON string.

    Raises ``TypeError`` if the context contains a non-JSON-serialisable value
    — this is intentional: it surfaces a contract violation (a live object leaked
    into the context) at the boundary rather than deep inside a worker.
    """
    return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))


def loads_context(raw: str) -> JobContext:
    """Deserialise a JSON string back into a ``JobContext``.

    Raises ``ValueError`` when the payload is not a JSON object.
    """
    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(
            f"JobContext must deserialize to an object, got {type(data).__name__}"
        )
    return data  # type: ignore[return-value]


def merge_partials(partials: list[dict]) -> JobContext:
    """Fan-in the parallel avatar + captions partial contexts (§6.3).

    The chord callback receives ``[avatar_ctx, captions_ctx]`` (order not
    guaranteed). Both partials share the same base keys (job_id, params, script,
    audio_*, words) because each was derived from the same upstream tts context;
    they differ only in the ``avatar_*`` vs ``ass_*`` keys. We union them into a
    single context, letting the avatar-specific and caption-specific keys land
    from whichever partial carries them.

    Args:
        partials: The list of partial ``JobContext`` dicts from the group.

    Returns:
        A single merged ``JobContext``.

    Raises:
        ValueError: If ``partials`` is empty or contains a non-dict element.
    """
    if not partials:
        raise ValueError("merge_partials requires at least one partial context")

    merged: dict = {}
    for partial in partials:
        if not isinstance(partial, dict):
            raise ValueError(
                f"chord partial must be a dict, got {type(partial).__name__}"
            )
        # Base keys are identical across partials; a plain update is safe and
        # keeps the last-writer value for shared keys while accumulating the
        # stage-specific avatar_*/ass_* keys from each side.
        merged.update(partial)
    return merged  # type: ignore[return-value]
