"""Shared helpers for the Wave P P3 OTT tests (PM3.1-PM3.5): an in-memory DB, channels, clients, auth tokens."""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

import jwt
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.domains.compliance.takedown  # noqa: F401  (registers takedown_reports)
import app.domains.ott.models  # noqa: F401
import app.domains.ott_viewers.models  # noqa: F401
import app.domains.ott_commerce.models  # noqa: F401
import app.integrations.railyard.meters  # noqa: F401  (registers railyard_meter_outbox)
import app.models.db.creator_subscription  # noqa: F401
import app.models.db.dodo_usage_event  # noqa: F401
import app.services.ott_transcode.models  # noqa: F401
from app.domains.ott.models import OttChannel, OttTitle
from app.models.db.base import Base
from app.models.db.models import User
from app.models.exception import HttpException
from app.utils import utils

AUTH_SECRET = "scribase-viewers-project-jwt-secret-0123456789"
VIEWER_SECRET = "v" * 40
OWNER_KEY = "owner-key"


def make_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def session_cm(factory):
    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return _session


def patch_sessions(monkeypatch, factory, modules: Iterable[Any]) -> None:
    import app.controllers.v1.jobs as jobs_mod
    import app.models.db.base as db_base

    cm = session_cm(factory)
    for module in (db_base, jobs_mod, *modules):
        monkeypatch.setattr(module, "get_session", cm)


def enable(monkeypatch, *surfaces: str) -> None:
    from app.domains.ott import flags

    monkeypatch.setenv(flags.MASTER, "1")
    for surface in surfaces:
        monkeypatch.setenv(flags.SURFACES[surface], "1")


def owner(factory, email: str = "owner@example.com", key: str = OWNER_KEY) -> str:
    with factory() as s:
        user = User(email=email, api_key_hash=hashlib.sha256(key.encode()).hexdigest())
        s.add(user)
        s.commit()
        return user.id


def channel(factory, user_id: str, handle: str, *, titles: int = 2, access_tier: str = "free",
            duration_s: float = 600.0) -> tuple[str, list[str]]:
    with factory() as s:
        row = OttChannel(user_id=user_id, handle=handle, title=handle.title(), status="published", brand_colors=[])
        s.add(row)
        s.flush()
        ids = []
        for n in range(titles):
            title = OttTitle(channel_id=row.id, title=f"{handle} title {n}", kind="episode", genres=[],
                             geo_countries=[], status="published", package_status="ready", duration_s=duration_s,
                             position=n, source_key=f"ott:src/{handle}/{n}.mp4", access_tier=access_tier,
                             manifest_key=f"ott/{row.id}/t{n}/j/master.m3u8",
                             published_at=datetime.now(timezone.utc))
            s.add(title)
            s.flush()
            ids.append(title.id)
        s.commit()
        return row.id, ids


def app_client(*routers) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def auth_token(subject: str, email: str, *, secret: str = AUTH_SECRET, aud: str = "authenticated",
               ttl: int = 3600, **extra) -> str:
    now = int(time.time())
    claims = {"sub": subject, "email": email, "aud": aud, "exp": now + ttl, "iat": now, "role": "authenticated",
              **extra}
    return jwt.encode(claims, secret, algorithm="HS256")
