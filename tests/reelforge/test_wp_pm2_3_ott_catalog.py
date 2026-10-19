"""Wave P PM2.3 (MV1): OTT catalog, CMS and one-click publish.

A creator with 5 reels presses one button and gets a channel with 5 published
titles in under 60 s (measured, shown); unpublish or takedown hides a title at
once; the compliance gate blocks a flagged title; no field asks for a key; the
routes 404 until OTT_ENABLED and OTT_CMS_LIVE are on; the migration applies on
Postgres (scratch database via MENIVOR_PG_TEST_URL).
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

import app.models.db.base as db_base
from app.domains.compliance import takedown
from app.domains.ott import models, publish, router as ott_router, schemas, service
from app.models.db.base import Base
from app.models.db.models import Job, User
from app.models.exception import HttpException
from app.utils import utils

KEY = "ott-key"
H = {"x-api-key": KEY}
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

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

    import app.controllers.v1.jobs as jobs_mod

    monkeypatch.setattr(db_base, "get_session", _session)
    monkeypatch.setattr(jobs_mod, "get_session", _session)
    monkeypatch.setattr(ott_router, "get_session", _session)
    monkeypatch.setattr(service, "_url", lambda key: f"https://signed/{key}" if key else "")
    monkeypatch.setenv("OTT_ENABLED", "1")
    monkeypatch.setenv("OTT_CMS_LIVE", "1")
    with factory() as s:
        s.add(User(email="maya.films@example.com", api_key_hash=hashlib.sha256(KEY.encode()).hexdigest()))
        s.commit()
    return factory


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ott_router.router)
    app.add_exception_handler(HttpException, lambda _r, exc: JSONResponse(
        status_code=exc.status_code, content=utils.get_response(exc.status_code, exc.data, exc.message)))
    return TestClient(app)


def _uid(maker):
    with maker() as s:
        return s.query(User).one().id


def _reels(maker, n=5, **params) -> list[str]:
    uid = _uid(maker)
    ids = []
    with maker() as s:
        for i in range(n):
            job = Job(user_id=uid, kind="avatar_reel", state=1, result_key=f"jobs/r{i}/final.mp4",
                      poster_key=f"jobs/r{i}/poster.jpg",
                      params={"video_subject": f"Reel {i}", "target_duration_s": 30, **params})
            s.add(job)
            s.flush()
            ids.append(job.id)
        s.commit()
    return ids


def test_one_click_turns_five_reels_into_a_live_channel_in_under_a_minute(maker):
    _reels(maker, 5)
    res = _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert len(data["published"]) == 5 and data["held"] == []
    assert data["within_target"] is True and data["seconds"] < 60
    channel = data["channel"]
    assert channel["handle"] == "maya-films" and channel["status"] == "published"
    assert channel["storefront_path"] == "/c/maya-films"
    assert all(t["status"] == "published" for t in channel["titles"])
    again = _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]
    assert len(again["channel"]["titles"]) == 5  # no duplicates


def test_unfinished_or_unkept_reels_are_not_published(maker):
    _reels(maker, 1)
    uid = _uid(maker)
    with maker() as s:
        s.add(Job(user_id=uid, kind="avatar_reel", state=4, result_key="", params={}))
        s.add(Job(user_id=uid, kind="avatar_reel", state=1, result_key="jobs/k/final.mp4",
                  params={"_keep": {"credits": 1, "workspace_id": None, "kept": False}}))
        s.commit()
    data = _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]
    assert len(data["published"]) == 1


def test_compliance_gate_blocks_a_flagged_title(maker):
    flagged, blocked = _reels(maker, 2)
    uid = _uid(maker)
    with maker() as s:
        s.get(Job, flagged).stages = {"_content_gate": {"decision": "block"}}
        report = takedown.TakedownReport(job_id=blocked, content_ref=blocked, reason="copyright",
                                         reporter_email="r@example.com", status=takedown.STATUS_BLOCKED)
        s.add(report)
        s.commit()
    data = _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]
    assert data["published"] == [] and len(data["held"]) == 2
    title_id = data["held"][0]["title_id"]
    res = _client().post(f"/api/v1/ott/studio/titles/{title_id}/publish", headers=H)
    assert res.status_code == 409 and res.json()["data"]["code"] == "compliance_gate"
    assert uid


def test_unpublish_and_takedown_hide_a_title_at_once(maker):
    first, second = _reels(maker, 2)
    client = _client()
    titles = client.post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]["channel"]["titles"]
    by_job = {t["source_job_id"]: t["id"] for t in titles}
    hidden = client.post(f"/api/v1/ott/studio/titles/{by_job[first]}/unpublish", headers=H).json()["data"]
    assert hidden["status"] == "hidden" and hidden["hidden_reason"] == "owner"
    with maker() as s:
        report = takedown.TakedownReport(job_id=second, content_ref=second, reason="privacy",
                                         reporter_email="r@example.com", status=takedown.STATUS_OPEN)
        s.add(report)
        s.flush()
        takedown.block(s, report.id, "staff:1")
        s.commit()
    with maker() as s:
        row = s.get(models.OttTitle, by_job[second])
        assert row.status == "hidden" and row.hidden_reason == "takedown"


def test_sweep_hides_titles_that_fail_the_gate_later(maker):
    (job_id,) = _reels(maker, 1)
    _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H)
    with maker() as s:
        s.get(Job, job_id).stages = {"_content_gate": {"decision": "block"}}
        s.commit()
    with maker() as s:
        assert service.sweep_gate(s) == 1
        s.commit()


def test_metadata_edits_are_validated_and_name_no_tools(maker):
    _reels(maker, 1)
    client = _client()
    title = client.post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]["channel"]["titles"][0]
    ok = client.patch(f"/api/v1/ott/studio/titles/{title['id']}", headers=H, json={
        "title": "Morning routine", "genres": ["Lifestyle"], "rating": "PG", "access_tier": "paid",
        "geo_mode": "deny", "geo_countries": ["de", "FR"], "available_from": "2026-10-01T00:00:00Z",
        "available_until": "2026-12-01T00:00:00Z"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["geo_countries"] == ["DE", "FR"]
    assert client.patch(f"/api/v1/ott/studio/titles/{title['id']}", headers=H,
                        json={"title": "Made with Sora"}).status_code == 400
    assert client.patch(f"/api/v1/ott/studio/titles/{title['id']}", headers=H,
                        json={"geo_countries": ["Germany"]}).status_code == 400
    assert client.patch(f"/api/v1/ott/studio/titles/{title['id']}", headers=H,
                        json={"available_from": "2026-12-01T00:00:00Z",
                              "available_until": "2026-10-01T00:00:00Z"}).status_code == 400


def test_channel_series_and_rails(maker):
    _reels(maker, 2)
    client = _client()
    titles = client.post("/api/v1/ott/studio/publish-all", json={}, headers=H).json()["data"]["channel"]["titles"]
    assert client.patch("/api/v1/ott/studio/channel", headers=H,
                        json={"handle": "Maya Studio!", "layout": "rails", "brand_colors": ["#112233"]}).json()[
        "data"]["handle"] == "maya-studio"
    series = client.post("/api/v1/ott/studio/series", headers=H, json={"title": "Season one"}).json()["data"]
    assert client.patch(f"/api/v1/ott/studio/titles/{titles[0]['id']}", headers=H,
                        json={"series_id": series["id"], "season": 1, "episode": 1}).status_code == 200
    rail = client.post("/api/v1/ott/studio/collections", headers=H,
                       json={"title": "Start here", "title_ids": [t["id"] for t in titles]})
    assert rail.status_code == 200
    assert client.post("/api/v1/ott/studio/collections", headers=H,
                       json={"title": "Bad", "title_ids": ["nope"]}).status_code == 404
    studio = client.get("/api/v1/ott/studio", headers=H).json()["data"]
    assert studio["layout"] == "rails" and studio["collections"][0]["title"] == "Start here"


def test_routes_are_404_until_the_cms_flag_is_on(maker, monkeypatch):
    monkeypatch.setenv("OTT_CMS_LIVE", "0")
    assert _client().get("/api/v1/ott/studio", headers=H).status_code == 404
    monkeypatch.delenv("OTT_ENABLED")
    monkeypatch.setenv("OTT_CMS_LIVE", "1")
    assert _client().post("/api/v1/ott/studio/publish-all", json={}, headers=H).status_code == 404


def test_no_request_field_asks_for_a_key():
    for model in (schemas.ChannelUpdate, schemas.TitleUpdate, schemas.AddTitles, schemas.SeriesCreate,
                  schemas.CollectionCreate, schemas.PublishAll):
        for name in model.model_fields:
            assert not any(word in name for word in ("key", "token", "secret", "password")), (model, name)


def test_migration_matches_the_models():
    text = (REPO / "migrations" / "versions" / "20261001_0900_b1d3f5a7c9e2_ott_catalog.py").read_text()
    for table in ("ott_channels", "ott_series", "ott_titles", "ott_collections"):
        assert f'"{table}" not in tables' in text
        assert table in Base.metadata.tables


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("MENIVOR_PG_TEST_URL"), reason="set MENIVOR_PG_TEST_URL to a scratch Postgres")
def test_catalog_tables_exist_on_postgres_after_upgrade():
    engine = create_engine(os.environ["MENIVOR_PG_TEST_URL"], future=True)
    names = set(inspect(engine).get_table_names())
    assert {"ott_channels", "ott_series", "ott_titles", "ott_collections"} <= names
    columns = {c["name"] for c in inspect(engine).get_columns("ott_titles")}
    assert {"geo_mode", "geo_countries", "access_tier", "package_status", "manifest_key"} <= columns
    assert publish.TARGET_SECONDS == 60.0
