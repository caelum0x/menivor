"""Repository for :class:`RenderJob` — bridges the pure envelope ↔ the ORM row.

The ``services/render`` envelope is a frozen dataclass (progress 0..1, output_refs
tuple); the persisted row stores progress as 0..100 and output_refs as a
newline-joined blob. This repo converts both ways so the poll worker can load a
row, advance the pure envelope, and save it back within one transaction.
"""

from __future__ import annotations

from typing import Any

from app.models.db.render import RenderJob as RenderJobRow
from app.services.render.envelope import RenderJob as Envelope


def _refs_to_blob(refs: tuple[str, ...]) -> str:
    return "\n".join(r for r in refs if r)


def _blob_to_refs(blob: str) -> tuple[str, ...]:
    return tuple(x for x in (blob or "").split("\n") if x)


def row_to_envelope(row: RenderJobRow) -> Envelope:
    """Project a persisted row into the pure envelope the services use."""
    return Envelope(
        id=row.id,
        backend=row.backend,
        workflow_version=row.workflow_version,
        state=row.state,
        progress=max(0.0, min(1.0, (row.progress or 0) / 100.0)),
        provider_ref=row.provider_ref,
        poll_cursor=row.poll_cursor,
        output_refs=_blob_to_refs(row.output_refs),
        cost_micros=row.actual_cost_micros,
        error=row.error,
        attempts=row.attempts,
    )


class RenderJobRepository:
    """CRUD + envelope sync for ``render_jobs``."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def create(
        self,
        envelope: Envelope,
        *,
        user_id: str,
        workspace_id: str = "",
        held_cost_micros: int = 0,
        source: str = "render",
        label: str = "",
    ) -> RenderJobRow:
        row = RenderJobRow(
            id=envelope.id,
            user_id=user_id,
            workspace_id=workspace_id or "",
            source=(source or "render")[:20],
            label=(label or "")[:200],
            backend=envelope.backend,
            workflow_version=envelope.workflow_version,
            state=envelope.state,
            progress=int(round(envelope.progress * 100)),
            provider_ref=envelope.provider_ref,
            poll_cursor=envelope.poll_cursor,
            held_cost_micros=held_cost_micros,
            actual_cost_micros=envelope.cost_micros,
            output_refs=_refs_to_blob(envelope.output_refs),
            error=envelope.error,
            attempts=envelope.attempts,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, job_id: str) -> RenderJobRow | None:
        return self._s.get(RenderJobRow, job_id)

    def save_envelope(self, envelope: Envelope) -> RenderJobRow | None:
        """Persist an advanced envelope back onto its row (state/progress/output/cost)."""
        row = self.get(envelope.id)
        if row is None:
            return None
        row.state = envelope.state
        row.progress = int(round(envelope.progress * 100))
        row.provider_ref = envelope.provider_ref
        row.poll_cursor = envelope.poll_cursor
        row.output_refs = _refs_to_blob(envelope.output_refs)
        if envelope.cost_micros:
            row.actual_cost_micros = envelope.cost_micros
        row.error = envelope.error
        row.attempts = envelope.attempts
        self._s.flush()
        return row

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        state: str | None = None,
        source: str | None = None,
    ) -> list[RenderJobRow]:
        """The caller's render jobs, newest first (owner-scoped history)."""
        query = self._s.query(RenderJobRow).filter(RenderJobRow.user_id == user_id)
        if state:
            query = query.filter(RenderJobRow.state == state)
        if source:
            query = query.filter(RenderJobRow.source == source)
        return (
            query.order_by(RenderJobRow.created_at.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all()
        )

    def count_for_user(self, user_id: str, *, state: str | None = None, source: str | None = None) -> int:
        query = self._s.query(RenderJobRow).filter(RenderJobRow.user_id == user_id)
        if state:
            query = query.filter(RenderJobRow.state == state)
        if source:
            query = query.filter(RenderJobRow.source == source)
        return int(query.count())

    def list_active(self, *, limit: int = 100) -> list[RenderJobRow]:
        """Non-terminal jobs for the poll worker to advance (oldest first)."""
        return (
            self._s.query(RenderJobRow)
            .filter(RenderJobRow.state.in_(("IN_QUEUE", "IN_PROGRESS")))
            .order_by(RenderJobRow.created_at.asc())
            .limit(limit)
            .all()
        )
