"""Country rules per title (MV5): the viewer's country comes from the edge header ``CF-IPCountry``.

``geo_mode`` is ``all``, ``allow`` (only the listed countries) or ``deny``.
An unknown country (``XX`` or missing) is refused by an ``allow`` rule and
passed by a ``deny`` rule. VPN detection is out of scope (no free, honest source).

**Trusted origin (Wave Q QM1.2, P-M8).** ``CF-IPCountry`` is only believed on
a request that carries the edge's origin marker: the Cloudflare edge (a
Transform Rule, behind authenticated origin pulls) sets ``X-Menivor-Edge`` to
the shared secret in ``OTT_EDGE_SECRET``, and a request without the matching
marker counts as unknown. With no secret configured, geo rules are **off**
(every title plays everywhere) and the API logs a startup warning, because a
header anyone can send is not a country.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from typing import Mapping, Optional

HEADER = "cf-ipcountry"
EDGE_HEADER = "x-menivor-edge"
EDGE_SECRET_ENV = "OTT_EDGE_SECRET"
UNKNOWN = "XX"
MIN_SECRET = 24
STARTUP_WARNING = ("OTT geo rules are OFF: set OTT_EDGE_SECRET and have the edge send X-Menivor-Edge "
                   "(Cloudflare authenticated origin pulls), or CF-IPCountry cannot be trusted")


def _secret(env: Optional[Mapping[str, str]] = None) -> str:
    value = str((env if env is not None else os.environ).get(EDGE_SECRET_ENV) or "").strip()
    return value if len(value) >= MIN_SECRET else ""


def enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Geo rules apply only when the edge marker is configured."""
    return bool(_secret(env))


def trusted(headers: Mapping[str, str], env: Optional[Mapping[str, str]] = None) -> bool:
    secret = _secret(env)
    marker = str(headers.get(EDGE_HEADER) or headers.get("X-Menivor-Edge") or "")
    return bool(secret) and hmac.compare_digest(marker.encode(), secret.encode())


def country(headers: Mapping[str, str], env: Optional[Mapping[str, str]] = None) -> str:
    if not trusted(headers, env):
        return UNKNOWN
    value = str(headers.get(HEADER) or headers.get("CF-IPCountry") or "").strip().upper()
    return value if len(value) == 2 and value.isalpha() else UNKNOWN


def allowed(geo_mode: str, countries: list[str] | tuple[str, ...], viewer_country: str,
            env: Optional[Mapping[str, str]] = None) -> bool:
    if not enabled(env):
        return True  # geo is off until the trusted origin marker is configured
    listed = {c.upper() for c in countries or ()}
    if geo_mode == "allow":
        return viewer_country in listed
    if geo_mode == "deny":
        return viewer_country not in listed
    return True


def startup_check(warn: Callable[[str], None], env: Optional[Mapping[str, str]] = None) -> bool:
    """Warn once at startup when geo is off; returns whether geo is on."""
    on = enabled(env)
    if not on:
        warn(STARTUP_WARNING)
    return on


MESSAGE = "This title is not available in your country."

__all__ = ["EDGE_HEADER", "EDGE_SECRET_ENV", "HEADER", "MESSAGE", "STARTUP_WARNING", "UNKNOWN", "allowed", "country",
           "enabled", "startup_check", "trusted"]
