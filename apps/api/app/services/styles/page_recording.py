"""Record the pasted page as a moving product visual (headless Chromium).

A style's product panel should move: this opens the creator's own public page
in headless Chromium (Playwright, already in the worker image), records the
viewport while it scrolls through the page with short pauses, and returns the
recorded clip. It is the creator's own page, captured like a screen recording.

SSRF guard: the URL must normalize to a public http(s) URL whose host resolves
to a global address, and every request the page makes is routed through the
same check (private, loopback and link-local destinations are aborted).

Best-effort: any failure returns ``""`` so the style falls back to the page's
preview image.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from functools import lru_cache
from typing import Callable
from urllib.parse import urlparse

from loguru import logger

MAX_RECORD_S = 40.0
MIN_RECORD_S = 6.0
NAV_TIMEOUT_MS = 20_000


@lru_cache(maxsize=256)
def _host_is_public(host: str) -> bool:
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in {"localhost"} or host.endswith((".internal", ".local")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def url_is_public(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return False
    return _host_is_public(parsed.hostname or "")


def scroll_plan(page_height: int, viewport_height: int, duration_s: float) -> list[tuple[int, int]]:
    """``[(scroll_y, hold_ms), ...]`` that tours the page within ``duration_s``.

    Moves down in viewport-sized steps with short holds, then returns to the
    top, so the clip always has motion and ends near where it started.
    """
    usable = max(0, int(page_height) - int(viewport_height))
    total_ms = int(max(MIN_RECORD_S, min(MAX_RECORD_S, duration_s)) * 1000)
    step = max(240, int(viewport_height * 0.6))
    stops = list(range(step, usable + 1, step)) or [min(usable, step)]
    stops = stops[:12] + [0]
    hold = max(400, total_ms // max(1, len(stops)) - 300)
    return [(y, hold) for y in stops]


_BANNER_BUTTON = re.compile(r"^(accept|accept all|decline|reject|got it|agree|ok|okay|close)$", re.I)


def _dismiss_banners(page) -> None:
    """Click a cookie/consent button when one is showing (best-effort)."""
    try:
        button = page.get_by_role("button", name=_BANNER_BUTTON).first
        if button.is_visible(timeout=800):
            button.click(timeout=1500)
            page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001 - no banner, or not clickable
        return


def record_page(
    url: str,
    dest_dir: str,
    *,
    width: int,
    height: int,
    duration_s: float,
    playwright_factory: Callable | None = None,
) -> str:
    """Record ``url`` scrolling for ``duration_s``; returns the clip path or ``""``."""
    if not url or not url_is_public(url):
        logger.warning("page recording: URL is not a public http(s) page")
        return ""
    try:
        if playwright_factory is None:
            from playwright.sync_api import sync_playwright as playwright_factory
        os.makedirs(dest_dir, exist_ok=True)
        # Recorded at 2/3 of the panel (a phone-to-tablet layout); the scene
        # scales it up to the panel.
        view_w, view_h = max(360, width * 2 // 3) // 2 * 2, max(320, height * 2 // 3) // 2 * 2
        with playwright_factory() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context = browser.new_context(
                    viewport={"width": view_w, "height": view_h},
                    record_video_dir=dest_dir,
                    record_video_size={"width": view_w, "height": view_h},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 MenivorPreview"
                    ),
                )

                def _guard(route):
                    if url_is_public(route.request.url) or route.request.url.startswith("data:"):
                        route.continue_()
                    else:
                        route.abort()

                context.route("**/*", _guard)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(1200)
                _dismiss_banners(page)
                page_height = int(page.evaluate("document.documentElement.scrollHeight") or view_h)
                for y, hold in scroll_plan(page_height, view_h, duration_s):
                    page.evaluate(f"window.scrollTo({{top: {int(y)}, behavior: 'smooth'}})")
                    page.wait_for_timeout(hold)
                video = page.video
                context.close()
                path = video.path() if video else ""
            finally:
                browser.close()
        if path and os.path.isfile(path) and os.path.getsize(path) > 0:
            return str(path)
        return ""
    except Exception as exc:  # noqa: BLE001 - best-effort visual
        logger.warning(f"page recording failed: {type(exc).__name__}: {exc}")
        return ""


__all__ = ["record_page", "scroll_plan", "url_is_public"]
