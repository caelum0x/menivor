"""The Railyard consumer contract, Menivor side (Wave P dispatch 5.3 and 5.4).

One place for the env names, the meter codes, the Rago event shape and the
transaction id formats, so ``meters``, ``grants`` and the tests all agree.
The contract fixtures from PY1.5 replace
``tests/reelforge/fixtures/railyard-consumer-contract.json`` when they land.

Env (filled on the boxes by ``gen-secrets.sh``, never committed):
    RELAY_URL, RELAY_KEY          Relay (LLM gateway); RELAY_API_KEY and
                                  RAILYARD_RELAY_* are accepted too
    RAGO_URL, RAGO_API_KEY        Rago events (RAILYARD_RAGO_* accepted too)
    MINT_URL, MINT_API_KEY        Mint (MINT_SERVER_URL accepted too)
    MINT_MIRROR_PATH              the Mint ledger-mirror endpoint path, set when
                                  PY1.5 publishes it; unset means Dodo mirror
                                  entries wait in the outbox
    RAILYARD_LIVE                 0 or 1: 1 sends events and makes Relay the
                                  only way to reach an LLM
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any, Optional

PRODUCT = "menivor"
MENIVOR_METERS: tuple[str, ...] = (
    "menivor.reel.rendered",
    "menivor.preset.render",
    "menivor.lora.train",
    "menivor.ott.gb_stored",
    "menivor.ott.minutes_delivered",
    "menivor.ott.encode_minutes",
    "menivor.ai.minutes",
)
REEL_RENDERED, PRESET_RENDER, LORA_TRAIN = MENIVOR_METERS[:3]
RAGO_EVENTS_PATH = "/api/v1/events"
_ON = {"1", "true", "yes", "on"}

Env = Mapping[str, Optional[str]]


def _read(env: Env, *names: str) -> str:
    for name in names:
        value = env.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def railyard_live(env: Optional[Env] = None) -> bool:
    return _read(env if env is not None else os.environ, "RAILYARD_LIVE").lower() in _ON


def transaction_id(code: str, source_id: str) -> str:
    """``<product>:<meter>:<source id>``; the meter is the code without the product prefix."""
    if code not in MENIVOR_METERS:
        raise ValueError(f"{code!r} is not a Menivor meter")
    source = str(source_id or "").strip()
    if not source:
        raise ValueError("a meter event needs a source id")
    return f"{PRODUCT}:{code[len(PRODUCT) + 1:]}:{source}"


def grant_transaction_id(org_id: str, period: str, n: int) -> str:
    """``<aud>:grant:<org>:<grant_period>:<n>`` (contract 5.4)."""
    return f"{PRODUCT}:grant:{org_id}:{period}:{int(n)}"


def rago_event(
    *,
    code: str,
    source_id: str,
    customer: str,
    timestamp: Optional[float] = None,
    properties: Optional[Mapping[str, Any]] = None,
    transaction: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "transaction_id": transaction or transaction_id(code, source_id),
        "external_customer_id": str(customer or ""),
        "code": code,
        "timestamp": int(timestamp if timestamp is not None else time.time()),
        "properties": dict(properties or {}),
    }


def rago_target(env: Env) -> tuple[str, str]:
    url = _read(env, "RAGO_URL", "RAILYARD_RAGO_URL").rstrip("/")
    return url, _read(env, "RAGO_API_KEY", "RAILYARD_RAGO_API_KEY")


def mint_target(env: Env) -> tuple[str, str, str]:
    url = _read(env, "MINT_URL", "MINT_SERVER_URL").rstrip("/")
    return url, _read(env, "MINT_API_KEY"), _read(env, "MINT_MIRROR_PATH")


def relay_url(env: Env) -> str:
    return _read(env, "RELAY_URL", "RAILYARD_RELAY_URL").rstrip("/")
