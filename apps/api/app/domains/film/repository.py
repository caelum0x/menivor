"""FilmProject repository — persist a planned film + its locked shots.

Bridges the pure ``film.orchestrator.FilmPlan`` to durable rows: ``create_from_plan``
writes the project + one :class:`FilmShot` per planned shot (prompt + seed +
camera + duration), so a poll worker can render each shot independently and the
project flips to ``shots_ready`` when all shots are done (the stitched final video
is produced separately by the export task).
"""

from __future__ import annotations

from typing import Any

from app.domains.film.orchestrator import FilmPlan
from app.models.db.film import FilmProject, FilmShot


class FilmRepository:
    """Persist + query film projects and their shots."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def create_from_plan(
        self, plan: FilmPlan, *, user_id: str, title: str = "", character_id: str = ""
    ) -> FilmProject:
        project = FilmProject(
            user_id=user_id, title=title, character_id=character_id,
            total_runtime_s=int(round(plan.total_runtime_s)), shot_count=len(plan.shots),
        )
        self._s.add(project)
        self._s.flush()
        for sp in plan.shots:
            self._s.add(FilmShot(
                project_id=project.id,
                shot_key=sp.shot.shot_id,
                order=sp.shot.order,
                role=sp.shot.role,
                camera_motion=sp.shot.camera_motion,
                duration_ms=int(round(sp.shot.duration_s * 1000)),
                prompt=sp.prompt.prompt,
                negative_prompt=sp.prompt.negative_prompt,
                seed=sp.prompt.seed,
            ))
        self._s.flush()
        return project

    def get(self, project_id: str) -> FilmProject | None:
        return self._s.get(FilmProject, project_id)

    def shots(self, project_id: str) -> list[FilmShot]:
        return (
            self._s.query(FilmShot)
            .filter(FilmShot.project_id == project_id)
            .order_by(FilmShot.order.asc())
            .all()
        )

    def mark_shot(self, shot_id: str, *, status: str, render_job_id: str = "") -> FilmShot | None:
        shot = self._s.get(FilmShot, shot_id)
        if shot is None:
            return None
        shot.status = status
        if render_job_id:
            shot.render_job_id = render_job_id
        self._s.flush()
        # When every shot is done the project is ready to export (stitching is a
        # separate, explicit step — see ``POST /film/projects/{id}/export``).
        if status == "done":
            remaining = (
                self._s.query(FilmShot)
                .filter(FilmShot.project_id == shot.project_id, FilmShot.status != "done")
                .count()
            )
            if remaining == 0:
                project = self._s.get(FilmProject, shot.project_id)
                if project is not None and project.status not in ("exporting", "exported"):
                    project.status = "shots_ready"
                    self._s.flush()
        elif status in ("rendering", "failed", "pending"):
            project = self._s.get(FilmProject, shot.project_id)
            # A re-rendered shot invalidates a previous export / ready state.
            if project is not None and project.status in ("shots_ready", "assembled", "exported"):
                project.status = "rendering" if status == "rendering" else "planned"
                self._s.flush()
        return shot

    def list_for_user(self, user_id: str, *, limit: int = 50, offset: int = 0) -> list[FilmProject]:
        return (
            self._s.query(FilmProject)
            .filter(FilmProject.user_id == user_id)
            .order_by(FilmProject.created_at.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, int(limit)))
            .all()
        )

    def rename(self, project_id: str, title: str) -> FilmProject | None:
        project = self.get(project_id)
        if project is None:
            return None
        project.title = (title or "").strip()[:200]
        self._s.flush()
        return project

    def delete(self, project_id: str) -> bool:
        """Hard-delete a project and its shots (render_jobs rows are kept as history)."""
        project = self.get(project_id)
        if project is None:
            return False
        self._s.query(FilmShot).filter(FilmShot.project_id == project_id).delete(
            synchronize_session=False
        )
        self._s.delete(project)
        self._s.flush()
        return True

    def set_export(
        self,
        project_id: str,
        *,
        state: str,
        error: str = "",
        final_key: str | None = None,
    ) -> FilmProject | None:
        from datetime import datetime, timezone

        project = self.get(project_id)
        if project is None:
            return None
        project.export_state = state
        project.export_error = (error or "")[:2000]
        if final_key is not None:
            project.final_key = final_key
        if state in ("queued", "running"):
            project.status = "exporting"
        elif state == "done":
            project.status = "exported"
            project.exported_at = datetime.now(timezone.utc)
        elif state == "failed":
            project.status = "shots_ready"
        self._s.flush()
        return project
