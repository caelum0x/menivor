"""Render engines for Ad Clone: worst-case cost per plan, shown before any render, and the default pick.

Prices are list prices with their source and check date. The default engine is Kling (official
API) when its keys are set (owner pipeline: Midjourney stills -> ElevenLabs voice -> Kling
animation + lip-sync); otherwise the cheapest configured engine; with nothing configured the
plan is dry-run only and the cheapest engine is shown as the suggestion.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

KLING_PRICES = {  # USD per output second, no native audio (1 unit = $0.14)
    ("kling-v3", "720p"): 0.084, ("kling-v3", "1080p"): 0.112,
    ("kling-v2-6", "720p"): 0.042, ("kling-v2-6", "1080p"): 0.07,
}
KLING_LIPSYNC_PER_5S = 0.07  # 0.5 unit per 5 s
KLING_SOURCE = ("ESTIMATE: Kling API unit card as reported by createvision.ai/guides/kling-ai-pricing-2026 (read "
                "from kling.ai 2026-09-09) and promptsrush.com/blog/kling-ai-pricing (2026-09-16). The official "
                "pricing page (kling.ai/document-api/productBilling) is a client-rendered app and returned no price "
                "content on 2026-10-06; confirm in the Kling console before the first paid run")
REPLICATE = {"m25_480p": 0.1028, "mini_720p": 0.09, "seedream": 0.035}
REPLICATE_SOURCE = "replicate.com model pages (gtm/oxhan-very-turkish-time/work/vtt/config.py), checked 2026-10-06"
HIGGSFIELD_KLING_PER_S = 0.075
HIGGSFIELD_LIPSYNC_PER_S = 0.0155
HIGGSFIELD_SOURCE = "cloud.higgsfield.ai/pricing via CHEAPER-VIDEO-OPTIONS-2026-10-06.md (option 5, ~$2.7/30 s)"
RUNPOD_H100_PER_H = 1.99
RUNPOD_GPU_MIN_PER_OUTPUT_S = 1.5  # ~45 GPU-min per 30 s episode (Wan 2.2 + InfiniteTalk, 4-step LoRA)
RUNPOD_SOURCE = "runpod.io/pricing + InfiniteTalk speed notes via CHEAPER-VIDEO-OPTIONS-2026-10-06.md (option 7)"
HAILUO_PER_S = 0.08
HAILUO_SOURCE = "platform.minimax.io/docs/pricing/overview via CHEAPER-VIDEO-OPTIONS-2026-10-06.md (option 9)"


@dataclass(frozen=True)
class PlanSummary:
    close_s: list[int]   # requested seconds of each close/side talk shot
    wide_s: list[int]    # requested seconds of each wide talk shot
    payoff_s: int
    stills: int
    line_chars: int

    @property
    def shots(self) -> list[int]:
        return [*self.close_s, *self.wide_s, self.payoff_s]

    @property
    def video_s(self) -> int:
        return sum(self.shots)


def summarize(plan: Mapping[str, Any]) -> PlanSummary:
    close, wide, pay = [], [], 0
    for s in plan.get("shots") or []:
        if s["kind"] == "payoff":
            pay = int(s["dur"])
        elif s["kind"] == "talk":
            (wide if s.get("framing") == "wide" else close).append(int(s["dur"]))
    return PlanSummary(close, wide, pay, len(plan.get("stills") or []),
                       sum(len(str(ln.get("tts") or ln.get("text") or "")) for ln in plan.get("lines") or []))


def _env(env: Mapping[str, str], *names: str) -> bool:
    return all((env.get(n) or "").strip() for n in names)


def _up(usd: float) -> float:
    """Quotes round UP to the cent, so a run can never cost more than the price the user approved."""
    return math.ceil(round(usd, 6) * 100) / 100


def _clip(seconds: int, sizes: tuple[int, ...]) -> int:
    return next((s for s in sizes if seconds <= s), sizes[-1] * math.ceil(seconds / sizes[-1]))


def kling_estimate(ps: PlanSummary, *, model: str = "kling-v3", res: str = "720p", mj_stills: bool = True) -> dict:
    rate = KLING_PRICES[(model, res)]
    clips = [_clip(s, (5, 10)) for s in ps.shots]
    video = round(sum(clips) * rate, 4)
    lips = round(sum(math.ceil(c / 5) for c in clips) * KLING_LIPSYNC_PER_5S, 4)
    stills = 0.0 if mj_stills else round(ps.stills * REPLICATE["seedream"], 4)
    return {"items": [{"item": f"image-to-video {model} {res}", "units": f"{sum(clips)} s ({len(clips)} clips)", "usd": video},
                      {"item": "lip-sync to our ElevenLabs audio", "units": f"{sum(clips)} s", "usd": lips},
                      {"item": "first frames (Midjourney imports)" if mj_stills else "stills (Seedream 5 Lite)",
                       "units": f"{ps.stills}", "usd": stills}],
            "usd": _up(video + lips + stills), "source": KLING_SOURCE}


def replicate_estimate(ps: PlanSummary) -> dict:
    close = round(sum([*ps.close_s, ps.payoff_s]) * REPLICATE["m25_480p"], 4)
    wide = round(sum(ps.wide_s) * REPLICATE["mini_720p"], 4)
    stills = round(ps.stills * REPLICATE["seedream"], 4)
    dearest = max([s * REPLICATE["m25_480p"] for s in [*ps.close_s, ps.payoff_s]] +
                  [s * REPLICATE["mini_720p"] for s in ps.wide_s] + [0.0])
    return {"items": [{"item": "Seedance 2.5 480p close-ups + payoff", "units": f"{sum([*ps.close_s, ps.payoff_s])} s", "usd": close},
                      {"item": "Seedance 2.0-mini 720p wides", "units": f"{sum(ps.wide_s)} s", "usd": wide},
                      {"item": "stills (Seedream 5 Lite)", "units": f"{ps.stills}", "usd": stills},
                      {"item": "re-roll reserve (dearest shot)", "units": "1", "usd": round(dearest, 4)}],
            "usd": _up(close + wide + stills + dearest), "source": REPLICATE_SOURCE}


def higgsfield_estimate(ps: PlanSummary) -> dict:
    clips = [_clip(s, (5, 10)) for s in ps.shots]
    video = round(sum(clips) * HIGGSFIELD_KLING_PER_S, 4)
    lips = round(sum(clips) * HIGGSFIELD_LIPSYNC_PER_S, 4)
    return {"items": [{"item": "Kling via Higgsfield", "units": f"{sum(clips)} s", "usd": video},
                      {"item": "lip-sync", "units": f"{sum(clips)} s", "usd": lips}],
            "usd": _up(video + lips), "source": HIGGSFIELD_SOURCE}


def runpod_estimate(ps: PlanSummary) -> dict:
    gpu_h = ps.video_s * RUNPOD_GPU_MIN_PER_OUTPUT_S / 60
    usd = round(gpu_h * RUNPOD_H100_PER_H, 4)
    return {"items": [{"item": "Wan 2.2 + InfiniteTalk on RunPod H100", "units": f"{gpu_h:.2f} GPU-h", "usd": usd}],
            "usd": _up(usd), "source": RUNPOD_SOURCE, "fixed_monthly_usd": 7.0}


def hailuo_estimate(ps: PlanSummary) -> dict:
    clips = [_clip(s, (6, 10)) for s in ps.shots]
    usd = round(sum(clips) * HAILUO_PER_S, 4)
    return {"items": [{"item": "MiniMax Hailuo 768p (audio reference)", "units": f"{sum(clips)} s", "usd": usd}],
            "usd": _up(usd), "source": HAILUO_SOURCE}


ENGINES: dict[str, dict[str, Any]] = {
    "kling": {"label": "Kling (official API) + lip-sync", "keys": ("KLING_ACCESS_KEY", "KLING_SECRET_KEY"),
              "alt_keys": ("KLING_API_KEY",), "estimate": kling_estimate, "adapter": "kling.KlingClient",
              "price_basis": "estimate"},
    "higgsfield_kling": {"label": "Kling via Higgsfield (fallback)", "keys": ("HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET"),
                         "estimate": higgsfield_estimate, "adapter": "adapters.HiggsfieldKling", "price_basis": "estimate"},
    "replicate": {"label": "Seedance on Replicate (lean recipe)", "keys": ("REPLICATE_API_TOKEN",),
                  "estimate": replicate_estimate, "adapter": "make_episode.py", "price_basis": "list"},
    "runpod_wan": {"label": "Wan 2.2 + InfiniteTalk on RunPod", "keys": ("RUNPOD_API_KEY", "RUNPOD_WAN_ENDPOINT_ID"),
                   "estimate": runpod_estimate, "adapter": "adapters.RunpodWan", "price_basis": "estimate"},
    "minimax_hailuo": {"label": "MiniMax Hailuo", "keys": ("MINIMAX_API_KEY",), "estimate": hailuo_estimate,
                       "adapter": "adapters.MinimaxHailuo", "price_basis": "estimate"},
}


def configured(name: str, env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    spec = ENGINES[name]
    return _env(env, *spec["keys"]) or bool(spec.get("alt_keys") and _env(env, *spec["alt_keys"]))


def voice_route(env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ if env is None else env
    if _env(env, "ELEVENLABS_API_KEY"):
        return {"engine": "elevenlabs", "label": "ElevenLabs (designed voices, plan credits)", "usd": "0 marginal"}
    return {"engine": "kokoro", "label": "Kokoro-82M local (Apache-2.0)", "usd": "0"}


def estimates(plan: Mapping[str, Any], env: Mapping[str, str] | None = None) -> list[dict]:
    env = os.environ if env is None else env
    ps = summarize(plan)
    out = []
    for name, spec in ENGINES.items():
        if name == "kling":
            model = (env.get("KLING_MODEL") or "kling-v3").strip()
            res = (env.get("KLING_RESOLUTION") or "720p").strip()
            est = spec["estimate"](ps, model=model if (model, res) in KLING_PRICES else "kling-v3",
                                   res=res if (model, res) in KLING_PRICES else "720p")
        else:
            est = spec["estimate"](ps)
        out.append({"engine": name, "label": spec["label"], "configured": configured(name, env),
                    "keys": list(spec["keys"]), "price_basis": spec["price_basis"], **est})
    return out


def choose(rows: list[dict], requested: str | None = None) -> dict:
    """The engine to use: the requested one if configured; else Kling if configured; else cheapest configured."""
    by = {r["engine"]: r for r in rows}
    if requested:
        if requested not in by:
            raise ValueError(f"engine is one of {', '.join(by)}")
        return {**by[requested], "dry_run_only": not by[requested]["configured"], "reason": "requested"}
    if by["kling"]["configured"]:
        return {**by["kling"], "dry_run_only": False, "reason": "Kling keys are set (default pipeline)"}
    ready = sorted((r for r in rows if r["configured"]), key=lambda r: r["usd"])
    if ready:
        return {**ready[0], "dry_run_only": False, "reason": "cheapest configured engine"}
    cheapest = min(rows, key=lambda r: r["usd"])
    return {**cheapest, "dry_run_only": True, "reason": "no engine keys set: dry run only (cheapest shown)"}
