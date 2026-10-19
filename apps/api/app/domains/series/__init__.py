"""Unattended channel-runner (Clipfarm) domain.

Faceless, unattended matrices: a source list is expanded
(``domains.series.fanout``) into de-duplicated render+publish specs, each
rendered as a normal ReelForge job and later cross-posted with per-account
pacing. The pure runner + session-injected repositories are driven both by the
Celery beat (``workers.tasks_series``) and — additively — by the HTTP surface in
:mod:`app.domains.series.router` (read run history / pacing, trigger a render or
publish-pacing pass).
"""

from .router import router

__all__ = ["router"]
