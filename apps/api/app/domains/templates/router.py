"""Shot-template HTTP domain — browse + compile + instantiate.

Routes under ``/api/v1`` via :func:`app.controllers.v1.base.new_router`, MPT
envelope + :class:`HttpException` like the catalog domain. The engine is pure code
(no DB), so these endpoints have no guarded-DB block and never 503; a bad
selection is a clean 422 via :class:`TemplateError`.

* ``GET  /templates``                    list system genre templates
* ``GET  /templates/{slug}``             full template (slots + inputs)
* ``POST /templates/{slug}/compile``     inputs → timed RenderSpec (preview)
* ``POST /templates/{slug}/instantiate`` inputs → pipeline-ready reel draft
"""

from __future__ import annotations

from fastapi import Path, Request

from app.controllers import base
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.utils import utils

from . import service
from .schemas import CompileRequest, template_detail, template_summary
from .validation import TemplateError

# Guarded persistence — instantiation history + popularity analytics. The
# core browse/compile/instantiate endpoints stay DB-free; these degrade to 503.
try:
    from app.core.api_dependencies import (
        get_session,
        require_database as _require_db,
        resolve_principal as _resolve_user,
    )
    from app.domains.templates.repository import TemplateInstanceRepository

    _DB_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    _DB_IMPORT_ERROR = exc

router = new_router()


def _record_instance_best_effort(request: Request, request_id: str, result: dict) -> None:
    """Record a template instantiation for analytics (never fails the response).

    Only runs when the DB layer + an authenticated user resolve; a missing DB or
    an anonymous caller silently skips (the instantiate result is unaffected).
    """
    if _DB_IMPORT_ERROR is not None:
        return
    try:
        with get_session() as session:
            user = _resolve_user(request, session, request_id)
            spec = result.get("render_spec") or {}
            TemplateInstanceRepository(session).record(
                user_id=user.id,
                template_slug=_internal_slug(result.get("template", "")),
                template_version=result.get("version", ""),
                inputs=result.get("reel_draft", {}),
                duration_s=float(spec.get("duration_s", 0) or 0),
            )
    except Exception:  # noqa: BLE001 - analytics is best-effort, never fatal
        pass


def _internal_slug(slug: str) -> str:
    from .presets.aliases import internal_slug

    return internal_slug(slug)


def _bad_request(request_id: str, exc: Exception) -> HttpException:
    return HttpException(task_id=request_id, status_code=422, message=f"{request_id}: {exc}")


def _public_slug(slug: str) -> str:
    from .presets.aliases import public_slug

    return public_slug(slug)


def _public_spec(spec: dict) -> dict:
    if isinstance(spec, dict) and spec.get("template_slug"):
        return {**spec, "template_slug": _public_slug(spec["template_slug"])}
    return spec


def _public_result(result: dict) -> dict:
    """Instantiate output with public slugs (history keeps the internal one)."""
    out = dict(result)
    if out.get("template"):
        out["template"] = _public_slug(out["template"])
    if isinstance(out.get("render_spec"), dict):
        out["render_spec"] = _public_spec(out["render_spec"])
    return out


def _resolve_character(request: Request, request_id: str, character_id: str | None):
    """Load the caller's OWNED character as a pure profile, or ``None``.

    Returns a ``CharacterProfile`` for compilation when ``character_id`` is set
    and resolvable (auth + ownership enforced via the shared jobs helpers); a
    missing DB layer or an unknown/foreign character is a clean error so a bound
    reel never silently renders WITHOUT the identity lock. ``character_id`` unset
    keeps the classic (character-less) compile untouched.
    """
    if not character_id:
        return None
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: characters layer unavailable")
    from app.domains.characters.repository import CharacterRepository, to_profile

    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        row = CharacterRepository(session).get_owned(character_id, user.id)
        if row is None:
            raise HttpException(task_id=request_id, status_code=404,
                                message=f"{request_id}: character not found")
        return to_profile(row)


@router.get("/templates", summary="List genre shot-templates")
def list_templates(request: Request):
    """Browse the seeded viral-genre templates (story split, ASMR, recap…)."""
    _ = base.get_task_id(request)
    return utils.get_response(
        200, {"templates": [template_summary(t) for t in service.list_templates()]}
    )


# NOTE: these literal routes MUST precede ``/templates/{slug}`` so the path
# ``/templates/backgrounds`` isn't captured as slug="backgrounds".
@router.get("/templates/backgrounds", summary="Browse the background-footage library")
def list_backgrounds(request: Request, category: str = ""):
    """The curated loop-able backgrounds (gameplay parkour, satisfying ASMR, …)
    that split-screen / loop formats auto-fill when the caller supplies no clip."""
    _ = base.get_task_id(request)
    from app.domains.content import background_library as bglib

    clips = bglib.list_backgrounds(category or None)
    return utils.get_response(200, {"backgrounds": [bglib.to_dict(c) for c in clips]})


@router.get("/templates/analytics/popular", summary="Most-instantiated templates")
def popular_templates(request: Request, limit: int = 10):
    """Genre-conversion analytics: which templates creators actually run."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: templates analytics unavailable")
    _require_db(request_id)
    with get_session() as session:
        popular = TemplateInstanceRepository(session).popular_templates(limit=max(1, min(50, limit)))
        return utils.get_response(200, {"popular": [_public_popular(row) for row in popular]})


def _public_popular(row):
    if isinstance(row, dict) and "template_slug" in row:
        return {**row, "template_slug": _public_slug(row["template_slug"])}
    if isinstance(row, dict) and "slug" in row:
        return {**row, "slug": _public_slug(row["slug"])}
    return row


@router.get("/templates/history", summary="Caller's recent template instantiations")
def template_history(request: Request, limit: int = 50):
    """A creator's own instantiation history (reproducibility)."""
    request_id = base.get_task_id(request)
    if _DB_IMPORT_ERROR is not None:
        raise HttpException(task_id=request_id, status_code=503,
                            message=f"{request_id}: templates history unavailable")
    _require_db(request_id)
    with get_session() as session:
        user = _resolve_user(request, session, request_id)
        rows = TemplateInstanceRepository(session).list_for_user(user.id, limit=max(1, min(100, limit)))
        return utils.get_response(200, {
            "history": [
                {"id": r.id, "template_slug": _public_slug(r.template_slug), "template_version": r.template_version,
                 "duration_s": r.duration_s, "reel_job_id": r.reel_job_id}
                for r in rows
            ],
        })


@router.get("/templates/{slug}", summary="Get one shot-template")
def get_template(request: Request, slug: str = Path(...)):
    """Full template detail: segment slots + required inputs."""
    request_id = base.get_task_id(request)
    from .presets import get_template as _get

    tmpl = _get(slug)
    if tmpl is None:
        raise HttpException(task_id=request_id, status_code=404, message=f"{request_id}: unknown template {slug!r}")
    return utils.get_response(200, template_detail(tmpl))


@router.post("/templates/{slug}/compile", summary="Compile a template → render-spec")
def compile_template(request: Request, body: CompileRequest, slug: str = Path(...)):
    """Validate inputs and expand the template into a timed RenderSpec (preview)."""
    request_id = base.get_task_id(request)
    character = _resolve_character(request, request_id, body.character_id)
    try:
        spec = service.compile_spec(
            slug, body.inputs, duration_s=body.duration_s, surface=body.surface, character=character
        )
    except TemplateError as exc:
        raise _bad_request(request_id, exc) from exc
    return utils.get_response(200, _public_spec(spec.to_dict()))


@router.post("/templates/{slug}/instantiate", summary="Template → pipeline-ready reel draft")
def instantiate_template(request: Request, body: CompileRequest, slug: str = Path(...)):
    """Turn a template + inputs into a submittable reel draft (+ compiled spec)."""
    request_id = base.get_task_id(request)
    character = _resolve_character(request, request_id, body.character_id)
    try:
        result = service.instantiate_draft(
            slug, body.inputs, duration_s=body.duration_s, surface=body.surface, character=character
        )
    except TemplateError as exc:
        raise _bad_request(request_id, exc) from exc
    # Best-effort analytics: record the instantiation (never affects the response).
    _record_instance_best_effort(request, request_id, result)
    return utils.get_response(200, _public_result(result))
