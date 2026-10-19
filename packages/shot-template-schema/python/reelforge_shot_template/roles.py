"""Canonical slot roles + ordering (mirror of ``src/roles.ts``).

A genre template is a sequence of named segment slots. Roles have a fixed
narrative order so validators can assert monotonic progression.
"""

from __future__ import annotations

# Fixed narrative order (Hook → … → CTA / Loop). This is a superset of the
# backend ``templates`` domain's ``SlotSpec`` roles (``app.domains.templates.slots``)
# so every seeded system template projects onto a valid schema blueprint — the
# backend enforces that parity at registry load (``presets/__init__.py``), which
# is what stops the picker's blueprints and the seeded templates from diverging.
ROLE_ORDER: tuple[str, ...] = (
    "hook",
    "setup",
    "proof1",
    "proof2",
    "rising",
    "body",
    "escalation",
    "exchange",
    "climax",
    "payoff",
    "button",
    "cta",
    "loop",
    "seam",
)

_INDEX = {role: i for i, role in enumerate(ROLE_ORDER)}


def is_role(role: str) -> bool:
    return role in _INDEX


def role_index(role: str) -> int:
    """Ordering index (raises for unknown roles)."""
    if role not in _INDEX:
        raise KeyError(f"unknown slot role {role!r}")
    return _INDEX[role]
