"""Environment-based OAuth credential resolution for the publish seam.

The live publish path normally resolves a *per-creator*, Fernet-encrypted OAuth
token from the ``connections`` domain (see :mod:`app.services.oauth_connect`).
For simpler single-account deployments — a self-hosted instance that posts to one
owned TikTok / Instagram / YouTube account — the credentials can instead be
supplied directly through the environment. This module is the one place that
reads them, so the rules stay in a single, testable spot.

Env vars (per platform ``<P>`` ∈ ``TIKTOK`` / ``INSTAGRAM`` / ``YOUTUBE``):

* ``<P>_ACCESS_TOKEN``        — a valid, already-obtained OAuth access token used
  as the fallback bearer token when no per-user token is supplied.
* ``<P>_CLIENT_ID``           — OAuth app client id (shared with
  :mod:`app.services.oauth_connect`).
* ``<P>_CLIENT_SECRET``       — OAuth app client secret.
* ``<P>_EXTERNAL_ACCOUNT_ID`` — the platform-side account id required by some
  APIs (Instagram Graph needs the IG *user* id; also read from
  ``<P>_USER_ID`` as an alias).

Absence is not an error here — resolution always returns a :class:`PlatformCreds`
(possibly empty). The *caller* decides how to degrade (the upload client raises a
clean, human-readable error when no usable token can be found). Nothing here ever
raises, logs, or serialises a secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Scheduler-style aliases the callers may pass; kept here so credential
# resolution never raises on a known alias (unlike the strict DB normalizer).
_ALIASES = {"youtube_shorts": "youtube", "ig": "instagram", "reels": "instagram"}


def normalize_platform(provider: object) -> str:
    """Lower-case, strip and de-alias a provider WITHOUT raising.

    Unlike ``repositories._normalize_provider`` (which rejects unknown tokens so
    an invalid value can never reach a row), this is a soft normalizer for the
    credential/upload path: an unknown token is returned as-is so the *caller*
    can degrade cleanly (an empty creds snapshot / a clear "unsupported platform"
    error) instead of a raw ``ValueError`` escaping.
    """
    token = ("" if provider is None else str(provider)).strip().lower()
    return _ALIASES.get(token, token)


@dataclass(frozen=True)
class PlatformCreds:
    """Immutable snapshot of a platform's env-supplied OAuth credentials."""

    provider: str
    access_token: str = ""
    client_id: str = ""
    client_secret: str = ""
    external_account_id: str = ""

    @property
    def has_token(self) -> bool:
        """True when an env access token is present (the minimum to publish)."""
        return bool(self.access_token)

    @property
    def has_app(self) -> bool:
        """True when the OAuth app id + secret are both configured."""
        return bool(self.client_id and self.client_secret)


def _read(prefix: str, *suffixes: str) -> str:
    """First non-empty ``{prefix}_{suffix}`` env value, trimmed (``""`` if none)."""
    for suffix in suffixes:
        value = os.getenv(f"{prefix}_{suffix}", "").strip()
        if value:
            return value
    return ""


def resolve_platform_creds(provider: str) -> PlatformCreds:
    """Resolve a platform's env credentials into an immutable snapshot.

    Never raises and never returns ``None``; an unconfigured platform yields a
    :class:`PlatformCreds` whose ``has_token`` / ``has_app`` are ``False``.
    """
    normalized = normalize_platform(provider)
    prefix = normalized.upper()
    return PlatformCreds(
        provider=normalized,
        access_token=_read(prefix, "ACCESS_TOKEN"),
        client_id=_read(prefix, "CLIENT_ID"),
        client_secret=_read(prefix, "CLIENT_SECRET"),
        external_account_id=_read(prefix, "EXTERNAL_ACCOUNT_ID", "USER_ID"),
    )


__all__ = ["PlatformCreds", "resolve_platform_creds", "normalize_platform"]
