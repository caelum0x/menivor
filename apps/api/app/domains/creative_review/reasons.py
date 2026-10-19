"""Reason chips for the review queue (fixed list; the UI shows them as one-tap chips)."""

from __future__ import annotations

from typing import Any

APPROVE_REASONS: dict[str, str] = {
    "on_brand": "On brand",
    "strong_hook": "Strong hook",
    "ready_to_post": "Ready to post",
}
FIX_REASONS: dict[str, str] = {
    "off_brand": "Off brand",
    "weak_hook": "Weak hook",
    "visual_issue": "Visual issue",
    "wrong_product": "Wrong product",
    "text_error": "Text error",
    "too_long": "Too long",
}
#: What a regenerate asks the model to change, per reason.
CHANGE_REQUEST: dict[str, str] = {
    "off_brand": "Match the brand colors, voice and audience more closely",
    "weak_hook": "Open with a stronger, clearer hook in the first two seconds",
    "visual_issue": "Fix the visuals: clean framing, natural hands and faces, no artifacts",
    "wrong_product": "Show the right product, clearly and in use",
    "text_error": "Fix the on-screen text: correct spelling, short and readable",
    "too_long": "Make it shorter and tighter",
}


class ReasonError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = 422


def check(decision: str, reason: str) -> str:
    """The reason id ("" when none given). Approve takes approve chips; reject/regenerate take fix chips."""
    value = str(reason or "").strip()
    if not value:
        if decision == "regenerate":
            raise ReasonError("Pick what to change before regenerating.")
        return ""
    allowed = APPROVE_REASONS if decision == "approve" else FIX_REASONS
    if value not in allowed:
        raise ReasonError("Pick one of the reason chips.")
    return value


def label(reason: str) -> str:
    return APPROVE_REASONS.get(reason) or FIX_REASONS.get(reason) or ""


def catalog() -> dict[str, Any]:
    return {
        "approve": [{"id": k, "label": v} for k, v in APPROVE_REASONS.items()],
        "fix": [{"id": k, "label": v} for k, v in FIX_REASONS.items()],
    }


__all__ = ["APPROVE_REASONS", "CHANGE_REQUEST", "FIX_REASONS", "ReasonError", "catalog", "check", "label"]
