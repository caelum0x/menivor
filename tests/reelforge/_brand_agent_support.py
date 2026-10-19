"""Shared fakes for the Brand Agent tests: in-memory DB, fixture analysis, fake ports."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.adclone import preset_store as _preset_store  # noqa: F401  (registers adclone_presets)
from app.domains.brand_agent import models as _agent_models  # noqa: F401  (registers tables)
from app.domains.multipost import models as _multipost_models  # noqa: F401  (registers multipost tables)
from app.domains.brand_agent import site_analysis
from app.domains.brand_agent.deps import AgentDeps
from app.domains.brand_agent.ports.base import PortUnavailable
from app.models.db.base import Base
from app.models.db.models import User

FIXTURES = Path(__file__).parent / "fixtures" / "brand_agent"
SITE_URL = "https://basepoint.example/"
T0 = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)  # a Tuesday


def make_factory():
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


def make_user(factory, email="owner@example.com", api_key=None, credits=100) -> str:
    """A signed-in user; ``credits`` > 0 grants that many on the credit ledger (the agent's meter)."""
    from app.models.db.models import CreditLedger

    key = api_key or email
    with factory() as s:
        user = User(email=email, api_key_hash=hashlib.sha256(key.encode()).hexdigest(), credits=0)
        s.add(user)
        s.flush()
        if credits:
            s.add(CreditLedger(user_id=user.id, delta=credits, reason="signup", balance_after=credits))
        s.commit()
        return user.id


def connect_account(factory, user_id, provider="tiktok") -> None:
    """A connected publishing account (Autopost), so publish actions pass the preflight."""
    from app.domains.multipost.models import MultipostAccount

    with factory() as s:
        s.add(MultipostAccount(user_id=user_id, provider=provider, external_account_id=f"{provider}-1",
                               handle="@brand", access_token_enc="enc"))
        s.commit()


def fixture_analysis(url: str = SITE_URL) -> dict:
    html = (FIXTURES / "site.html").read_text()
    css = (FIXTURES / "app.css").read_text()
    return site_analysis.analyze_html(html, url, stylesheets=[css])


class FakeSearch:
    def __init__(self, results=None):
        self.queries = []
        self.results = results if results is not None else [
            {"title": "Supabase | The Postgres development platform", "url": "https://supabase.com/",
             "snippet": "Build in a weekend. Scale to millions."},
            {"title": "Neon Serverless Postgres", "url": "https://neon.tech/",
             "snippet": "Branching, autoscaling Postgres with scale to zero."},
            {"title": "Basepoint home", "url": "https://basepoint.example/about", "snippet": "our own site"},
        ]

    def search(self, query, limit=6):
        self.queries.append(query)
        return list(self.results)[:limit]


class FakeLLM:
    """Returns queued replies (str) per call; records every (system, prompt)."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def available(self):
        return True

    def complete(self, system, prompt):
        self.calls.append((system, prompt))
        return self.replies.pop(0) if self.replies else ""


class FakeGeneration:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def generate(self, *, session, user_id, kind, prompt, options):
        self.calls.append({"user_id": user_id, "kind": kind, "prompt": prompt, "options": options})
        if self.fail:
            raise self.fail
        return {"kind": kind, "ref": f"media-{len(self.calls)}", "url": f"https://cdn.test/{len(self.calls)}",
                "status": "submitted"}


class FakeIntegrations:
    def __init__(self, creatives=None, error=None):
        self.creatives = creatives
        self.error = error
        self.calls = []

    def list_connected_accounts(self, user_id):
        return [{"platform": "meta", "account_id": "act_1", "name": "Basepoint Ads"}] if self.creatives else []

    def top_performing_creatives(self, user_id, *, platform, limit):
        self.calls.append((user_id, platform, limit))
        if self.error:
            raise self.error
        if self.creatives is None:
            raise PortUnavailable("Meta Ads is not connected yet. Connect your ad account in Connectors.")
        return list(self.creatives)[:limit]

    def ask_campaign_question(self, user_id, question):
        return {"answer": "fake"}

    def pull_report(self, user_id, **kw):
        return {}

    def propose_optimization(self, user_id, **kw):
        return {}


class FakeAdClone:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def clone_from_link(self, user_id, url, *, brand, space_id):
        self.calls.append((user_id, url, space_id))
        if self.error:
            raise self.error
        return {"status": "queued", "job_id": "clone-1", "url": url}


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, *, session, user_id, payload):
        self.calls.append((user_id, payload))
        return {"status": "scheduled", "ref": "post-1"}


def make_deps(**overrides) -> AgentDeps:
    values = {
        "analyzer": lambda url: fixture_analysis(url),
        "search": FakeSearch(),
        "llm": None,
        "integrations": FakeIntegrations(),
        "ad_clone": FakeAdClone(),
        "generation": FakeGeneration(),
        "publisher": FakePublisher(),
        "now": lambda: T0,
    }
    values.update(overrides)
    return AgentDeps(**values)
