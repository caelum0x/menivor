"""Public job payloads expose the source link and stored hashtags for Share to X."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

# `app.domains.reels` binds the name `router` to the APIRouter, which shadows
# the submodule. The functions live on the module object.
importlib.import_module("app.domains.reels.router")
jobs = sys.modules["app.domains.reels.router"]


def _job(**overrides):
    base = {
        "id": "job1",
        "kind": "avatar_reel",
        "state": 1,
        "progress": 100,
        "stages": {},
        "params": {},
        "failed_stage": "",
        "error": "",
        "script": "",
        "title": "",
        "archived_at": None,
        "created_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_public_job_includes_hook_source_url_and_hashtags(monkeypatch):
    monkeypatch.setattr(jobs, "_presign_job_artifacts", lambda *args, **kwargs: None)
    job = _job(
        script="Şimdi dene\nbody",
        params={
            "source_url": "https://shop.example/ürün",
            "video_subject": "subject",
            "social_metadata": {"hashtags": ["#Menivor", "reels", "#Menivor", "bad tag"]},
            "hashtags": ["extra"],
        },
    )
    data = jobs._job_public_data(job, "rid")
    assert data["hook"] == "Şimdi dene"
    assert data["source_url"] == "https://shop.example/ürün"
    assert data["hashtags"] == ["#Menivor", "#reels", "#extra"]


def test_public_job_drops_unsafe_source_urls(monkeypatch):
    monkeypatch.setattr(jobs, "_presign_job_artifacts", lambda *args, **kwargs: None)
    for raw in ("javascript:alert(1)", "file:///etc/passwd", "not a url", "https://bad.example/a b"):
        data = jobs._job_public_data(_job(params={"source_url": raw}), "rid")
        assert "source_url" not in data


def test_batch_job_includes_the_same_share_fields(monkeypatch):
    monkeypatch.setattr(jobs, "_presign_job_artifacts", lambda *args, **kwargs: None)
    job = _job(
        script="First hook\nrest",
        params={"source_url": "https://shop.example/p", "hashtags": ["shop"]},
    )
    data = jobs._batch_job_data(job, "rid")
    assert data["hook"] == "First hook"
    assert data["source_url"] == "https://shop.example/p"
    assert data["hashtags"] == ["#shop"]
