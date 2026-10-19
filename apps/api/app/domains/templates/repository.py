"""TemplateInstance repository — record instantiations + genre analytics.

Records each template→reel instantiation and answers the analytics the growth
team needs: which genres creators actually run (``popular_templates``) and a
creator's own history (``list_for_user``). Session-injected; the pure templates
service stays pure — the router calls ``record`` after a successful instantiate.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from app.models.db.templates import TemplateInstance


class TemplateInstanceRepository:
    """CRUD + analytics for ``template_instances``."""

    def __init__(self, session: Any) -> None:
        self._s = session

    def record(
        self, *, user_id: str, template_slug: str, template_version: str,
        inputs: dict, duration_s: float, reel_job_id: str = "",
    ) -> TemplateInstance:
        row = TemplateInstance(
            user_id=user_id, template_slug=template_slug, template_version=template_version,
            inputs=dict(inputs or {}), duration_s=int(round(duration_s)), reel_job_id=reel_job_id,
        )
        self._s.add(row)
        self._s.flush()
        return row

    def get(self, instance_id: str) -> TemplateInstance | None:
        return self._s.get(TemplateInstance, instance_id)

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[TemplateInstance]:
        return (
            self._s.query(TemplateInstance)
            .filter(TemplateInstance.user_id == user_id)
            .order_by(TemplateInstance.created_at.desc())
            .limit(limit)
            .all()
        )

    def popular_templates(self, *, limit: int = 10) -> list[dict]:
        """Most-instantiated templates (slug, count) — genre conversion analytics."""
        rows = (
            self._s.query(
                TemplateInstance.template_slug,
                func.count(TemplateInstance.id).label("count"),
            )
            .group_by(TemplateInstance.template_slug)
            .order_by(func.count(TemplateInstance.id).desc())
            .limit(limit)
            .all()
        )
        return [{"template_slug": slug, "count": int(count)} for slug, count in rows]
