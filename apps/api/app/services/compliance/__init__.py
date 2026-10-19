"""ReelForge data-governance services (Compliance / GDPR / SOC2, Epic 5).

Native data-governance logic layered over the existing model (no heavy OSS
fork) — it reuses the Epic 1 audit trail (:mod:`app.services.audit`), the RBAC
decision engine (:mod:`app.services.rbac`), Cloudflare R2
(:mod:`app.services.storage.r2`) and the Celery beat scheduler.

Four crisp, strictly-scoped capabilities:

* :mod:`app.services.compliance.export` — assemble and hand back a COMPLETE,
  requester-scoped data package (GDPR Art. 15 / 20) via a short-lived, private,
  owner-scoped signed R2 URL.
* :mod:`app.services.compliance.erasure` — ANONYMIZE a user's PII in place
  (GDPR Art. 17) while preserving referential integrity and legally-required
  financial / audit records; idempotent and audited.
* :mod:`app.services.compliance.retention` — enforce per-workspace retention
  windows (the Celery-beat sweep) and get/set a workspace's policy
  (``workspace.settings`` RBAC-gated).
* :mod:`app.services.compliance.consent` — record and read a user's consent
  decisions.

HARD invariant across every entrypoint: an export or erasure returns / affects
ONLY the requesting user's (or their RBAC-gated workspace's) data — no path can
ever reach another user's rows.
"""

from __future__ import annotations

from app.services.compliance import consent, erasure, export, retention

__all__ = ["consent", "erasure", "export", "retention"]
