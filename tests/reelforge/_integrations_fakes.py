"""Shared fakes for the Integrations tests: a recording HTTP transport and an in-memory DB."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


class Resp:
    def __init__(self, status_code=200, body=None, headers=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body

    @property
    def text(self):
        return self._text if self._text is not None else json.dumps(self._body)

    @property
    def content(self):
        return self.text.encode("utf-8")


class FakeTransport:
    """Routes by (method, url prefix); the longest matching prefix wins; responses are used in order."""

    def __init__(self):
        self.routes: dict[tuple[str, str], list[Resp]] = {}
        self.calls: list[dict] = []

    def add(self, method, prefix, *responses):
        self.routes.setdefault((method, prefix), []).extend(responses)
        return self

    def request(self, method, url, *, headers=None, params=None, json=None, data=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "params": params or {},
                           "json": json, "data": data})
        matches = [k for k in self.routes if k[0] == method and url.startswith(k[1])]
        if not matches:
            raise AssertionError(f"unexpected request {method} {url}")
        queue = self.routes[max(matches, key=lambda k: len(k[1]))]
        if not queue:
            raise AssertionError(f"no response left for {method} {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def find(self, method, prefix):
        return [c for c in self.calls if c["method"] == method and c["url"].startswith(prefix)]


def make_db():
    from app.models.db.base import Base
    import app.domains.integrations.models  # noqa: F401 - register tables
    import app.domains.approvals.models  # noqa: F401
    import app.domains.adstudio.catalog_models  # noqa: F401
    import app.domains.multipost.models  # noqa: F401

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    factory.scope = scope
    return factory


def add_user(factory, email="owner@example.com") -> str:
    from app.models.db.models import User

    with factory.scope() as s:
        user = User(email=email, api_key_hash=hashlib.sha256(email.encode()).hexdigest(), credits=0)
        s.add(user)
        s.flush()
        return user.id


def add_workspace(factory, owner_id, members=()) -> str:
    from app.models.db.models import Workspace, WorkspaceMember

    with factory.scope() as s:
        ws = Workspace(name="Team", owner_id=owner_id)
        s.add(ws)
        s.flush()
        s.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_id, role="owner"))
        for user_id, role in members:
            s.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role=role))
        return ws.id


def add_brand_kit(factory, user_id, name="Brand", workspace_id=None) -> str:
    from app.models.db.models import UserPreset

    with factory.scope() as s:
        kit = UserPreset(user_id=user_id, workspace_id=workspace_id, name=name, config={})
        s.add(kit)
        s.flush()
        return kit.id
