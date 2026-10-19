"""Ad Clone orchestration: link -> brief -> plans + per-engine prices -> (dry-run) render."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from typing import Any

from . import engines, ipguard, midjourney, planschema, presets
from .adapters import EngineNotReady, adapter_for
from .analyze import heuristic_brief, refine_with_llm
from .ingest import observe
from .linkresolve import Head, resolve
from .rewrite import CloneOptions, build_plans
from .schemas import CloneBrief

ENABLED_ENV = "ADCLONE_ENABLED"
PAID_ENV = "ADCLONE_PAID_RENDER"
CAP_ENV = "ADCLONE_CAP_USD"
DEFAULT_CAP_USD = 6.0
LLM_ENV = "ADCLONE_USE_LLM"

Downloader = Callable[[str, str], str]
Llm = Callable[[str], str]


class AdCloneError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return _truthy(os.getenv(ENABLED_ENV))


def default_downloader(url: str, dest_stem: str) -> str:
    from app.domains.clipping.platform_source import download_platform_video

    return download_platform_video(url, dest_stem)


def default_llm() -> Llm | None:
    """The LLM step through Railyard Relay, or None (switched off, or Relay not configured)."""
    if not _truthy(os.getenv(LLM_ENV, "1")):
        return None
    from .relay_writer import relay_llm

    return relay_llm()


def llm_note() -> str:
    from .relay_writer import NOT_CONFIGURED_NOTE, relay_configured

    if not _truthy(os.getenv(LLM_ENV, "1")):
        return f"LLM step switched off ({LLM_ENV}=0): measured analysis and template lines only"
    return "" if relay_configured() else NOT_CONFIGURED_NOTE


def analyze_link(url: str, *, head: Head | None = None, downloader: Downloader | None = None,
                 observer: Callable[..., Any] = observe, llm: Llm | None = None,
                 workdir: str | None = None, keep_workdir: bool = False,
                 language: str | None = None) -> CloneBrief:
    """``language``: the ad's spoken language when the user knows it; None = Whisper detects it."""
    link = resolve(url, head=head)
    root = workdir or tempfile.mkdtemp(prefix="adclone-")
    try:
        try:
            path = (downloader or default_downloader)(link.url, os.path.join(root, "source"))
        except Exception as exc:  # noqa: BLE001 - surface a typed error
            status = getattr(exc, "status_code", 502)
            raise AdCloneError(status, getattr(exc, "message", "could not download the ad")) from exc
        obs = observer(path, os.path.join(root, "frames"), url=link.url, platform=link.platform,
                       source_ref=link.source_ref, language=language)
        brief = heuristic_brief(obs)
        if llm is not None:
            return refine_with_llm(brief, llm)
        note = llm_note() or "LLM step not used for this brief"
        return brief.model_copy(update={"notes": [*brief.notes, note]})
    finally:
        if not keep_workdir:
            shutil.rmtree(root, ignore_errors=True)  # source footage never outlives the analysis


def clone(brief: CloneBrief, *, preset_name: str = "oxhan", options: CloneOptions | None = None,
          engine: str | None = None, llm: Llm | None = None, env: Mapping[str, str] | None = None) -> dict:
    preset = presets.load(preset_name)
    plans = build_plans(brief, preset, options or CloneOptions(), llm=llm)
    out = []
    for plan in plans:
        problems = planschema.validate(plan, cta_text=preset["cta"]["text"], cta_speaker=preset["cta"]["speaker"])
        if problems:
            raise AdCloneError(500, "generated plan failed the episode schema: " + "; ".join(problems[:5]))
        from app.services.billing.premium_credits import ai_video_credits_for_usd

        rows = engines.estimates(plan, env)
        chosen = engines.choose(rows, engine)
        out.append({"plan": plan, "estimates": rows, "engine": chosen,
                    "ai_video_credits": ai_video_credits_for_usd(chosen["usd"]),
                    "midjourney": midjourney.prompts(plan, preset)})
    return {"brief": brief.model_dump(), "product": presets.public_view(preset), "variations": out,
            "voice": engines.voice_route(env), "paid_render": paid_enabled(env)}


def checked_plan(plan: Mapping[str, Any]) -> dict:
    """Re-check a client-supplied plan (IP guard + episode schema); returns its product preset."""
    preset = presets.load(str((plan.get("clone") or {}).get("preset") or "oxhan"))
    ipguard.enforce(plan, banned_terms=preset.get("banned_design") or [], source_texts=[],
                    source_markers=[str((plan.get("clone") or {}).get("source_ref") or "")],
                    allow_lines=[preset["cta"]["text"]])
    problems = planschema.validate(plan, cta_text=preset["cta"]["text"], cta_speaker=preset["cta"]["speaker"])
    if problems:
        raise AdCloneError(422, "plan does not match the episode format: " + "; ".join(problems[:5]))
    return preset


def paid_enabled(env: Mapping[str, str] | None = None) -> bool:
    return _truthy((os.environ if env is None else env).get(PAID_ENV))


def cap_usd(env: Mapping[str, str] | None = None) -> float:
    try:
        return float((os.environ if env is None else env).get(CAP_ENV) or DEFAULT_CAP_USD)
    except ValueError:
        return DEFAULT_CAP_USD


def render(plan: Mapping[str, Any], *, engine: str | None = None, dry_run: bool = True,
           env: Mapping[str, str] | None = None) -> dict:
    """Dry run: the requests each engine would send + price. Paid renders go through approve (render_job)."""
    env = os.environ if env is None else env
    checked_plan(plan)
    rows = engines.estimates(plan, env)
    chosen = engines.choose(rows, engine)
    adapter = adapter_for(chosen["engine"])
    result = {"engine": chosen, "requests": adapter.dry_run(plan), "dry_run": True}
    if dry_run or chosen["dry_run_only"]:
        return result
    if not paid_enabled(env):
        raise AdCloneError(403, f"paid rendering is off; set {PAID_ENV}=1 after checking the price")
    raise AdCloneError(409, "approve the render (POST /ad-clone/render/approve) to start a paid job")


def shot_audio(line_files: list[str], out_path: str, *, lead_s: float = 0.25, gap_s: float = 0.3) -> str:
    """Concatenate a shot's line takes with the plan's lead and gaps (the audio Kling lip-syncs to)."""
    silence = ["-f", "lavfi", "-t"]
    args = ["ffmpeg", "-v", "error", "-y", *silence, f"{lead_s}", "-i", "anullsrc=r=44100:cl=mono"]
    for i, f in enumerate(line_files):
        args += ["-i", f]
        if i < len(line_files) - 1:
            args += [*silence, f"{gap_s}", "-i", "anullsrc=r=44100:cl=mono"]
    n = sum(1 for a in args if a == "-i")
    norm = "".join(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono[x{i}];" for i in range(n))
    labels = "".join(f"[x{i}]" for i in range(n))
    args += ["-filter_complex", f"{norm}{labels}concat=n={n}:v=0:a=1[a]", "-map", "[a]", out_path]
    out = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    if out.returncode != 0:
        raise AdCloneError(500, f"could not build shot audio: {out.stderr[:200]}")
    return out_path


__all__ = ["AdCloneError", "EngineNotReady", "analyze_link", "cap_usd", "checked_plan", "clone", "enabled",
           "paid_enabled", "render", "shot_audio"]
