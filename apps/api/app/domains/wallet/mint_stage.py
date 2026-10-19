"""Launch-flag **stage machinery** for the Mint-settlement rail.

The wallet is flipped from the local microdollar ledger to the live mint-server
one *stage at a time*, driven purely by config (no code change to promote):

    local  ->  canary(percent)  ->  on

* ``local``  — never route to Mint even when ``MINT_SERVER_URL`` is set. This is
  the kill-switch: promote to ``local`` to instantly fall back to the ledger
  without unsetting the URL/keys.
* ``canary`` — route a deterministic subset of owners (``rollout_percent``) to
  Mint; everyone else stays on the local ledger. The bucket is a stable hash of
  the owner key, so an owner never flip-flops between rails mid-rollout.
* ``on``     — route every wallet job to Mint (the terminal state).

Routing is decided ONCE at reserve time (:func:`should_use_mint`). A job that
reserved on Mint stamps ``mint_hold_id`` into its params marker, so its
settle/release always return to Mint regardless of a later stage change — the
stage only governs where *new* reservations land, never in-flight ones.

Config keys (env wins; see ``app/config/config.py``):
* ``MINT_STAGE``            — ``local`` | ``canary`` | ``on`` (default ``on``
  when the rail is fully configured, else ``local``).
* ``MINT_ROLLOUT_PERCENT``  — integer 0-100, only meaningful in ``canary``.
"""

from __future__ import annotations

import hashlib
from enum import Enum


class MintStage(str, Enum):
    """The three launch stages, ordered ``local < canary < on``."""

    LOCAL = "local"
    CANARY = "canary"
    ON = "on"

    @classmethod
    def parse(cls, raw: object) -> "MintStage":
        """Parse a config value into a stage, defaulting unknown -> ``LOCAL``.

        Fail-safe: an unrecognized/empty stage resolves to ``LOCAL`` so a typo can
        never accidentally route real money to Mint.
        """
        if isinstance(raw, MintStage):
            return raw
        value = str(raw or "").strip().lower()
        for stage in cls:
            if stage.value == value:
                return stage
        return cls.LOCAL


def mint_configured() -> bool:
    """True when the rail is fully wired (URL + api_key + treasury all present).

    A partially-configured rail (e.g. URL but no key) is treated as unconfigured
    so the wallet stays on the local ledger rather than 500-ing on every reserve.
    """
    from app.config import config

    return bool(
        config.mint.get("server_url")
        and config.mint.get("api_key")
        and config.mint.get("treasury_account")
    )


def current_stage() -> MintStage:
    """Resolve the active stage from config.

    Defaults to ``ON`` when the rail is fully configured (so setting
    ``MINT_SERVER_URL`` + keys flips the wallet to Mint without also needing to
    set ``MINT_STAGE``), and ``LOCAL`` when it is not configured at all. An
    explicit ``MINT_STAGE`` always wins.
    """
    from app.config import config

    if not mint_configured():
        return MintStage.LOCAL
    raw = config.mint.get("stage")
    if raw is None or str(raw).strip() == "":
        return MintStage.ON
    return MintStage.parse(raw)


def rollout_percent() -> int:
    """The canary rollout percentage, clamped to ``[0, 100]`` (default ``0``)."""
    from app.config import config

    try:
        pct = int(config.mint.get("rollout_percent", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, pct))


def _bucket(owner_key: str) -> int:
    """Map an owner key to a stable bucket in ``[0, 100)``.

    A cryptographic digest (not Python's salted ``hash``) keeps the bucket stable
    across processes and restarts, so an owner's rail assignment never changes
    within a fixed rollout percentage.
    """
    digest = hashlib.sha256(owner_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100


def should_use_mint(owner_key: str, *, stage: MintStage | None = None) -> bool:
    """Return True when a *new* reservation for ``owner_key`` routes to Mint.

    ``owner_key`` is the wallet owner (workspace id for a shared pool, else the
    user id) so canary bucketing is per-owner and stable. Pass ``stage`` to
    decide against an explicit stage (tests); otherwise the live config stage is
    used. Never routes to Mint when the rail is unconfigured.
    """
    if not mint_configured():
        return False
    resolved = stage if stage is not None else current_stage()
    if resolved is MintStage.ON:
        return True
    if resolved is MintStage.CANARY:
        return _bucket(str(owner_key)) < rollout_percent()
    return False  # LOCAL (or any fail-safe fallback)
