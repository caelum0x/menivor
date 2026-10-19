"""Caption keyword-SEO — keyword extraction + platform caption/hashtag build."""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.exception import HttpException
from app.services.captions.keyword_seo import build_seo_caption, extract_keywords
from app.utils import utils


def test_extract_ranks_by_frequency_stopword_filtered():
    text = "The parkour parkour minecraft story is the best minecraft story ever told"
    kw = extract_keywords(text, limit=5)
    # 'parkour' (2) and 'minecraft' (2) and 'story' (2) outrank singletons; 'the'/'is' dropped.
    assert kw[:3] == ["parkour", "minecraft", "story"]
    assert "the" not in kw and "is" not in kw


def test_build_caption_caps_hashtags_per_platform():
    text = "glass cutting asmr satisfying kinetic sand soap oddly satisfying loop trigger"
    shorts = build_seo_caption(text, platform="shorts")  # max 5 hashtags
    reels = build_seo_caption(text, platform="reels")     # max 8 hashtags
    assert len(shorts.hashtags) <= 5
    assert len(reels.hashtags) <= 8
    assert all(h.startswith("#") for h in shorts.hashtags)


def test_base_caption_leads_else_keywords_fill():
    text = "movie recap thriller plot twist ending explained"
    with_base = build_seo_caption(text, base_caption="You won't believe this ending")
    assert with_base.caption.startswith("You won't believe")
    without = build_seo_caption(text)
    # No base -> keywords front-load the searchable caption (never empty).
    assert without.caption and "recap" in without.caption or "movie" in without.caption


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
def _client():
    mod = importlib.import_module("app.domains.captions.router")
    app = FastAPI()
    app.include_router(mod.router)
    app.add_exception_handler(
        HttpException,
        lambda r, exc: JSONResponse(status_code=exc.status_code,
                                    content=utils.get_response(exc.status_code, exc.data, exc.message)),
    )
    return TestClient(app)


def test_seo_endpoint():
    client = _client()
    resp = client.post("/api/v1/captions/seo", json={
        "text": "minecraft parkour reddit story satisfying", "platform": "tiktok",
        "base_caption": "This changed everything",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["caption"].startswith("This changed")
    assert len(data["hashtags"]) <= 5 and data["keywords"]


def test_seo_requires_text():
    assert _client().post("/api/v1/captions/seo", json={"text": "  "}).status_code == 422
