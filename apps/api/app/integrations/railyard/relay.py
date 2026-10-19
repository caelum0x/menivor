"""Route Menivor's LLM calls through Railyard Relay when RAILYARD_RELAY_URL is set.

The transport (OpenAI SDK pointed at ``<relay>/openai/v1``, TensorZero model
names, Abacus cap handling) already lives in ``app.domains.railyard``, which is
gated on ``RELAY_URL``. This module maps the ``RAILYARD_RELAY_*`` names onto
that gate without mutating ``os.environ``: :func:`relay_env` returns an env
mapping the existing helpers accept via their ``env=`` parameter.

With neither variable set, :func:`relay_env` returns the process environment
unchanged, so behavior is identical to before.
"""

from __future__ import annotations

import os
from typing import Dict, Mapping, Optional

from .settings import Env, load_settings


def relay_env(env: Optional[Env] = None) -> Mapping[str, Optional[str]]:
    """Env for ``app.domains.railyard`` with RAILYARD_RELAY_* applied.

    An explicit ``RELAY_URL`` keeps priority (existing deployments). Returns the
    original mapping object when there is nothing to add.
    """
    base = env if env is not None else os.environ
    contract_key = base.get("RELAY_KEY")
    api_key = base.get("RELAY_API_KEY")
    if isinstance(contract_key, str) and contract_key.strip() and not (isinstance(api_key, str) and api_key.strip()):
        # Contract 5.3 names the Relay key RELAY_KEY; the transport reads RELAY_API_KEY.
        base = {**dict(base), "RELAY_API_KEY": contract_key.strip()}
    settings = load_settings(base)
    existing = base.get("RELAY_URL")
    if not settings.relay_enabled or (isinstance(existing, str) and existing.strip()):
        return base
    merged: Dict[str, Optional[str]] = dict(base)
    merged["RELAY_URL"] = settings.relay_url
    existing_key = base.get("RELAY_API_KEY")
    if settings.relay_api_key and not (isinstance(existing_key, str) and existing_key.strip()):
        merged["RELAY_API_KEY"] = settings.relay_api_key
    return merged


def relay_openai_base_url(env: Optional[Env] = None) -> Optional[str]:
    """``<relay>/openai/v1`` when Relay is configured under either name, else ``None``."""
    resolved = relay_env(env)
    url = resolved.get("RELAY_URL")
    if not (isinstance(url, str) and url.strip()):
        return None
    return f"{url.strip().rstrip('/')}/openai/v1"
