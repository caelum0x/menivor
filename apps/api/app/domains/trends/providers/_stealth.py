"""Private stealth/anti-detection support for the Playwright pull transport.

Ported and trimmed from ``external/tiktok-api/TikTokApi/stealth`` + ``helpers.py``
+ ``exceptions.py``. Only what the pull paths need is kept: a compact set of
init-script patches that hide the most obvious ``navigator.webdriver`` /
headless tells, a ``stealth_async`` applier, ``random_choice``, and the transport
exceptions. The 18 individual JS modules, the WebGL spoof matrices, and every
non-pull helper from upstream are dropped.

Import-safe: Playwright is only referenced through the ``page`` argument at call
time, so importing this module never requires Playwright to be installed.

--------------------------------------------------------------------------------
MIT NOTICE
This file adapts code from davidteather/TikTok-Api
(https://github.com/davidteather/TikTok-Api), licensed under the MIT License.
Original copyright (c) David Teather and contributors. See that project for the
full license text.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import random
from typing import Any

__all__ = [
    "STEALTH_SCRIPTS",
    "stealth_async",
    "random_choice",
    "TrendPullTransportError",
    "EmptyResponseException",
    "InvalidJSONException",
]


class TrendPullTransportError(Exception):
    """Generic transport error all other pull-transport errors descend from."""


class EmptyResponseException(TrendPullTransportError):
    """The remote returned an empty body (usually a bot-detection response)."""


class InvalidJSONException(TrendPullTransportError):
    """The remote returned a body that could not be decoded as JSON."""


def random_choice(choices: list | None) -> Any:
    """Return a random element of ``choices``, or ``None`` when empty/absent.

    Ported verbatim from upstream ``helpers.random_choice`` — used to spread the
    session pool across the provided msTokens / proxies.
    """
    if not choices:
        return None
    return random.choice(choices)


# A trimmed set of init scripts applied to every page before navigation. Kept
# deliberately small (the pull paths only need the coarse headless tells hidden);
# the values are spoofed to a common desktop-Chrome profile.
STEALTH_SCRIPTS: tuple[str, ...] = (
    # Remove the automation flag most bot filters key on.
    "Object.defineProperty(Object.getPrototypeOf(navigator), 'webdriver', "
    "{ get: () => undefined });",
    # Plausible plugin + language surface for a desktop browser.
    "Object.defineProperty(navigator, 'languages', "
    "{ get: () => ['en-US', 'en'] });",
    "Object.defineProperty(navigator, 'plugins', "
    "{ get: () => [1, 2, 3, 4, 5] });",
    # A non-headless-looking hardware profile.
    "Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });",
    # Grant a chrome runtime object so `window.chrome` isn't conspicuously absent.
    "window.chrome = window.chrome || { runtime: {} };",
    # Answer permission queries the way a real browser does.
    "const _q = window.navigator.permissions && window.navigator.permissions.query;"
    "if (_q) { window.navigator.permissions.query = (p) => ("
    "p && p.name === 'notifications' "
    "? Promise.resolve({ state: Notification.permission }) : _q(p)); }",
)


async def stealth_async(page: Any) -> None:
    """Apply the trimmed stealth init scripts to a Playwright ``page``.

    Each script is registered via ``add_init_script`` so it runs on every
    navigation. A failure to inject one patch is swallowed (best-effort
    hardening must never break session creation).
    """
    for script in STEALTH_SCRIPTS:
        try:
            await page.add_init_script(script)
        except Exception:  # noqa: BLE001 - stealth is best-effort hardening
            continue
