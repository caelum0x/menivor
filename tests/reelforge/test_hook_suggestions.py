"""Hook suggestions — cold-open rewrites + endpoint integration."""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.models.exception import HttpException
from app.services.loops.hook_suggestions import needs_suggestions, suggest_hooks
from app.utils import utils


def test_passing_hook_gets_no_suggestions():
    assert suggest_hooks("anything", passes_gate=True) == []


def test_weak_hook_returns_rewrites():
    sug = suggest_hooks("so basically my sister read my diary", passes_gate=False)
    shapes = {s.shape for s in sug}
    assert {"shock_first", "curiosity_gap", "question"} <= shapes
    # Filler ('so basically') is stripped from the rewrite payload.
    assert all("basically" not in s.text.lower() for s in sug)


def test_reason_biases_shock_first_to_top():
    sug = suggest_hooks(
        "the setup takes a while", passes_gate=False,
        reasons=("open on the spiciest spoken line first, not setup",),
    )
    assert sug[0].shape == "shock_first"


def test_needs_suggestions_gate():
    assert needs_suggestions(0.5) is True   # below 0.70 gate
    assert needs_suggestions(0.85) is False


# --------------------------------------------------------------------------- #
# Endpoint: hook-score includes suggestions when below the gate
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


def test_hook_score_endpoint_returns_suggestions_when_weak():
    client = _client()
    resp = client.post("/api/v1/captions/hook-score", json={
        "motion": 0.1, "text": 0.0, "audio_onset": 0.1, "early_cut": 0.0,
        "speech": 0.1, "face_or_subject": 0.1, "hook_end_s": 3.0,
        "opening_line": "so basically I tried this thing",
    })
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert not data["passes_gate"]
    assert data["suggestions"] and data["suggestions"][0]["shape"]


def test_hook_score_no_suggestions_when_strong():
    client = _client()
    resp = client.post("/api/v1/captions/hook-score", json={
        "motion": 1, "text": 1, "audio_onset": 1, "early_cut": 1, "speech": 1,
        "face_or_subject": 1, "hook_end_s": 2.0, "opening_line": "shocking line",
    })
    data = resp.json()["data"]
    assert data["passes_gate"] and data["suggestions"] == []
