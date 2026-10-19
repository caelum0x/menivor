"""Small, dependency-explicit liveness and readiness checks for deployment probes."""

from __future__ import annotations

from typing import Callable

from sqlalchemy import text

from app.config import config


def check_runtime_storage() -> None:
    """Verify the backend-owned runtime directories are writable/available.

    API and workers share this volume for temporary GPU inputs and local render
    outputs before R2 upload; accepting a job without it would strand work.
    """
    from app.bootstrap import RUNTIME_ROOT, ensure_runtime_directories

    ensure_runtime_directories()
    required = (RUNTIME_ROOT / "data", RUNTIME_ROOT / "output", RUNTIME_ROOT / "temp")
    if not all(path.is_dir() for path in required):
        raise RuntimeError("runtime storage directories are unavailable")


def check_database() -> None:
    """Verify the database can accept and execute one cheap query."""
    from app.models.db.base import get_engine

    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def check_redis() -> None:
    """Verify the shared broker/state Redis is reachable."""
    import redis

    app_cfg = config.app
    client = redis.Redis(
        host=app_cfg.get("redis_host", "localhost"),
        port=int(app_cfg.get("redis_port", 6379)),
        db=int(app_cfg.get("redis_db", 0)),
        password=app_cfg.get("redis_password", "") or None,
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
    )
    if not client.ping():
        raise RuntimeError("Redis PING returned false")


def check_r2() -> None:
    """Verify configured R2 credentials can address the configured bucket."""
    from app.platform.storage.r2 import get_r2_client

    get_r2_client().healthcheck()


def check_generation_worker() -> None:
    """Verify at least one worker can receive generation work.

    A healthy HTTP process with no render consumer would accept and debit jobs
    that can never complete. Celery's control ping uses the broker, so it also
    confirms the worker is connected to the same Redis deployment.
    """
    from app.workers.celery_app import celery_app

    inspector = celery_app.control.inspect(timeout=0.75)
    replies = inspector.ping()
    if not replies:
        raise RuntimeError("no Celery worker replied to readiness ping")
    queues = inspector.active_queues() or {}
    has_generation_consumer = any(
        queue.get("name") == "generation"
        for worker_queues in queues.values()
        for queue in worker_queues
    )
    if not has_generation_consumer:
        raise RuntimeError("no worker consumes the generation queue")


def readiness() -> tuple[bool, dict[str, str]]:
    """Run every critical dependency check without leaking provider details."""
    checks: tuple[tuple[str, Callable[[], None]], ...] = (
        ("runtime", check_runtime_storage),
        ("database", check_database),
        ("redis", check_redis),
        ("r2", check_r2),
        ("worker", check_generation_worker),
    )
    results: dict[str, str] = {}
    ready = True
    for name, check in checks:
        try:
            check()
        except Exception:
            ready = False
            results[name] = "down"
        else:
            results[name] = "ok"
    return ready, results
