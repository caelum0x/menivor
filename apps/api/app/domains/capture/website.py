"""Website capture script: a smooth scroll-through with cursor highlights.

Timeline for a ``duration_s`` recording::

    hold at top (1.5s) -> hover the first call to action (1.2s)
    -> eased scroll down in viewport-sized chunks, hovering a visible link or
       button between chunks -> eased scroll back to the top -> hold (1.5s)

Cookie banners are dismissed (best effort) before the recorded part starts, so
the lead-in (page load + banner) is trimmed off the final video.
"""

from __future__ import annotations

import math
import os
import random
import re
import time
from typing import Any

from app.domains.capture.browser import BrowserSession, Recording

HOLD_TOP_S = 1.5
HOVER_CTA_S = 1.2
HOLD_END_S = 1.5
MAX_CHUNKS = 14

SMOOTH_SCROLL_JS = r"""
([to, ms]) => new Promise((resolve) => {
  document.documentElement.style.scrollBehavior = 'auto';
  const from = window.scrollY;
  const start = performance.now();
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const step = (now) => {
    const t = Math.min(1, (now - start) / Math.max(1, ms));
    window.scrollTo(0, from + (to - from) * ease(t));
    if (t < 1) requestAnimationFrame(step); else resolve(window.scrollY);
  };
  requestAnimationFrame(step);
})
"""

SCROLL_INFO_JS = r"""
() => ({
  max: Math.max(0, Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0) - window.innerHeight),
  vh: window.innerHeight,
  vw: window.innerWidth,
})
"""

TARGETS_JS = r"""
() => {
  const out = [];
  const els = document.querySelectorAll('a[href], button, [role="button"], input[type="submit"], summary');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 16 || r.bottom < 40 || r.top > window.innerHeight - 40) continue;
    if (r.left < 0 || r.right > window.innerWidth) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) continue;
    out.push([Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]);
    if (out.length >= 16) break;
  }
  return out;
}
"""

_CONSENT = re.compile(r"^\s*(accept( all)?( cookies)?|allow all|agree|i agree|got it|ok(ay)?|continue)\s*$", re.I)


def plan_chunks(max_scroll: int, viewport_h: int) -> list[int]:
    """Scroll stops (px) from the top to the bottom in ~0.8-viewport steps."""
    if max_scroll <= 0 or viewport_h <= 0:
        return []
    count = min(MAX_CHUNKS, max(1, math.ceil(max_scroll / (viewport_h * 0.8))))
    return [round(max_scroll * (i + 1) / count) for i in range(count)]


def budget(duration_s: float, chunks: int) -> tuple[float, float, float]:
    """(seconds per down-chunk scroll, pause per chunk, seconds for scroll-up)."""
    scroll_time = max(2.0, duration_s - HOLD_TOP_S - HOVER_CTA_S - HOLD_END_S)
    up = min(3.0, 0.2 * scroll_time) if chunks else 0.0
    down = scroll_time - up
    if chunks <= 0:
        return 0.0, 0.0, 0.0
    per = down / chunks
    return per * 0.72, per * 0.28, up


def _dismiss_consent(page: Any) -> None:
    try:
        button = page.get_by_role("button", name=_CONSENT).first
        if button.count() and button.is_visible():
            button.click(timeout=1500)
            time.sleep(0.4)
    except Exception:  # noqa: BLE001 - consent handling is best effort
        pass


def _hover(page: Any, rng: random.Random, fallback: tuple[int, int], seconds: float) -> None:
    started = time.monotonic()
    try:
        targets = page.evaluate(TARGETS_JS) or []
    except Exception:  # noqa: BLE001
        targets = []
    x, y = rng.choice(targets) if targets else fallback
    try:
        page.mouse.move(x, y, steps=max(8, int(seconds * 30)))
    except Exception:  # noqa: BLE001
        pass
    remaining = seconds - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)


def record_website(url: str, aspect: str, duration_s: float, work_dir: str, *, seed: int, cursor: bool = True) -> Recording:
    rng = random.Random(seed)
    shots: list[tuple[str, str]] = []
    with BrowserSession(aspect, work_dir, cursor=cursor) as session:
        page = session.page
        session.goto(url)
        _dismiss_consent(page)
        meta = session.page_meta()
        info = page.evaluate(SCROLL_INFO_JS) or {}
        vw, vh = int(info.get("vw") or session.viewport["width"]), int(info.get("vh") or session.viewport["height"])
        center = (vw // 2, vh // 2)
        tag = aspect.replace(":", "x")
        top_shot = os.path.join(work_dir, f"shot-{tag}-top.jpg")
        if session.screenshot(top_shot):
            shots.append((top_shot, "top"))
        page.mouse.move(center[0], int(vh * 0.8))
        session.mark_start()
        time.sleep(HOLD_TOP_S)
        _hover(page, rng, center, HOVER_CTA_S)
        stops = plan_chunks(int(info.get("max") or 0), vh)
        scroll_s, pause_s, up_s = budget(duration_s, len(stops))
        if stops:
            for index, stop in enumerate(stops):
                page.evaluate(SMOOTH_SCROLL_JS, [stop, int(scroll_s * 1000)])
                _hover(page, rng, center, pause_s)
                if index in (len(stops) // 2, len(stops) - 1):
                    path = os.path.join(work_dir, f"shot-{tag}-{index}.jpg")
                    if session.screenshot(path):
                        shots.append((path, "middle" if index < len(stops) - 1 else "bottom"))
            page.evaluate(SMOOTH_SCROLL_JS, [0, int(up_s * 1000)])
        else:
            # The page scrolls inside a container (or not at all): wheel over it.
            page.mouse.move(*center, steps=10)
            deadline = time.monotonic() + max(2.0, duration_s - HOLD_TOP_S - HOVER_CTA_S - HOLD_END_S)
            while time.monotonic() < deadline:
                page.mouse.wheel(0, 90)
                time.sleep(0.05)
        time.sleep(HOLD_END_S)
        video, lead_in, recorded = session.finish()
    return Recording(video_path=video, lead_in_s=lead_in, recorded_s=recorded, screenshots=shots, page_meta=meta)


__all__ = ["budget", "plan_chunks", "record_website"]
