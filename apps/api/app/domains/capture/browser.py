"""Headless Chromium session for captures (Playwright, Apache-2.0).

One :class:`BrowserSession` = one recorded page at one aspect ratio:

* 9:16 uses a mobile viewport (540x960 CSS px, touch, mobile UA) so sites show
  their real mobile layout; 16:9 uses a 1280x720 desktop viewport. Playwright
  records the page at that size; :mod:`app.domains.capture.encode` upscales it
  to 1080x1920 / 1920x1080.
* Every network request is checked by the Ad Studio SSRF classifier (public
  hosts only, cached per host). Service workers are blocked so no request
  bypasses the route guard; downloads are refused.
* A small overlay draws a highlighted cursor that follows the mouse and pulses
  on click, because headless Chromium renders no pointer.

Install (not bundled with the API image by default)::

    pip install -r requirements.txt           # includes playwright
    python -m playwright install --with-deps chromium

Without the browser binary a website capture fails with a clear
message; store-listing captures do not need Playwright at all.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

VIEWPORTS: dict[str, dict[str, Any]] = {
    "9:16": {"width": 540, "height": 960, "mobile": True},
    "16:9": {"width": 1280, "height": 720, "mobile": False},
    "1:1": {"width": 900, "height": 900, "mobile": False},
}
NAV_TIMEOUT_MS = 45_000
SETTLE_TIMEOUT_MS = 8_000
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
INSTALL_HINT = (
    "website capture needs the headless browser; the server operator must run "
    "`pip install playwright` and `python -m playwright install --with-deps chromium`"
)

CURSOR_SCRIPT = r"""
(() => {
  if (window.__mvCursorInstalled) return;
  window.__mvCursorInstalled = true;
  const install = () => {
    if (document.getElementById('__mv_cursor')) return;
    const dot = document.createElement('div');
    dot.id = '__mv_cursor';
    dot.setAttribute('aria-hidden', 'true');
    dot.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'width:26px', 'height:26px', 'margin:-13px 0 0 -13px',
      'border-radius:50%', 'background:rgba(255,214,10,0.45)', 'border:2px solid rgba(255,255,255,0.95)',
      'box-shadow:0 0 0 2px rgba(0,0,0,0.25),0 2px 10px rgba(0,0,0,0.35)', 'pointer-events:none',
      'z-index:2147483647', 'transition:transform 120ms ease-out', 'transform:translate(-100px,-100px)'
    ].join(';');
    document.documentElement.appendChild(dot);
    let x = -100, y = -100;
    const place = (s) => { dot.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + s + ')'; };
    window.addEventListener('mousemove', (e) => { x = e.clientX; y = e.clientY; place(1); }, true);
    window.addEventListener('mousedown', () => {
      place(0.7);
      const ring = document.createElement('div');
      ring.style.cssText = 'position:fixed;left:' + x + 'px;top:' + y + 'px;width:26px;height:26px;margin:-13px 0 0 -13px;' +
        'border-radius:50%;border:3px solid rgba(255,214,10,0.9);pointer-events:none;z-index:2147483647;' +
        'transition:transform 450ms ease-out,opacity 450ms ease-out;transform:scale(1);opacity:1';
      document.documentElement.appendChild(ring);
      requestAnimationFrame(() => { ring.style.transform = 'scale(2.6)'; ring.style.opacity = '0'; });
      setTimeout(() => ring.remove(), 500);
    }, true);
    window.addEventListener('mouseup', () => place(1), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
"""


class CaptureBrowserError(RuntimeError):
    """A user-presentable browser capture failure."""


@dataclass
class Recording:
    video_path: str
    lead_in_s: float
    recorded_s: float
    screenshots: list[tuple[str, str]] = field(default_factory=list)
    page_meta: dict[str, Any] = field(default_factory=dict)


def _host_guard() -> Any:
    """Return ``allowed(url) -> bool`` backed by the shared SSRF classifier."""
    from app.domains.adstudio.fetch import FetchError, _pinned_ip, normalize_public_url

    cache: dict[str, bool] = {}

    def allowed(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme in ("data", "blob", "about"):
            return True
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if host not in cache:
            try:
                normalize_public_url(url)
                _pinned_ip(url)
                cache[host] = True
            except FetchError:
                cache[host] = False
        return cache[host]

    return allowed


PAGE_META_JS = r"""
() => {
  const pick = (sel) => { const el = document.querySelector(sel); return el ? (el.getAttribute('content') || '').trim() : ''; };
  return {
    title: (document.title || '').trim().slice(0, 200),
    description: (pick('meta[name="description"]') || pick('meta[property="og:description"]')).slice(0, 600),
    site_name: pick('meta[property="og:site_name"]').slice(0, 120),
    og_image: pick('meta[property="og:image"]').slice(0, 1000),
    theme_color: pick('meta[name="theme-color"]').slice(0, 32),
  };
}
"""


class BrowserSession:
    """Context manager around one recorded Playwright page."""

    def __init__(self, aspect: str, work_dir: str, *, cursor: bool = True) -> None:
        if aspect not in VIEWPORTS:
            raise CaptureBrowserError(f"unsupported aspect ratio {aspect}")
        self.aspect = aspect
        self.viewport = VIEWPORTS[aspect]
        self.video_dir = os.path.join(work_dir, f"video-{aspect.replace(':', 'x')}")
        self.cursor = cursor
        self.page: Any = None
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._t0 = 0.0
        self._t_start = 0.0

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise CaptureBrowserError(INSTALL_HINT) from exc
        os.makedirs(self.video_dir, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                headless=True, args=["--disable-dev-shm-usage", "--autoplay-policy=no-user-gesture-required"]
            )
        except Exception as exc:  # noqa: BLE001 - missing browser binary etc.
            self._pw.stop()
            raise CaptureBrowserError(INSTALL_HINT) from exc
        width, height, mobile = self.viewport["width"], self.viewport["height"], self.viewport["mobile"]
        self._context = self._browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=self.video_dir,
            record_video_size={"width": width, "height": height},
            is_mobile=mobile,
            has_touch=mobile,
            device_scale_factor=2 if mobile else 1,
            user_agent=MOBILE_UA if mobile else DESKTOP_UA,
            accept_downloads=False,
            service_workers="block",
            locale="en-US",
        )
        allowed = _host_guard()
        self._context.route("**/*", lambda route: route.continue_() if allowed(route.request.url) else route.abort())
        if self.cursor:
            self._context.add_init_script(CURSOR_SCRIPT)
        self._t0 = time.monotonic()
        self.page = self._context.new_page()
        self.page.set_default_timeout(15_000)
        return self

    def goto(self, url: str) -> None:
        try:
            response = self.page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - normalize navigation errors
            raise CaptureBrowserError("the page did not load in time or refused the connection") from exc
        if response is not None and response.status >= 400:
            raise CaptureBrowserError(f"the page returned HTTP {response.status}")
        try:
            self.page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 - busy pages never go idle; that's fine
            pass

    def mark_start(self) -> None:
        """The recorded footage starts here (everything before is trimmed)."""
        self._t_start = time.monotonic()

    def page_meta(self) -> dict[str, Any]:
        try:
            return dict(self.page.evaluate(PAGE_META_JS) or {})
        except Exception:  # noqa: BLE001 - meta is best-effort
            return {}

    def screenshot(self, path: str) -> bool:
        try:
            self.page.evaluate("() => { const c = document.getElementById('__mv_cursor'); if (c) c.style.display = 'none'; }")
            self.page.screenshot(path=path, type="jpeg", quality=88)
            return True
        except Exception:  # noqa: BLE001 - screenshots are best-effort
            return False
        finally:
            try:
                self.page.evaluate("() => { const c = document.getElementById('__mv_cursor'); if (c) c.style.display = 'block'; }")
            except Exception:  # noqa: BLE001
                pass

    def finish(self) -> tuple[str, float, float]:
        """Close the context and return ``(video_path, lead_in_s, recorded_s)``."""
        end = time.monotonic()
        video = self.page.video if self.page is not None else None
        self._context.close()
        path = video.path() if video is not None else ""
        self._context = None
        lead_in = max(0.0, (self._t_start or self._t0) - self._t0)
        return str(path), lead_in, max(0.0, end - (self._t_start or self._t0))

    def __exit__(self, *exc: Any) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["BrowserSession", "CaptureBrowserError", "CURSOR_SCRIPT", "INSTALL_HINT", "Recording", "VIEWPORTS"]
