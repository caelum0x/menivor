"""Unit tests for the AI B-roll cutaways service (``app.services.broll``).

All network / material / R2 interactions are monkeypatched — these tests never
touch Pexels/Pixabay, the LLM, or Cloudflare R2. They pin the three behaviours
the build plan calls out:

* ``suggest_broll`` returns one record per fetched clip, each carrying a
  server-generated ``broll_key`` under ``jobs/<job_id>/broll/``.
* A download (material) failure yields ``[]`` and never raises — a B-roll
  failure must never fail the job.
* ``amount`` is clamped to ``[1, MAX_BROLL_AMOUNT]``.
"""

from __future__ import annotations

import pytest

from app.models.schema import VideoAspect
from app.services import broll


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _patch_terms(monkeypatch, terms):
    """Force ``llm.generate_terms`` (imported lazily inside broll) to return ``terms``."""
    import app.services.llm as llm

    monkeypatch.setattr(
        llm,
        "generate_terms",
        lambda video_subject, video_script, amount: list(terms),
    )


def _patch_download(monkeypatch, paths, recorder=None):
    """Force ``material.download_videos`` to return ``paths`` (recording its kwargs)."""
    import app.services.material as material

    def fake_download(**kwargs):
        if recorder is not None:
            recorder.update(kwargs)
        return list(paths)

    monkeypatch.setattr(material, "download_videos", fake_download)


def _patch_upload(monkeypatch, keys=None):
    """Stub the R2 upload used by broll so each clip yields a deterministic key."""
    calls: list[str] = []

    def fake_upload(job_id, local_path):
        key = f"jobs/{job_id}/broll/{len(calls)}.mp4"
        calls.append(local_path)
        return key

    monkeypatch.setattr(broll, "_upload_broll_clip", fake_upload)
    return calls


def _patch_duration(monkeypatch, value=3.0):
    monkeypatch.setattr(broll, "_probe_duration", lambda local_path: float(value))


# --------------------------------------------------------------------------- #
# 1. Happy path — returns clip dicts with broll_key
# --------------------------------------------------------------------------- #
def test_suggest_returns_clip_dicts_with_broll_key(monkeypatch):
    _patch_terms(monkeypatch, ["ocean waves", "city night"])
    _patch_download(monkeypatch, ["/tmp/a.mp4", "/tmp/b.mp4"])
    _patch_upload(monkeypatch)
    _patch_duration(monkeypatch, 4.2)

    result = broll.suggest_broll(
        job_id="job123",
        subject="Ocean documentary",
        script="Waves crash on the shore.",
        source="pexels",
        amount=6,
    )

    assert isinstance(result, list)
    assert len(result) == 2
    for clip in result:
        assert clip["broll_key"].startswith("jobs/job123/broll/")
        assert clip["source"] == "pexels"
        assert clip["duration"] == 4.2
        assert clip["term"] in {"ocean waves", "city night"}


def test_suggest_forwards_aspect_and_source_to_material(monkeypatch):
    recorder: dict = {}
    _patch_terms(monkeypatch, ["mountains"])
    _patch_download(monkeypatch, ["/tmp/a.mp4"], recorder=recorder)
    _patch_upload(monkeypatch)
    _patch_duration(monkeypatch)

    broll.suggest_broll(
        job_id="j1",
        subject="Hiking",
        source="pixabay",
        aspect=VideoAspect.landscape,
    )

    assert recorder["task_id"] == "j1"
    assert recorder["source"] == "pixabay"
    assert recorder["video_aspect"] == VideoAspect.landscape
    assert recorder["search_terms"] == ["mountains"]


# --------------------------------------------------------------------------- #
# 2. Best-effort — a download failure yields [] (no raise)
# --------------------------------------------------------------------------- #
def test_download_failure_yields_empty_list(monkeypatch):
    import app.services.material as material

    _patch_terms(monkeypatch, ["boom"])

    def boom(**kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(material, "download_videos", boom)

    result = broll.suggest_broll(job_id="job123", subject="anything")
    assert result == []


def test_term_generation_failure_falls_back_to_subject_words(monkeypatch):
    import app.services.llm as llm

    def boom(video_subject, video_script, amount):
        raise RuntimeError("llm down")

    monkeypatch.setattr(llm, "generate_terms", boom)
    recorder: dict = {}
    _patch_download(monkeypatch, ["/tmp/a.mp4"], recorder=recorder)
    _patch_upload(monkeypatch)
    _patch_duration(monkeypatch)

    result = broll.suggest_broll(job_id="j1", subject="Red Fox Running")

    # Fell back to distinct subject words as search terms.
    assert recorder["search_terms"] == ["Red", "Fox", "Running"]
    assert len(result) == 1


def test_empty_terms_and_empty_subject_returns_empty(monkeypatch):
    _patch_terms(monkeypatch, [])
    # download must never be reached; make it explode if it is.
    import app.services.material as material

    monkeypatch.setattr(
        material,
        "download_videos",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    assert broll.suggest_broll(job_id="j1", subject="   ") == []


def test_upload_failure_skips_only_that_clip(monkeypatch):
    _patch_terms(monkeypatch, ["a", "b"])
    _patch_download(monkeypatch, ["/tmp/good.mp4", "/tmp/bad.mp4"])
    _patch_duration(monkeypatch)

    def flaky_upload(job_id, local_path):
        if "bad" in local_path:
            raise RuntimeError("R2 down")
        return f"jobs/{job_id}/broll/ok.mp4"

    monkeypatch.setattr(broll, "_upload_broll_clip", flaky_upload)

    result = broll.suggest_broll(job_id="j1", subject="things")
    assert len(result) == 1
    assert result[0]["broll_key"] == "jobs/j1/broll/ok.mp4"


def test_missing_job_id_returns_empty(monkeypatch):
    _patch_terms(monkeypatch, ["x"])
    result = broll.suggest_broll(job_id="", subject="hi")
    assert result == []


# --------------------------------------------------------------------------- #
# 3. amount is clamped
# --------------------------------------------------------------------------- #
def test_amount_is_clamped_to_max(monkeypatch):
    seen: dict = {}

    def spy_terms(video_subject, video_script, amount):
        seen["amount"] = amount
        return [f"t{i}" for i in range(amount)]

    import app.services.llm as llm

    monkeypatch.setattr(llm, "generate_terms", spy_terms)
    # Return more clips than the cap; result must be truncated to the cap.
    _patch_download(monkeypatch, [f"/tmp/{i}.mp4" for i in range(100)])
    _patch_upload(monkeypatch)
    _patch_duration(monkeypatch)

    result = broll.suggest_broll(job_id="j1", subject="lots", amount=999)

    assert seen["amount"] == broll.MAX_BROLL_AMOUNT
    assert len(result) == broll.MAX_BROLL_AMOUNT


def test_amount_below_one_clamps_to_one(monkeypatch):
    seen: dict = {}

    def spy_terms(video_subject, video_script, amount):
        seen["amount"] = amount
        return ["only"]

    import app.services.llm as llm

    monkeypatch.setattr(llm, "generate_terms", spy_terms)
    _patch_download(monkeypatch, ["/tmp/a.mp4"])
    _patch_upload(monkeypatch)
    _patch_duration(monkeypatch)

    result = broll.suggest_broll(job_id="j1", subject="x", amount=0)
    assert seen["amount"] == 1
    assert len(result) == 1


@pytest.mark.parametrize(
    "given,expected",
    [(-5, 1), (0, 1), (1, 1), (6, 6), (12, 12), (13, 12), (10_000, 12), ("bad", 1)],
)
def test_clamp_amount(given, expected):
    assert broll._clamp_amount(given) == expected


# --------------------------------------------------------------------------- #
# 4. get_broll_local — ownership guard + best-effort
# --------------------------------------------------------------------------- #
def test_get_broll_local_blocks_cross_tenant_key(monkeypatch):
    import app.services.reelforge as reelforge

    def deny(job_id, key):
        raise PermissionError("not yours")

    monkeypatch.setattr(reelforge, "_assert_owned_r2_key", deny)

    # Must return None (not raise) and must never attempt a download.
    assert (
        broll.get_broll_local("jobs/victim/broll/x.mp4", job_id="attacker") is None
    )


def test_get_broll_local_empty_key_returns_none():
    assert broll.get_broll_local("") is None


def test_get_broll_local_download_failure_returns_none(monkeypatch):
    class FakeClient:
        def presign_get(self, key):
            raise RuntimeError("no r2")

    monkeypatch.setattr(
        "app.services.storage.r2.get_r2_client", lambda: FakeClient()
    )
    assert broll.get_broll_local("jobs/j1/broll/x.mp4") is None
