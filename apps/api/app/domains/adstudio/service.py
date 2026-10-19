"""Ad Studio use cases, independent of HTTP.

Network work (page fetch, LLM, image download/upload) always happens before a
DB session is opened; the controller then persists inside one short
transaction. Every error is an :class:`AdStudioError` carrying an HTTP status
and a user-presentable message.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.domains.adstudio import angles as angle_lib
from app.domains.adstudio.fetch import FetchError
from app.domains.adstudio.images import owned_image_entries, register_images, store_remote_images
from app.domains.adstudio.repository import AdStudioRepository
from app.domains.adstudio.scrape import manual_product, scrape_product
from app.domains.adstudio.variants import FORMATS, plan_matrix
from app.domains.adstudio.worker import STALE_RENDER_S

MAX_ACTIVE_RENDERS_PER_USER = 40
_EDITABLE_ANGLE_FIELDS = ("hook", "pain", "proof", "offer", "cta")


class AdStudioError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _language(requested: str | None, product: dict[str, Any]) -> str:
    value = (requested or "").strip().lower()
    if value in ("tr", "en"):
        return value
    return "tr" if product.get("language") == "tr" else "en"


def resolve_product(url: str | None, manual: dict[str, Any] | None) -> dict[str, Any]:
    try:
        if manual and str(manual.get("title") or "").strip():
            return manual_product(manual, url or "")
        if url:
            return scrape_product(url)
    except FetchError as exc:
        raise AdStudioError(exc.status_code, exc.message) from exc
    raise AdStudioError(422, "paste a product URL or enter the product details")


def make_angles(product: dict[str, Any], language: str, count: int, use_llm: bool) -> list[dict[str, Any]]:
    if use_llm:
        return angle_lib.llm_angles(product, language, count)
    return angle_lib.template_angles(product, language, count)


def analyze(url: str | None, manual: dict[str, Any] | None, language: str | None, count: int, use_llm: bool) -> dict[str, Any]:
    """Stateless preview: product + angles (nothing persisted)."""
    product = resolve_product(url, manual)
    lang = _language(language, product)
    return {"product": product, "language": lang, "angles": make_angles(product, lang, count, use_llm)}


def sanitize_angles(raw: list[dict[str, Any]], product: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Accept user-edited angle copy, rebuilding derived fields server-side."""
    clean: list[dict[str, Any]] = []
    for index, item in enumerate(raw[: len(angle_lib.ANGLE_KINDS)]):
        kind = str(item.get("kind") or "").strip()
        if kind not in angle_lib.ANGLE_KINDS:
            kind = angle_lib.ANGLE_KINDS[index % len(angle_lib.ANGLE_KINDS)]
        fields = {f: " ".join(str(item.get(f) or "").split())[: angle_lib.FIELD_MAX] for f in _EDITABLE_ANGLE_FIELDS}
        if not fields["hook"]:
            raise AdStudioError(422, f"angle {index + 1} needs a hook")
        angle = angle_lib.finish_angle(kind, fields, product, language, str(item.get("source") or "edited")[:12], index)
        clean.append(angle)
    if not clean:
        raise AdStudioError(422, "at least one ad angle is required")
    return clean


def prepare_project(
    *, url: str | None, manual: dict[str, Any] | None, language: str | None,
    angles: list[dict[str, Any]] | None, count: int, use_llm: bool,
) -> dict[str, Any]:
    """Network phase of project creation (no DB)."""
    product = resolve_product(url, manual)
    lang = _language(language, product)
    final_angles = sanitize_angles(angles, product, lang) if angles else make_angles(product, lang, count, use_llm)
    stored = store_remote_images(list(product.get("images") or []))
    return {"id": uuid.uuid4().hex, "product": product, "language": lang, "angles": final_angles, "stored": stored}


def persist_project(session: Any, *, user_id: str, prepared: dict[str, Any], title: str, image_keys: list[str]) -> Any:
    from app.domains.media.service import MediaDomainError

    try:
        owned = owned_image_entries(session, user_id=user_id, keys=image_keys)
    except MediaDomainError as exc:
        raise AdStudioError(exc.status_code, exc.message) from exc
    imported = register_images(session, user_id=user_id, project_id=prepared["id"], stored=prepared["stored"])
    product = prepared["product"]
    return AdStudioRepository(session).create_project(
        id=prepared["id"],
        user_id=user_id,
        title=(title or product.get("title") or "Product ad")[:200],
        source_url=str(product.get("url") or "")[:2000],
        source=str(product.get("source") or "generic")[:20],
        language=prepared["language"],
        product=product,
        angles=prepared["angles"],
        images=(owned + imported)[:8],
    )


def queue_variants(
    session: Any, *, user_id: str, project: Any, angle_ids: list[str], formats: list[str],
    aspects: list[str], options: dict[str, str],
) -> list[str]:
    """Create queued variant rows; returns ids to dispatch after commit."""
    angles_by_id = {str(a.get("id")): a for a in project.angles or []}
    missing = [a for a in angle_ids if a not in angles_by_id]
    if missing:
        raise AdStudioError(422, f"unknown angle(s): {', '.join(missing)}")
    try:
        combos = plan_matrix(angle_ids, formats, aspects)
    except ValueError as exc:
        raise AdStudioError(422, str(exc)) from exc
    if not project.images:
        raise AdStudioError(422, "add at least one product image before rendering ads")
    if "ugc_avatar" in formats and not options.get("avatar_id"):
        raise AdStudioError(422, "pick an avatar for UGC avatar ads")
    from app.domains.adstudio.models import AdVariant

    active = (
        session.query(AdVariant)
        .filter(AdVariant.user_id == user_id, AdVariant.status.in_(("queued", "rendering")))
        .count()
    )
    if active + len(combos) > MAX_ACTIVE_RENDERS_PER_USER:
        raise AdStudioError(429, "too many ads are rendering; wait for the current batch to finish")
    repo = AdStudioRepository(session)
    ids: list[str] = []
    for angle_id, fmt, aspect in combos:
        angle = angles_by_id[angle_id]
        variant = repo.create_variant(
            project_id=project.id, user_id=user_id, angle_id=angle_id, format=fmt, aspect=aspect,
            status="queued", script=str(angle.get("script") or ""),
            spec={"angle": angle, "options": {k: v for k, v in options.items() if v} if fmt == "ugc_avatar" else {}},
        )
        ids.append(variant.id)
    return ids


def attach_job(session: Any, *, user_id: str, variant: Any, job_id: str) -> None:
    """Link the reel job the client created from ``spec.job_request``."""
    from app.models.db.models import Job

    if variant.format != "ugc_avatar" or variant.status not in ("ready", "failed"):
        raise AdStudioError(409, "this ad is not waiting for a reel job")
    job = session.query(Job).filter(Job.id == job_id, Job.user_id == user_id).first()
    if job is None:
        raise AdStudioError(404, "reel job not found")
    params = dict(job.params or {})
    if str(params.get("screen_recording_key") or "") != variant.output_key:
        raise AdStudioError(409, "that reel job was not created from this ad")
    variant.job_id, variant.status, variant.error = job.id, "submitted", ""


def retry_variant(variant: Any) -> bool:
    """Reset a failed variant. Returns True when a local render must be queued."""
    if variant.status != "failed":
        raise AdStudioError(409, "only failed ads can be retried")
    variant.error = ""
    if variant.format == "ugc_avatar" and variant.output_key and (variant.spec or {}).get("job_request"):
        variant.status, variant.job_id = "ready", ""
        return False
    variant.status, variant.output_key, variant.poster_key = "queued", "", ""
    return True


def sweep(session: Any, project_id: str) -> None:
    AdStudioRepository(session).fail_stale_renders(project_id, older_than_s=STALE_RENDER_S)


def sync_jobs(session: Any, variants: list[Any]) -> dict[str, Any]:
    """Fold linked reel job state onto UGC variants; returns jobs by id."""
    from app.models.const import TASK_STATE_COMPLETE, TASK_STATE_FAILED
    from app.models.db.models import Job

    ids = [v.job_id for v in variants if v.job_id]
    if not ids:
        return {}
    jobs = {j.id: j for j in session.query(Job).filter(Job.id.in_(ids)).all()}
    for variant in variants:
        job = jobs.get(variant.job_id)
        if job is None or variant.status not in ("submitted", "done", "failed"):
            continue
        if job.state == TASK_STATE_COMPLETE and job.result_key and variant.status != "done":
            variant.status, variant.error = "done", ""
        elif job.state == TASK_STATE_FAILED and variant.status == "submitted":
            variant.status = "failed"
            variant.error = (job.error or "the avatar reel failed")[:500]
    return jobs


__all__ = [
    "AdStudioError",
    "FORMATS",
    "analyze",
    "attach_job",
    "make_angles",
    "persist_project",
    "prepare_project",
    "queue_variants",
    "retry_variant",
    "sanitize_angles",
    "sweep",
    "sync_jobs",
]
