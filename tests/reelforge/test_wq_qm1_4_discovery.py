"""Wave Q QM1.4: related titles, the fastembed switch, and the cast receiver's backend side (U25, U45, P-M16).

1. ``GET /ott/titles/{id}/related`` ranks the same channel's titles by the
   stored vector (no model call when the title is indexed), skips the title
   itself and anything a viewer cannot play, and fills with the newest titles.
2. p95 under 300 ms on 5,000 titles (target, measured here).
3. fastembed runs when installed (the worker and API images pin it in
   requirements.txt); the hashing embedder stays the fallback, and a search
   uses whichever model wrote the index.
"""

from __future__ import annotations

import importlib.util
import random
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.domains.ott_ai.models  # noqa: F401  (index text reads transcripts)
import app.domains.ott_discovery.models  # noqa: F401
from app.domains.ott.models import OttTitle
from app.domains.ott_discovery import embeddings, router as discovery_router, search
from app.domains.ott_discovery.embeddings import HashingEmbedder
from app.domains.ott_discovery.models import OttTitleEmbedding

from tests.reelforge import _wp_p3_ott as h

REPO = Path(__file__).resolve().parents[2]
HAS_FASTEMBED = importlib.util.find_spec("fastembed") is not None


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (discovery_router,))
    h.enable(monkeypatch, "discovery")
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "hashing")
    monkeypatch.setattr("app.domains.ott.catalog_public._art", lambda key: "")
    embeddings.default_embedder.cache_clear()
    search.reset_cache()
    owner = h.owner(factory)
    cid, _ = h.channel(factory, owner, "maya", titles=0)
    other_owner = h.owner(factory, email="o2@example.com", key="k2")
    other_cid, _ = h.channel(factory, other_owner, "noor", titles=0)
    client = h.app_client(discovery_router.router)
    yield {"factory": factory, "client": client, "cid": cid, "other": other_cid}
    getattr(embeddings.default_embedder, "cache_clear", lambda: None)()
    search.reset_cache()


def _titles(env, channel_id, rows, *, published_days_ago=None):
    ids = []
    with env["factory"]() as s:
        for n, (name, synopsis) in enumerate(rows):
            ago = (published_days_ago or [0] * len(rows))[n]
            t = OttTitle(channel_id=channel_id, title=name, synopsis=synopsis, kind="episode", genres=[],
                         geo_countries=[], status="published", package_status="ready", duration_s=600, position=n,
                         access_tier="free", published_at=datetime.now(timezone.utc) - timedelta(days=ago))
            s.add(t)
            s.flush()
            ids.append(t.id)
        s.commit()
    return ids


FOOD = [("Sourdough basics", "bread starter flour water bake"),
        ("Rye bread at home", "bread rye flour bake loaf"),
        ("Bread scoring", "bread loaf scoring bake oven"),
        ("Mountain bike repair", "bike chain brake tyre repair"),
        ("Road bike fitting", "bike saddle fitting road")]


def test_related_ranks_the_same_channel_by_stored_vector(env):
    ids = _titles(env, env["cid"], FOOD)
    elsewhere = _titles(env, env["other"], [("Bread for beginners", "bread flour bake loaf starter")])
    with env["factory"]() as s:
        assert search.reindex(s, embedder=HashingEmbedder()) == 6
        s.commit()
    res = env["client"].get(f"/api/v1/ott/titles/{ids[0]}/related?limit=2")
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    names = [r["title"] for r in data["results"]]
    assert names == ["Rye bread at home", "Bread scoring"] or set(names) == {"Rye bread at home", "Bread scoring"}
    assert data["source"] == "similar"
    assert all(r["id"] != ids[0] and r["id"] != elsewhere[0] for r in data["results"])
    assert res.headers["cache-control"].startswith("public")
    assert env["client"].get("/api/v1/ott/titles/nope/related").status_code == 404


def test_related_skips_unplayable_and_fills_with_newest(env):
    ids = _titles(env, env["cid"], FOOD, published_days_ago=[5, 4, 3, 2, 1])
    with env["factory"]() as s:
        search.reindex(s, embedder=HashingEmbedder())
        s.get(OttTitle, ids[1]).status = "hidden"
        s.commit()
    search.reset_cache()
    with env["factory"]() as s:
        out = search.related(s, ids[0], limit=4)
    got = [r["id"] for r in out["results"]]
    assert ids[1] not in got and ids[0] not in got
    assert len(got) == 3 and set(got) == {ids[2], ids[3], ids[4]}
    # A title not indexed yet is embedded on the fly with the running model.
    new = _titles(env, env["cid"], [("Bread crust", "bread crust bake oven loaf")])[0]
    with env["factory"]() as s:
        out = search.related(s, new, limit=2)
    assert out["results"] and out["results"][0]["title"] in {"Bread scoring", "Sourdough basics"}
    # With nothing indexed at all, the newest titles still fill the row.
    with env["factory"]() as s:
        s.query(OttTitleEmbedding).delete()
        s.commit()
    search.reset_cache()
    with env["factory"]() as s:
        out = search.related(s, ids[0], limit=2, embedder=_Silent())
    assert out["source"] == "newest" and [r["id"] for r in out["results"]] == [new, ids[4]]


class _Silent(HashingEmbedder):
    """An embedder whose vectors match nothing (all zeros), so only the newest titles can fill the row."""

    def embed(self, texts):
        return super().embed(texts) * 0


def test_related_p95_is_under_300_ms_on_5000_titles(env):
    rng = random.Random(11)
    vocab = ["bread", "bike", "garden", "coffee", "travel", "yoga", "guitar", "camera", "code", "paint", "soccer",
             "chess", "piano", "cooking", "hiking", "startup", "design", "science", "history", "music"]
    embedder = HashingEmbedder()
    with env["factory"]() as s:
        titles, texts = [], []
        for n in range(5000):
            words = rng.sample(vocab, 4)
            titles.append(OttTitle(channel_id=env["cid"], title=" ".join(words[:2]).title(), synopsis=" ".join(words),
                                   kind="episode", genres=[], geo_countries=[], status="published",
                                   package_status="ready", duration_s=60, access_tier="free", position=n,
                                   published_at=datetime.now(timezone.utc)))
            texts.append(" ".join(words))
        s.add_all(titles)
        s.flush()
        vectors = embedder.embed(texts)
        s.add_all([OttTitleEmbedding(title_id=t.id, channel_id=env["cid"], model=embedder.name, dim=embedder.dim,
                                     vector=[round(float(x), 6) for x in v], text_hash="x")
                   for t, v in zip(titles, vectors)])
        s.commit()
        picks = [t.id for t in rng.sample(titles, 40)]
    timings = []
    with env["factory"]() as s:
        search.related(s, picks[0])
        for title_id in picks:
            started = time.perf_counter()
            out = search.related(s, title_id)
            timings.append((time.perf_counter() - started) * 1000)
            assert len(out["results"]) == search.RELATED_LIMIT and out["source"] == "similar"
    p95 = statistics.quantiles(timings, n=20)[18]
    assert p95 < 300, f"related p95 {p95:.1f} ms"


def test_embedder_switch_and_fallback(monkeypatch):
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "hashing")
    embeddings.default_embedder.cache_clear()
    assert isinstance(embeddings.default_embedder(), HashingEmbedder)

    class Broken:
        def __init__(self):
            raise RuntimeError("model download refused")

    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "fastembed")
    monkeypatch.setattr(embeddings, "FastEmbedder", Broken)
    embeddings.default_embedder.cache_clear()
    assert isinstance(embeddings.default_embedder(), HashingEmbedder)
    assert embeddings.by_name(HashingEmbedder.name).name == HashingEmbedder.name
    assert embeddings.by_name("bge-small-en-v1.5") is None
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "nonsense")
    assert embeddings.choice() == ""
    embeddings.default_embedder.cache_clear()


def test_search_uses_the_model_that_wrote_the_index(env, monkeypatch):
    _titles(env, env["cid"], FOOD)
    with env["factory"]() as s:
        search.reindex(s, embedder=HashingEmbedder())
        s.commit()
    search.reset_cache()

    class Other(HashingEmbedder):
        name = "bge-small-en-v1.5"

    monkeypatch.setattr(embeddings, "default_embedder", lambda: Other())
    monkeypatch.setattr(search, "default_embedder", lambda: Other())
    with env["factory"]() as s:
        found = search.search(s, "bread loaf")
    assert found["results"] and found["results"][0]["title"] in {n for n, _ in FOOD[:3]}


@pytest.mark.skipif(not HAS_FASTEMBED, reason="fastembed is installed on the API and worker images, not here")
def test_fastembed_runs_and_related_uses_its_vectors(env, monkeypatch):
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "fastembed")
    embeddings.default_embedder.cache_clear()
    model = embeddings.default_embedder()
    assert model.name == "bge-small-en-v1.5"
    vectors = model.embed(["bread starter flour", "mountain bike chain"])
    assert vectors.shape == (2, 384) and abs(float((vectors[0] ** 2).sum()) - 1.0) < 1e-3
    ids = _titles(env, env["cid"], FOOD)
    with env["factory"]() as s:
        assert search.reindex(s) == 5
        s.commit()
        rows = s.query(OttTitleEmbedding).all()
    assert {r.model for r in rows} == {"bge-small-en-v1.5"}
    with env["factory"]() as s:
        out = search.related(s, ids[3], limit=1)
    assert out["results"][0]["title"] == "Road bike fitting"


def test_worker_and_api_images_pin_fastembed():
    lines = (REPO / "requirements.txt").read_text().splitlines()
    pins = [line for line in lines if re.match(r"^fastembed==\d", line)]
    assert pins == ["fastembed==0.8.1"]
    assert "fastembed" in (REPO / "THIRD_PARTY_NOTICES.md").read_text()
    assert "FASTEMBED_CACHE_PATH" in (REPO / "apps/api/Dockerfile").read_text()
