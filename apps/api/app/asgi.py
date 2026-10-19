"""Application implementation - ASGI."""

import os
from contextlib import asynccontextmanager

from app.bootstrap import ensure_runtime_directories
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config import config
from app.core.observability import correlation_middleware, request_correlation_id
from app.core.public_errors import public_message
from app.models.exception import HttpException
from app.router import root_api_router
from app.services import health
from app.utils import utils

VALIDATION_MESSAGE = "Some details aren't valid. Check them and try again."


@asynccontextmanager
async def application_lifespan(_: FastAPI):
    """Start only the public ReelForge API process dependencies.

    GPU generation runs in the dedicated Celery generation worker. Importing
    or starting the historical Pixelle HTTP application here would create a
    second, unauthenticated product surface and consume worker resources in
    every API replica.
    """
    logger.info("startup event")
    ensure_runtime_directories()

    # Configuration preflight (same checks as tools/ops/preflight.py). Under a
    # public launch posture (mode=public or any launch flag enabled) a missing
    # or misshaped required variable raises and ABORTS startup, listing every
    # problem by name (never values). In internal_pilot/dev it only warns, so
    # local development and the hermetic test suites start exactly as before.
    from app.core.launch_preflight import enforce_startup_preflight

    enforce_startup_preflight(logger.warning)

    # Wave Q QM1.2 (P-M8): OTT geo rules stay off, with this warning, until the edge marker is configured.
    from app.domains.ott_access import geo as ott_geo

    ott_geo.startup_check(logger.warning)

    # Mobile sign-in (Supabase-compatible auth on Scribase): one clear line when
    # SUPABASE_URL is unset (linking off, 503) or which issuer is trusted.
    try:
        from app.core import supabase_auth

        supabase_auth.startup_check()
    except Exception as exc:  # noqa: BLE001 - a config check must never block startup
        logger.warning(f"mobile sign-in startup check failed: {exc}")

    # Wire Sentry for the API process. NO-OP when [sentry].dsn is unset; never
    # raises (init_sentry swallows its own errors) so it cannot block startup.
    from app.telemetry.sentry import init_sentry

    init_sentry("api")

    # 跨平台发布由当前进程线程池执行，不会在服务重启后恢复。启动时把 Redis
    # 中确认已失去执行进程的活动状态收敛为失败，避免任务永久无法删除。
    from app.services import task as task_service

    task_service.recover_interrupted_cross_posts()
    try:
        yield
    finally:
        logger.info("shutdown event")


def exception_handler(request: Request, e: HttpException):
    """Return a short human ``message``; the raw detail stays in the log.

    ``HttpException`` already logged the full internal message (request id,
    exception text) when it was constructed. The response carries the request
    id in its own field so support can trace it without showing it to people.
    """
    request_id = request_correlation_id(request)
    content = utils.get_response(
        e.status_code,
        e.data,
        public_message(e.status_code, e.message, (e.task_id, request_id)),
    )
    content["request_id"] = request_id
    return JSONResponse(status_code=e.status_code, content=content)


def validation_exception_handler(request: Request, e: RequestValidationError):
    request_id = request_correlation_id(request)
    content = utils.get_response(
        status=400,
        data=e.errors(),
        message=VALIDATION_MESSAGE,
    )
    content["request_id"] = request_id
    return JSONResponse(status_code=400, content=content)


def get_application() -> FastAPI:
    """Initialize FastAPI application.

    Returns:
       FastAPI: Application object instance.

    """
    from app.core import api_docs

    docs_mode = api_docs.docs_mode()
    instance = FastAPI(
        title=config.project_name,
        description=config.project_description,
        version=config.project_version,
        debug=False,
        lifespan=application_lifespan,
        # /docs and /openapi.json are staff-only unless MENIVOR_API_DOCS=public.
        **api_docs.fastapi_docs_kwargs(docs_mode),
    )
    api_docs.install(instance, docs_mode)
    instance.middleware("http")(correlation_middleware)
    # Unhandled exceptions become a JSON 500 inside CORSMiddleware (added
    # below), so browsers see a real server error, not a CORS/network failure.
    from app.core.unhandled_errors import unhandled_error_middleware

    instance.middleware("http")(unhandled_error_middleware)
    # Binds the HTTP scope so launch gates can honour the pilot staff allow-list.
    from app.core.launch.policy import LaunchRequestScopeMiddleware

    instance.add_middleware(LaunchRequestScopeMiddleware)
    # Every generation prompt is screened by the moderation gate (default:
    # gpt-oss-safeguard against the Acceptable Use Policy) after validation and
    # before the handler, so a blocked prompt is never charged.
    # See app/core/moderation.py.
    from fastapi import Depends

    from app.core.moderation import moderate_generation_request

    instance.include_router(
        root_api_router, dependencies=[Depends(moderate_generation_request)]
    )

    @instance.get("/healthz", include_in_schema=False)
    def healthz():
        """Liveness probe: the API process is serving requests."""
        return {"status": "ok"}

    @instance.get("/readyz", include_in_schema=False)
    def readyz():
        """Readiness probe: DB, Redis, and R2 are all reachable."""
        ready, checks = health.readiness()
        status = 200 if ready else 503
        body = {"status": "ready" if ready else "not_ready", "checks": checks}
        return JSONResponse(status_code=status, content=body)

    instance.add_exception_handler(HttpException, exception_handler)
    instance.add_exception_handler(RequestValidationError, validation_exception_handler)
    return instance


app = get_application()

# The default permits local clients only. Production deployments must provide
# their exact HTTPS origins; an explicitly configured wildcard cannot carry
# credentialed browser requests.
cors_allowed_origins_str = os.getenv("CORS_ALLOWED_ORIGINS", "")
origins = [
    origin.strip()
    for origin in cors_allowed_origins_str.split(",")
    if origin.strip()
] or ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)

if os.getenv("REELFORGE_EXPOSE_LEGACY_TASKS", "").lower() in {"1", "true", "yes", "on"}:
    task_dir = utils.task_dir()
    app.mount(
        "/tasks",
        StaticFiles(directory=task_dir, html=True, follow_symlink=False),
        name="legacy-tasks",
    )

public_dir = utils.public_dir()
app.mount("/", StaticFiles(directory=public_dir, html=True), name="")
