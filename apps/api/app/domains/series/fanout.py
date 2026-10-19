"""Clipfarm fan-out planner — body × hooks × templates × aspects × accounts.

Faceless operators run unattended matrices: one body script, N hook variants,
across M templates, K aspect ratios, posted to A accounts. This planner expands
the matrix into concrete render+publish specs, **dedupes by spec-hash** (so an
identical combination is never rendered twice across runs), and **paces** posts
per account to avoid self-cannibalization.

Pure + deterministic — the hash is content-addressed (stable across processes),
so the same matrix always yields the same specs and the same dedupe decisions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from itertools import product


@dataclass(frozen=True)
class FanoutMatrix:
    """The axes of a clipfarm batch. Each list is one dimension of the product."""

    bodies: tuple[str, ...]
    hooks: tuple[str, ...] = ("",)
    templates: tuple[str, ...] = ("",)
    aspects: tuple[str, ...] = ("9:16",)
    accounts: tuple[str, ...] = ("",)


@dataclass(frozen=True)
class ClipSpec:
    """One concrete clip to render + publish."""

    spec_hash: str
    body: str
    hook: str
    template: str
    aspect: str
    account: str

    def as_dict(self) -> dict:
        return {
            "spec_hash": self.spec_hash, "body": self.body, "hook": self.hook,
            "template": self.template, "aspect": self.aspect, "account": self.account,
        }


@dataclass
class FanoutPlan:
    """The planned batch: fresh specs to run + how many were skipped as dupes."""

    specs: list[ClipSpec] = field(default_factory=list)
    skipped_duplicates: int = 0
    total_combinations: int = 0


def spec_hash(body: str, hook: str, template: str, aspect: str, account: str) -> str:
    """Stable content hash of a combination (account-scoped so the same creative
    can legitimately post to different accounts)."""
    payload = json.dumps(
        {"body": body, "hook": hook, "template": template, "aspect": aspect, "account": account},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def plan_fanout(matrix: FanoutMatrix, *, seen_hashes: set[str] | None = None) -> FanoutPlan:
    """Expand ``matrix`` into fresh :class:`ClipSpec`s, skipping seen hashes.

    ``seen_hashes`` is the set already rendered in prior runs (from the DB); any
    combination whose hash is in it — or duplicated within this same matrix — is
    counted as skipped, never emitted twice.
    """
    seen = set(seen_hashes or set())
    plan = FanoutPlan()
    for body, hook, template, aspect, account in product(
        matrix.bodies, matrix.hooks, matrix.templates, matrix.aspects, matrix.accounts
    ):
        plan.total_combinations += 1
        h = spec_hash(body, hook, template, aspect, account)
        if h in seen:
            plan.skipped_duplicates += 1
            continue
        seen.add(h)
        plan.specs.append(
            ClipSpec(spec_hash=h, body=body, hook=hook, template=template, aspect=aspect, account=account)
        )
    return plan


def pace_by_account(specs: list[ClipSpec], *, max_per_account: int) -> list[ClipSpec]:
    """Cap how many specs post to each account this run (cannibalization pacing).

    Keeps input order; the overflow is left for the next run's window. A
    ``max_per_account`` <= 0 means no cap.
    """
    if max_per_account <= 0:
        return list(specs)
    counts: dict[str, int] = {}
    kept: list[ClipSpec] = []
    for spec in specs:
        n = counts.get(spec.account, 0)
        if n >= max_per_account:
            continue
        counts[spec.account] = n + 1
        kept.append(spec)
    return kept
