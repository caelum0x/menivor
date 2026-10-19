"""SQLAlchemy declarative base, engine and session plumbing for ReelForge.

Per INTEGRATION_CONTRACT.md §4.1. The engine is created from
``config.neon.database_url`` (Neon Postgres) with ``pool_pre_ping=True`` so
stale pooled connections are transparently recycled — important for Neon's
serverless auto-suspend behaviour.

Engine / session-factory creation is done lazily (first use) so that merely
importing this module never crashes the pipeline when the database URL is not
yet configured or the driver is absent. ``get_session()`` is a context manager
usable both from FastAPI dependencies and Celery workers.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeEngine


class Base(DeclarativeBase):
    """Declarative base shared by every ReelForge ORM model."""


def jsonb_variant() -> TypeEngine:
    """A JSON column type that materialises as ``JSONB`` on PostgreSQL.

    PostgreSQL's ``json`` type has no equality operator, so Alembic's
    server-default drift check — which runs ``SELECT <default_a> = <default_b>``
    to compare a column's stored default against the model — fails on any JSON
    column that carries a ``server_default`` (``operator does not exist:
    json = unknown``). ``jsonb`` has ``=`` and is the better type anyway
    (normalised, indexable, deduplicated keys). SQLite and every other dialect
    keep the generic ``JSON`` rendering, mirroring the existing
    ``BigInteger().with_variant(Integer, "sqlite")`` house pattern. A fresh
    instance is returned per call so each column owns its own type object.
    """
    return JSON().with_variant(JSONB(), "postgresql")


def _select_pg_driver() -> str:
    """Return the ``+driver`` suffix for whichever psycopg is installed.

    A bare ``postgresql://`` URL makes SQLAlchemy default to ``psycopg2``. When
    only psycopg 3 (the ``psycopg`` package) is present — as in this runtime —
    that default raises ``ModuleNotFoundError`` at connect time. Selecting the
    installed driver up-front turns that opaque failure into a working engine.
    """
    from importlib.util import find_spec

    if find_spec("psycopg2") is not None:
        return ""  # SQLAlchemy's default; keep the URL untouched.
    if find_spec("psycopg") is not None:
        return "+psycopg"
    return ""  # Neither installed — let SQLAlchemy surface its own clear error.


def _normalize_database_url(raw: str) -> str:
    """Coerce a human-provided database string into a valid SQLAlchemy URL.

    Tolerates the exact snippet Neon's console hands out — a full
    ``psql 'postgresql://…'`` command with surrounding quotes — by extracting
    the embedded connection URL. Normalizes the legacy ``postgres://`` scheme to
    ``postgresql://`` and, for a bare (driver-less) Postgres URL, pins the
    psycopg driver that is actually installed. SQLite URLs pass through
    untouched. Pure and side-effect free; returns ``""`` for empty input.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    # Pull the connection URL out of a pasted shell command / quotes, if any.
    match = re.search(r"(postgres(?:ql)?(?:\+\w+)?://\S+)", text)
    if match:
        text = match.group(1)
    text = text.strip().strip("'").strip('"').strip()
    if text.startswith("sqlite:"):
        return text
    # Legacy scheme alias used by many providers (incl. Neon/Heroku).
    if text.startswith("postgres://"):
        text = "postgresql://" + text[len("postgres://"):]
    if text.startswith("postgresql://"):
        driver = _select_pg_driver()
        if driver:
            text = "postgresql" + driver + "://" + text[len("postgresql://"):]
    return text


def _database_url() -> str:
    """Resolve the Neon/Postgres URL from config with an env fallback.

    Reads ``config.neon.database_url`` (bound in ``app/config/config.py``).
    Falls back to the ``NEON_DATABASE_URL`` env var so the module is usable
    even if the config section has not been bound yet. The resolved value is
    run through :func:`_normalize_database_url` so a pasted ``psql '…'`` snippet
    or a driver-less scheme still yields a connectable engine. Never raises.
    """
    try:
        from app.config import config

        neon = getattr(config, "neon", None)
        if neon is not None:
            url = neon.get("database_url", "") or ""
            if url:
                return _normalize_database_url(url)
    except Exception as exc:  # pragma: no cover - defensive, config optional
        logger.warning(f"Unable to read config.neon.database_url: {exc}")
    return _normalize_database_url(
        os.getenv("REELFORGE_DATABASE_URL", "")
        or os.getenv("NEON_DATABASE_URL", "")
        or os.getenv("DATABASE_URL", "")
    )


_DEFAULT_POOL_SIZE = 2
_DEFAULT_MAX_OVERFLOW = 2
_DEFAULT_POOL_TIMEOUT_S = 30
_DEFAULT_POOL_RECYCLE_S = 1_800


def _bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    """Coerce a deployment pool setting without allowing an unsafe fan-out."""
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _pool_options(url: str, neon: object | None = None) -> dict[str, object]:
    """Return dialect-aware, bounded connection-pool options.

    Neon is most stable behind its pooled/PgBouncer connection string.  The
    application also caps each API/worker process to a deliberately small pool
    so Celery fan-out cannot multiply connections beyond the database budget.
    SQLite test URLs deliberately receive no QueuePool-only options.
    """
    if url.startswith("sqlite:"):
        return {}
    section = neon or {}
    try:
        get = section.get  # type: ignore[union-attr]
    except AttributeError:
        def get(_key: str, default: object) -> object:
            return default
    return {
        "pool_pre_ping": True,
        "pool_size": _bounded_int(
            get("pool_size", _DEFAULT_POOL_SIZE), _DEFAULT_POOL_SIZE, 1, 20
        ),
        "max_overflow": _bounded_int(
            get("max_overflow", _DEFAULT_MAX_OVERFLOW), _DEFAULT_MAX_OVERFLOW, 0, 20
        ),
        "pool_timeout": _bounded_int(
            get("pool_timeout_s", _DEFAULT_POOL_TIMEOUT_S),
            _DEFAULT_POOL_TIMEOUT_S,
            1,
            120,
        ),
        "pool_recycle": _bounded_int(
            get("pool_recycle_s", _DEFAULT_POOL_RECYCLE_S),
            _DEFAULT_POOL_RECYCLE_S,
            60,
            86_400,
        ),
        "pool_use_lifo": True,
    }


# Module-level lazily-populated singletons (§4.1). They start as ``None`` and
# are built on first use so importing this module has no side effects and never
# crashes when the DB is not configured. ``_init_lock`` guards the lazy build
# so ``engine`` and ``SessionLocal`` are published atomically (double-checked
# locking) even when several threads race to initialize them concurrently.
engine: Engine | None = None
SessionLocal: sessionmaker | None = None
_init_lock = threading.Lock()


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine, creating it on first call.

    Thread-safe via double-checked locking so a concurrent
    ``get_sessionmaker()`` never observes ``engine`` set while ``SessionLocal``
    is still ``None``. Raises ``RuntimeError`` (never a bare driver error) when
    no database URL is configured so callers get a clear, actionable message.
    """
    global engine, SessionLocal
    if engine is not None:
        return engine

    with _init_lock:
        # Re-check inside the lock: another thread may have finished the build
        # while we were waiting to acquire it.
        if engine is not None:
            return engine

        url = _database_url()
        if not url:
            raise RuntimeError(
                "No database URL configured. Set REELFORGE_DATABASE_URL, "
                "NEON_DATABASE_URL, DATABASE_URL, or config.neon.database_url."
            )

        try:
            from app.config import config

            neon = getattr(config, "neon", {})
        except Exception:  # pragma: no cover - config is optional at import time
            neon = {}
        new_engine = create_engine(url, future=True, **_pool_options(url, neon))
        # Publish SessionLocal before engine so any reader that sees a non-None
        # engine is guaranteed to also see a non-None SessionLocal.
        SessionLocal = sessionmaker(
            bind=new_engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )
        engine = new_engine
        logger.info(
            "SQLAlchemy engine initialized for ReelForge persistence layer"
        )
        return engine


def get_sessionmaker() -> sessionmaker:
    """Return the configured ``sessionmaker``, initializing the engine first."""
    if SessionLocal is None:
        get_engine()
    assert SessionLocal is not None  # narrowed by get_engine()
    return SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed DB session (commit on success, rollback on error).

    Usage::

        with get_session() as session:
            JobRepository(session).create(...)

    Suitable for FastAPI dependencies and Celery worker tasks. Always closes
    the session, returning the connection to the pool.
    """
    session: Session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
