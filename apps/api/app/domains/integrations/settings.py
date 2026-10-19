"""Env-only settings for the Integrations domain (names only; values never logged)."""

from __future__ import annotations

from app.domains.ads.config import web_url
from app.domains.integrations.connectors.base import env

REDIRECT_ENV = "MENIVOR_INTEGRATIONS_REDIRECT_URL"


def redirect_uri() -> str:
    """Where every provider sends the browser back (the web page finishes the connect)."""
    return env(REDIRECT_ENV) or f"{web_url()}/settings/integrations/callback"


__all__ = ["REDIRECT_ENV", "redirect_uri"]
