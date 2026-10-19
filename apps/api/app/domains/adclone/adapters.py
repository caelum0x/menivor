"""Dry-run adapters: ``dry_run(plan) -> per-shot requests`` for the /ad-clone/render dry run.

Paid renders never go through these: every engine's paid path (Kling in :mod:`kling`, Replicate,
Higgsfield-Kling, MiniMax Hailuo and RunPod Wan + InfiniteTalk in :mod:`engine_clients`) runs only in
the render worker after an approval (credits held, cost cap, Idempotency-Key). ``render_shot`` here
refuses so an HTTP request can never spend directly.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from .kling import KlingClient


class EngineNotReady(RuntimeError):
    status_code = 409


class _Stub:
    name = ""
    request_shape: dict[str, Any] = {}

    def dry_run(self, plan: Mapping[str, Any]) -> list[dict]:
        return [{"shot": s["id"], "engine": self.name, "seconds": int(s["dur"]),
                 "first_frame": (s.get("refs") or [None])[0], "lines": list(s.get("lines") or []),
                 "request": dict(self.request_shape)} for s in plan.get("shots") or []]

    def render_shot(self, **_: Any) -> dict:
        raise EngineNotReady(f"{self.name}: paid renders run in the worker after POST /ad-clone/render/approve")


class HiggsfieldKling(_Stub):
    name = "higgsfield_kling"
    request_shape = {"endpoint": "cloud.higgsfield.ai kling image-to-video", "lip_sync": "separate pass"}


class RunpodWan(_Stub):
    name = "runpod_wan"
    request_shape = {"worker": "wan22-i2v + infinitetalk (infra/render-workers/registry.yaml)",
                     "voice": "ElevenLabs or Chatterbox/Kokoro track drives the lips"}


class MinimaxHailuo(_Stub):
    name = "minimax_hailuo"
    request_shape = {"model": "hailuo (768p)", "audio_reference": "our line audio"}


class ReplicateEpisode:
    name = "replicate"

    def command(self, plan_path: str, tier: str = "standard") -> str:
        return f"cd work && python3 make_episode.py {shlex.quote(plan_path)} --tier {shlex.quote(tier)}"

    def dry_run(self, plan: Mapping[str, Any]) -> list[dict]:
        return [{"shot": s["id"], "engine": self.name, "seconds": int(s["dur"]), "framing": s.get("framing", "close")}
                for s in plan.get("shots") or []]

    def render_shot(self, **_: Any) -> dict:
        raise EngineNotReady("replicate renders whole episodes through make_episode.py (cost cap + ledger)")


class KlingAdapter:
    name = "kling"

    def __init__(self, client: KlingClient | None = None) -> None:
        self.client = client or KlingClient()

    def dry_run(self, plan: Mapping[str, Any]) -> list[dict]:
        return [{**r, "engine": self.name} for r in self.client.dry_run_requests(plan)]

    def render_shot(self, **kwargs: Any) -> dict:
        return self.client.render_talk_shot(**kwargs)


def adapter_for(engine: str) -> Any:
    table = {"kling": KlingAdapter, "replicate": ReplicateEpisode, "higgsfield_kling": HiggsfieldKling,
             "runpod_wan": RunpodWan, "minimax_hailuo": MinimaxHailuo}
    if engine not in table:
        raise ValueError(f"engine is one of {', '.join(table)}")
    return table[engine]()
