"""M0.7 (trademark alias only): no brand names in template/background/style
output, legacy ids keep resolving, and no source is disabled.
"""

from __future__ import annotations

import importlib
import json
import re

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.domains.content import background_library as library
from app.domains.templates.presets import get_template
from app.domains.templates.presets.aliases import PUBLIC_TEMPLATE_SLUGS, internal_slug, public_slug

BRANDS = re.compile(r"minecraft|subway|reddit|movie recap|\bgta\b|fake ai podcast", re.IGNORECASE)


def _client() -> TestClient:
    app = FastAPI()
    templates_router = importlib.import_module("app.domains.templates.router")
    app.include_router(templates_router.router)
    app.include_router(importlib.import_module("app.domains.styles.router").router)
    return TestClient(app)


def test_template_list_and_backgrounds_carry_no_brand_names():
    client = _client()
    listing = client.get("/api/v1/templates")
    assert listing.status_code == 200
    assert not BRANDS.search(json.dumps(listing.json()))
    backgrounds = client.get("/api/v1/templates/backgrounds")
    assert backgrounds.status_code == 200
    assert not BRANDS.search(json.dumps(backgrounds.json()))


def test_every_template_detail_carries_no_brand_names():
    client = _client()
    slugs = [t["slug"] for t in client.get("/api/v1/templates").json()["data"]["templates"]]
    for slug in slugs:
        detail = client.get(f"/api/v1/templates/{slug}")
        assert detail.status_code == 200, slug
        assert not BRANDS.search(json.dumps(detail.json())), slug


def test_styles_carry_no_brand_names():
    client = _client()
    response = client.get("/api/v1/styles")
    assert response.status_code == 200
    assert not BRANDS.search(json.dumps(response.json()))


def test_legacy_template_slugs_still_resolve_and_instantiate():
    for internal, public in PUBLIC_TEMPLATE_SLUGS.items():
        assert get_template(internal) is get_template(public) is not None
        assert public_slug(internal) == public and internal_slug(public) == internal
    client = _client()
    for slug in ("minecraft-reddit-split", "story-gameplay-split"):
        response = client.post(
            f"/api/v1/templates/{slug}/instantiate", json={"inputs": {"story": "It started on a Tuesday."}}
        )
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["template"] == "story-gameplay-split"
        assert body["render_spec"]["template_slug"] == "story-gameplay-split"
        assert not BRANDS.search(json.dumps(body))


def test_legacy_background_ids_resolve_to_the_same_loops():
    for legacy, current in library.LEGACY_BACKGROUND_ALIASES.items():
        assert library.get(legacy) is library.get(current) is not None
        assert library.canonical_id(legacy) == current
    ids = {clip.id for clip in library.list_backgrounds()}
    assert not ids & set(library.LEGACY_BACKGROUND_ALIASES)


def test_story_draft_uses_the_neutral_background():
    from app.domains.stories.contract import build_story_reel_draft

    draft = build_story_reel_draft("It started on a Tuesday.", subject="Tuesday")
    assert draft["background_id"] == "voxel-parkour"


def test_no_source_is_disabled():
    # Owner rule: the TikTok trend puller, the Reddit story fetch, the trends
    # beat task and yt-dlp ingestion all stay registered and importable.
    from app.domains.stories import fetch as story_fetch
    from app.workers.celery_app import celery_app

    assert callable(story_fetch.default_fetch)
    tasks = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    assert "app.workers.tasks.autopull_trends_task" in tasks
    assert importlib.import_module("app.domains.trends.providers.tiktok_pull")
    assert importlib.import_module("app.domains.clipping.platform_source")
