"""Owner-scoped persistence queries for Ad Studio projects and variants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.domains.adstudio.models import AdStudioProject, AdVariant


class AdStudioRepository:
    def __init__(self, session: Any) -> None:
        self._session = session

    # -- projects ------------------------------------------------------------
    def create_project(self, **fields: Any) -> AdStudioProject:
        project = AdStudioProject(**fields)
        self._session.add(project)
        self._session.flush()
        return project

    def get_owned_project(self, user_id: str, project_id: str) -> AdStudioProject | None:
        return (
            self._session.query(AdStudioProject)
            .filter(AdStudioProject.id == project_id, AdStudioProject.user_id == user_id)
            .first()
        )

    def list_projects(self, user_id: str, *, limit: int, offset: int) -> tuple[list[AdStudioProject], int]:
        query = self._session.query(AdStudioProject).filter(AdStudioProject.user_id == user_id)
        total = int(query.count())
        rows = (
            query.order_by(AdStudioProject.created_at.desc(), AdStudioProject.id.desc())
            .offset(max(0, offset))
            .limit(max(1, limit))
            .all()
        )
        return rows, total

    def variant_counts(self, project_ids: list[str]) -> dict[str, dict[str, int]]:
        if not project_ids:
            return {}
        counts: dict[str, dict[str, int]] = {}
        rows = (
            self._session.query(AdVariant.project_id, AdVariant.status)
            .filter(AdVariant.project_id.in_(project_ids))
            .all()
        )
        for project_id, status in rows:
            bucket = counts.setdefault(str(project_id), {"total": 0, "done": 0})
            bucket["total"] += 1
            if status == "done":
                bucket["done"] += 1
        return counts

    def delete_project(self, project: AdStudioProject) -> None:
        # Posts of a running "Publish and test" must not go out for a deleted project.
        from app.domains.adstudio.publish_test import retire_project_tests

        retire_project_tests(self._session, str(project.user_id), self.variants(project.id))
        self._session.query(AdVariant).filter(AdVariant.project_id == project.id).delete(
            synchronize_session=False
        )
        self._session.delete(project)
        self._session.flush()

    # -- variants ------------------------------------------------------------
    def create_variant(self, **fields: Any) -> AdVariant:
        variant = AdVariant(**fields)
        self._session.add(variant)
        self._session.flush()
        return variant

    def variants(self, project_id: str) -> list[AdVariant]:
        return (
            self._session.query(AdVariant)
            .filter(AdVariant.project_id == project_id)
            .order_by(AdVariant.created_at.asc(), AdVariant.id.asc())
            .all()
        )

    def get_owned_variant(self, user_id: str, project_id: str, variant_id: str) -> AdVariant | None:
        return (
            self._session.query(AdVariant)
            .filter(
                AdVariant.id == variant_id,
                AdVariant.project_id == project_id,
                AdVariant.user_id == user_id,
            )
            .first()
        )

    def get_variant(self, variant_id: str) -> AdVariant | None:
        return self._session.query(AdVariant).filter(AdVariant.id == variant_id).first()

    def lock_variant(self, variant_id: str) -> AdVariant | None:
        return (
            self._session.query(AdVariant)
            .filter(AdVariant.id == variant_id)
            .with_for_update()
            .first()
        )

    def get_project(self, project_id: str) -> AdStudioProject | None:
        return self._session.query(AdStudioProject).filter(AdStudioProject.id == project_id).first()

    def fail_stale_renders(self, project_id: str, *, older_than_s: int) -> int:
        """Mark renders orphaned by a restart as failed so they can be retried."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_s)
        return int(
            self._session.query(AdVariant)
            .filter(
                AdVariant.project_id == project_id,
                AdVariant.status.in_(("queued", "rendering")),
                AdVariant.updated_at < cutoff,
            )
            .update(
                {"status": "failed", "error": "the render was interrupted; retry it"},
                synchronize_session=False,
            )
        )


__all__ = ["AdStudioRepository"]
