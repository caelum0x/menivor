"""Time one reel's variants end to end on the real pipeline (ops tool).

Renders ``--variants`` versions of one style for one of OUR OWN products,
exactly like a one-flow create (same stage functions, same providers, same R2
round trips), but in-process: no Job row, no credits, no ledger, nothing
published. Every R2 object it creates under ``jobs/<timing-id>/`` is deleted
at the end. Provider spend (hook LLM + narration) is a few cents per variant
and is capped by ``--budget-usd``.

    python apps/api/tools/ops/time_style_variants.py --style meme_hook --product rally
    python apps/api/tools/ops/time_style_variants.py --parallel 2

Prints one JSON document with per-variant stage seconds, the wall clock for
the whole set, and the estimated spend.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from loguru import logger  # noqa: E402

DEFAULT_HOOKS = ("met_me_at", "nobody_me", "tell_me_without")
_STAGE_KEYS = ("audio_key", "ass_key", "final_key", "poster_key", "preview_key", "music_key")


def _render(style, content: dict, name: str, url: str, hook_format: str, voice: str, duration: int) -> dict:
    from app.domains.styles.catalog import style_overrides
    from app.services import reelforge
    from render_style_samples import _script  # type: ignore[import-not-found]

    script, hook = _script(style, content, hook_format)
    params = reelforge.ReelForgeParams(
        video_subject=name,
        video_script=script,
        voice_name=voice,
        aspect="9:16",
        language="en",
        target_duration_s=duration,
        source_url=url,
        **style_overrides(style, hook_style=hook.get("hook_style", "")),
    )
    job_id = f"timing-{uuid.uuid4().hex[:12]}"
    stages: dict[str, float] = {}
    ctx: dict = {}
    started = time.monotonic()
    for stage_name in ("script", "tts", "avatar", "captions", "compose"):
        fn = getattr(reelforge, f"stage_{stage_name}")
        t0 = time.monotonic()
        ctx = {**ctx, **(fn(job_id, params, ctx) or {})}
        stages[stage_name] = round(time.monotonic() - t0, 2)
    final = str(ctx.get("final_video") or "")
    ok = bool(final) and os.path.isfile(final) and os.path.getsize(final) > 0
    result = {
        "job_id": job_id,
        "hook_format": hook_format,
        "hook": hook.get("hook", ""),
        "ok": ok,
        "seconds": round(time.monotonic() - started, 2),
        "stages": stages,
        "narration_s": round(float(ctx.get("audio_duration") or 0.0), 1),
        "final_mb": round(os.path.getsize(final) / 1e6, 2) if ok else 0.0,
        "script_chars": len(str(ctx.get("script") or script)),
    }
    _cleanup(job_id, ctx, final)
    return result


def _cleanup(job_id: str, ctx: dict, final: str) -> None:
    from app.platform.storage.r2 import get_r2_client

    client = get_r2_client()
    for key in {str(ctx.get(k) or "") for k in _STAGE_KEYS} | {f"jobs/{job_id}/background.mp4", f"jobs/{job_id}/style-screen.mp4", f"jobs/{job_id}/captions.ass"}:
        if key.startswith(f"jobs/{job_id}/"):
            try:
                client.delete_object(key)
            except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
                logger.warning(f"could not delete {key}: {exc}")
    if final:
        shutil.rmtree(os.path.dirname(final), ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--style", default="meme_hook")
    parser.add_argument("--product", default="rally")
    parser.add_argument("--hooks", default=",".join(DEFAULT_HOOKS))
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--duration", type=int, default=25)
    parser.add_argument("--voice", default="")
    parser.add_argument("--budget-usd", type=float, default=2.0)
    args = parser.parse_args()

    from app.domains.ingest.service import IngestService
    from app.domains.styles.catalog import get_style
    from render_style_samples import DEFAULT_VOICE, PRODUCTS, TTS_USD_PER_1K_CHARS  # type: ignore[import-not-found]

    style = get_style(args.style)
    if style is None or style.needs_presenter or style.visual in ("anime", "character"):
        raise SystemExit("pick a page-visual style without a presenter (no image/avatar spend)")
    hooks = [h.strip() for h in args.hooks.split(",") if h.strip()]
    # ~450 chars of narration per variant at list price, plus the hook LLM call.
    estimate = len(hooks) * (0.45 * TTS_USD_PER_1K_CHARS + 0.01)
    if estimate > args.budget_usd:
        raise SystemExit(f"estimated spend ${estimate:.2f} exceeds --budget-usd {args.budget_usd}")
    name, url = PRODUCTS[args.product]
    content = dict(IngestService().url_to_reel(url).get("content") or {})
    content["title"] = content.get("title") or name
    voice = args.voice or DEFAULT_VOICE

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        futures = [
            pool.submit(_render, style, content, name, url, hook, voice, args.duration) for hook in hooks
        ]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - report, keep the others
                results.append({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    wall = round(time.monotonic() - started, 2)
    chars = sum(int(r.get("script_chars") or 0) for r in results)
    print(json.dumps({
        "style": args.style,
        "product": name,
        "parallel": args.parallel,
        "x264_preset": os.environ.get("MENIVOR_X264_PRESET") or "veryfast (default)",
        "wall_s": wall,
        "variants": results,
        "spend_usd_est": round(chars / 1000 * TTS_USD_PER_1K_CHARS + 0.01 * len(hooks), 3),
    }, indent=2))


if __name__ == "__main__":
    main()
