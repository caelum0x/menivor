"""Canonical event catalog + envelope + push mapping (mirror of ``src/*``).

The single source of event names, the ``EventEnvelope`` shape, and the
event→push/deep-link table, so the outbox, SDK webhook types, and the client
notification router all agree. Transport (outbox/dispatch) stays in ``apps/api``;
only this schema is shared. Pure data → byte-identical to the TS port.
"""

from __future__ import annotations

from typing import Any

# --- Canonical event names (single source) ------------------------------- #
EVENT_TYPES: tuple[str, ...] = (
    "job.completed",
    "job.failed",
    "publish.succeeded",
    "publish.failed",
    "retention.ingested",
    "performance.ingested",
    "experiment.winner_selected",
    "gateway.key_spend_exceeded",
    "gateway.plan_changed",
    "marketplace.submission_approved",
    "marketplace.payout_paid",
)

# --- Event → push / notification / deep-link mapping (client) ------------- #
PUSH_MAP: dict[str, dict[str, str]] = {
    "job.completed": {"channel": "push", "title": "Your reel is ready", "deep_link": "/jobs/{job_id}"},
    "job.failed": {"channel": "push", "title": "Reel generation failed", "deep_link": "/jobs/{job_id}"},
    "publish.succeeded": {"channel": "push", "title": "Published", "deep_link": "/publish/{job_id}"},
    "publish.failed": {"channel": "push", "title": "Publish failed", "deep_link": "/publish/{job_id}"},
    "retention.ingested": {"channel": "in_app", "title": "New retention data", "deep_link": "/insights/{job_id}"},
    "performance.ingested": {"channel": "in_app", "title": "Performance updated", "deep_link": "/performance/{job_id}"},
    "experiment.winner_selected": {"channel": "push", "title": "A/B winner picked", "deep_link": "/experiments/{experiment_key}"},
    "gateway.key_spend_exceeded": {"channel": "email", "title": "Spend cap reached", "deep_link": "/gateway"},
    "gateway.plan_changed": {"channel": "in_app", "title": "Plan updated", "deep_link": "/plan"},
    "marketplace.submission_approved": {"channel": "push", "title": "Submission approved", "deep_link": "/clipmarket"},
    "marketplace.payout_paid": {"channel": "push", "title": "You got paid", "deep_link": "/wallet"},
}


def is_event_type(name: str) -> bool:
    return name in EVENT_TYPES


def make_envelope(
    event_type: str,
    payload: dict[str, Any],
    *,
    id: str,
    occurred_at: str,
    workspace_id: str | None = None,
    dedupe_key: str | None = None,
) -> dict[str, Any]:
    """Build a canonical ``EventEnvelope`` (id/occurred_at are supplied by the caller
    so the shape is deterministic + testable)."""
    if not is_event_type(event_type):
        raise ValueError(f"unknown event type {event_type!r}")
    return {
        "id": id,
        "type": event_type,
        "occurred_at": occurred_at,
        "workspace_id": workspace_id,
        "dedupe_key": dedupe_key or f"{event_type}:{id}",
        "payload": payload,
    }


def push_for(event_type: str) -> dict[str, str] | None:
    """The push/notification descriptor for an event type (or None)."""
    return PUSH_MAP.get(event_type)


def validate_envelope(env: dict[str, Any]) -> list[str]:
    """Return a list of envelope violations (empty = valid)."""
    errors: list[str] = []
    for field in ("id", "type", "occurred_at", "dedupe_key", "payload"):
        if field not in env:
            errors.append(f"missing field {field}")
    if "type" in env and not is_event_type(str(env["type"])):
        errors.append(f"unknown event type {env['type']!r}")
    if "payload" in env and not isinstance(env["payload"], dict):
        errors.append("payload must be an object")
    return errors
