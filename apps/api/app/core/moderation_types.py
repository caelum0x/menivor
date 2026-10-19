"""Shared result/error types for the prompt moderation providers."""

from __future__ import annotations

from dataclasses import dataclass, field

DECISIONS: frozenset[str] = frozenset({"allow", "flag", "deny"})


@dataclass(frozen=True)
class ModerationResult:
    decision: str  # allow | flag | deny
    moderation_id: str = ""
    categories: tuple[str, ...] = field(default_factory=tuple)
    provider: str = ""
    cached: bool = False


class ModerationUnavailable(Exception):
    """The moderation provider could not give a decision (network, 5xx, bad body)."""


class ModerationRateLimited(ModerationUnavailable):
    """The provider answered 429: skip it for a cooldown window, try the next hop."""

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s
