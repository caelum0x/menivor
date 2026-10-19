"""Session-injected MotionRender repository.

CRUD + owner-scoped reads for ``motion_renders``. Never opens its own session
(``add`` + ``flush`` only) — the router owns the ``get_session`` lifecycle so the
pure motion service stays pure.
"""

from __future__ import annotations

from typing import Any

from app.models.db.motion import MotionRender


class MotionRenderRepository:
    """CRUD for the motion-render audit rows."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def create(
        self,
        *,
        user_id: str,
        preset_id: str,
        motion_class: str,
        intensity: int,
        plan: dict,
        provider_key: str = "",
        provider_run_id: str = "",
        output_ref: str = "",
    ) -> MotionRender:
        row = MotionRender(
            user_id=user_id,
            preset_id=preset_id,
            motion_class=motion_class,
            intensity=int(intensity),
            provider_key=provider_key,
            provider_run_id=provider_run_id,
            output_ref=output_ref,
            plan=dict(plan or {}),
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, render_id: str) -> MotionRender | None:
        return self._s.get(MotionRender, render_id)

    def get_owned(self, render_id: str, user_id: str) -> MotionRender | None:
        row = self._s.get(MotionRender, render_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[MotionRender]:
        return (
            self._s.query(MotionRender)
            .filter(MotionRender.user_id == user_id)
            .order_by(MotionRender.created_at.desc())
            .limit(limit)
            .all()
        )

    def delete_owned(self, render_id: str, user_id: str) -> bool:
        row = self.get_owned(render_id, user_id)
        if row is None:
            return False
        self._s.delete(row)
        self._s.flush()
        return True
