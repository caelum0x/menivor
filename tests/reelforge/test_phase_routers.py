"""HTTP surface for the P7/P9/P10 cores — captions, trends, film routers.

Import-safe, DB-free facades: mounted on a bare FastAPI app and exercised with
TestClient (mirrors test_presets.py), asserting the cores are reachable + shaped.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.exception import HttpException
from app.utils import utils


def _client(module_path: str) -> TestClient:
    mod = importlib.import_module(module_path)
    app = FastAPI()
    app.include_router(mod.router)

    def _http_handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _http_handler)
    return TestClient(app)


# --------------------------------------------------------------------------- #
# Captions facade
# --------------------------------------------------------------------------- #
def test_hook_score_endpoint():
    client = _client("app.domains.captions.router")
    resp = client.post("/api/v1/captions/hook-score", json={
        "motion": 1, "text": 1, "audio_onset": 1, "early_cut": 1, "speech": 1,
        "face_or_subject": 1, "hook_end_s": 2.0,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["passes_gate"] and data["grade"] == "viral"


def test_hormozi_endpoint_groups_words():
    client = _client("app.domains.captions.router")
    words = [{"text": w, "start": i * 0.3, "end": i * 0.3 + 0.3}
             for i, w in enumerate(["this", "changed", "my", "life"])]
    resp = client.post("/api/v1/captions/hormozi", json={"words": words, "max_per_group": 2})
    assert resp.status_code == 200
    groups = resp.json()["data"]["groups"]
    assert [g["text"] for g in groups] == ["this changed", "my life"]


def test_hormozi_requires_words():
    client = _client("app.domains.captions.router")
    assert client.post("/api/v1/captions/hormozi", json={"words": []}).status_code == 422


def test_safezones_endpoint():
    client = _client("app.domains.captions.router")
    resp = client.get("/api/v1/captions/safezones?play_h=1920")
    assert resp.status_code == 200
    zones = resp.json()["data"]["safezones"]
    assert "tiktok" in zones and zones["shorts"]["fontsize"] < zones["tiktok"]["fontsize"]


def test_loop_check_endpoint():
    client = _client("app.domains.captions.router")
    disc = [0.5] * 181
    disc[150] = 0.01  # a near-perfect seam at frame 150 (~5s @ 30fps)
    resp = client.post("/api/v1/captions/loop-check", json={
        "discontinuities": disc, "fps": 30.0, "target_s": 5.0, "max_s": 6.0,
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["end_frame"] == 150 and data["accepted"] is True


def test_loop_check_requires_input():
    client = _client("app.domains.captions.router")
    assert client.post("/api/v1/captions/loop-check", json={"discontinuities": []}).status_code == 422


def test_beat_fit_endpoint():
    client = _client("app.domains.captions.router")
    resp = client.post("/api/v1/captions/beat-fit", json={
        "cuts": [1.02, 2.01], "beats": [0.0, 1.0, 2.0], "fps": 30.0,
    })
    assert resp.status_code == 200
    fits = resp.json()["data"]["fits"]
    assert set(fits) == {"2", "3", "4"} and all(v >= 0 for v in fits.values())


# --------------------------------------------------------------------------- #
# Trends facade
# --------------------------------------------------------------------------- #
def test_trends_rank_endpoint():
    client = _client("app.domains.trends.router")
    resp = client.post("/api/v1/trends/rank", json={"trends": [
        {"trend_id": "hot", "counts": [100, 400, 1200, 3000]},
        {"trend_id": "cold", "counts": [99000, 99100, 99050, 99000]},
    ]})
    assert resp.status_code == 200
    ranked = resp.json()["data"]["trends"]
    assert ranked[0]["trend_id"] == "hot" and ranked[0]["recommend"]


def test_trends_requires_input():
    client = _client("app.domains.trends.router")
    assert client.post("/api/v1/trends/rank", json={"trends": []}).status_code == 422


# --------------------------------------------------------------------------- #
# Film facade
# --------------------------------------------------------------------------- #
def test_film_plan_endpoint():
    client = _client("app.domains.film.router")
    resp = client.post("/api/v1/film/plan", json={
        "beats": [
            {"scene_id": "sc1", "summary": "hero enters", "weight": 2.0},
            {"scene_id": "sc2", "summary": "the twist", "weight": 1.0},
        ],
        "character": {"character_id": "c1", "name": "Nova", "descriptors": ["red jacket"], "style": "3D"},
        "total_shots": 8, "target_runtime_s": 24.0,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert len(data["shots"]) == 8
    assert all("Nova" in s["prompt"] for s in data["shots"])
    assert data["node_order"][-1] == "finish"
    assert abs(data["total_runtime_s"] - 24.0) < 0.2


def test_film_plan_requires_beats():
    client = _client("app.domains.film.router")
    resp = client.post("/api/v1/film/plan", json={
        "beats": [], "character": {"character_id": "c", "name": "N"},
    })
    assert resp.status_code == 422
