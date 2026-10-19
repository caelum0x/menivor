"""Long->short auto-clipping tests.

Covers the three deliverables:
  * transcript -> ranked clip segments (pure policy, word-boundary snapping),
  * segment -> vertical-reframed RenderSpec draft (service),
  * edge cases (no speech, very long input),
plus the ported cross-fade stitch primitive and boundary schema validation.

All network/ML/ffmpeg calls sit behind injectable seams and are faked here.
"""

from __future__ import annotations

import hashlib
import importlib
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.domains.clipping import policy
from app.domains.clipping import external_source
from app.domains.clipping import service as clipping_service
from app.domains.clipping.external_source import (
    ExternalSourceError,
    download_external_video,
    safe_external_source_ref,
)
from app.domains.clipping.policy import ClipPlan, Word
from app.domains.clipping.schemas import ClipJobCreateRequest
from app.domains.clipping.service import (
    ClipRequest,
    ClippingResult,
    ClippingService,
    build_draft,
)
from app.models.db.base import Base
from app.models.db.models import User
from app.models.db.repositories import JobRepository
from app.models.exception import HttpException
from app.services.compose import transitions
from app.utils import utils


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _words(n: int, *, step: float = 1.0, dur: float = 0.9) -> list[Word]:
    """n one-word-per-second timings: word i spans [i*step, i*step+dur]."""
    return [
        Word(text=f"w{i}", start_s=i * step, end_s=i * step + dur) for i in range(n)
    ]


def _seg(start, end, score=90, **kw):
    return {"start_s": start, "end_s": end, "score": score, **kw}


# --------------------------------------------------------------------------- #
# 1. Pure policy: transcript -> ranked clip segments
# --------------------------------------------------------------------------- #
def test_clipping_plan_clips_selects_ranked_nonoverlapping():
    words = _words(140)
    ranked = [
        _seg(0, 30, 92, title="Hook"),  # best
        _seg(20, 50, 88),  # overlaps best -> skipped
        _seg(60, 90, 80, title="Part 2"),  # next best -> picked
        _seg(95, 100, 99),  # too short (5s) -> filtered
    ]
    plans = policy.plan_clips(
        words, ranked, target_count=5, min_len_s=15, max_len_s=60, score_floor=50
    )
    assert [p.score for p in plans] == [92, 80]
    assert plans[0].title == "Hook"
    # Windows are snapped to word boundaries and stay non-overlapping.
    assert plans[0].end_s <= plans[1].start_s
    # The transcript is the exact words inside the snapped window.
    assert plans[0].transcript.startswith("w0")


def test_clipping_cut_points_snap_to_word_boundaries():
    words = [Word("a", 10.2, 11.0), Word("b", 11.0, 12.4), Word("c", 12.4, 13.1)]
    # A loose [10, 13] window snaps to the enclosing word span [10.2, 13.1].
    start_s, end_s = policy.cut_points_from_window(words, 10.0, 13.0)
    assert start_s == pytest.approx(10.2)
    assert end_s == pytest.approx(13.1)


def test_clipping_segments_from_words_windows_on_boundaries():
    words = _words(120)  # ~0..120s
    segs = policy.segments_from_words(words, window_s=60)
    assert len(segs) == 2
    assert segs[0]["start_s"] == pytest.approx(0.0)
    assert all(s["end_s"] > s["start_s"] and s["text"] for s in segs)


def test_clipping_should_stitch():
    one = [ClipPlan(0, 20, 80)]
    two = [ClipPlan(0, 20, 80), ClipPlan(30, 55, 70)]
    assert policy.should_stitch(one) is False
    assert policy.should_stitch(two) is True


# --------------------------------------------------------------------------- #
# 2. Service: segment -> vertical-reframed RenderSpec draft
# --------------------------------------------------------------------------- #
def test_clipping_build_draft_is_vertical_with_caption():
    plan = ClipPlan(12.0, 40.0, 85, title="T", transcript="hello world")
    draft = build_draft(plan, source_ref="uploads/vid.mp4", caption_style="hormozi")
    spec = draft.render_spec
    assert spec.aspect == "9:16"
    assert spec.layout == "fill"
    assert spec.duration_s == pytest.approx(28.0)
    assert len(spec.segments) == 1
    seg = spec.segments[0]
    assert seg.media[0].kind == "clip"
    assert seg.media[0].ref == "uploads/vid.mp4"
    assert seg.caption is not None and seg.caption.text == "hello world"
    # The source window is preserved for the extractor.
    assert draft.source_in_s == 12.0 and draft.source_out_s == 40.0


def test_clipping_build_draft_without_captions_has_no_cue():
    plan = ClipPlan(0.0, 20.0, 70, transcript="x")
    draft = build_draft(plan, caption_style=None)
    assert draft.render_spec.segments[0].caption is None


def test_clipping_service_process_builds_and_renders_vertical_drafts(tmp_path):
    source = tmp_path / "long.mp4"
    source.write_bytes(b"fake-source")

    calls: dict = {"cut": [], "stitched": None}

    def fake_transcriber(audio_path, language="auto"):
        assert audio_path == str(source)
        return _words(120)

    def fake_ranker(segments, *, language="auto"):
        return [{**s, "score": 90} for s in segments]

    def fake_cutter(src, start_s, end_s, out_path, *, words=None, caption_preset=None):
        calls["cut"].append((start_s, end_s, caption_preset))
        # Captions should be re-based onto the clip's own timeline (>= 0).
        assert words is not None and all(w.start_s >= 0 for w in words)
        with open(out_path, "wb") as fh:
            fh.write(b"clip")
        return out_path

    def fake_composer(clip_paths, out_path):
        calls["stitched"] = list(clip_paths)
        with open(out_path, "wb") as fh:
            fh.write(b"stitched")
        return out_path

    service = ClippingService(
        transcriber=fake_transcriber,
        ranker=fake_ranker,
        cutter=fake_cutter,
        composer=fake_composer,
    )
    request = ClipRequest(
        target_count=3, min_len_s=15, max_len_s=60, captions="hormozi"
    )
    result = service.process(
        str(source), request, source_ref="uploads/long.mp4", workdir=str(tmp_path)
    )

    assert isinstance(result, ClippingResult)
    assert result.clip_count == 2
    assert len(result.clip_paths) == 2
    assert result.stitched_path.endswith("stitched.mp4")
    assert calls["stitched"] == list(result.clip_paths)
    # Every draft is a vertical RenderSpec with a burned result path.
    for draft in result.drafts:
        assert draft.render_spec.aspect == "9:16"
        assert draft.result_path
    # The caption preset flowed through to the extractor.
    assert all(preset == "hormozi" for _, _, preset in calls["cut"])


# --------------------------------------------------------------------------- #
# 3. Edge cases
# --------------------------------------------------------------------------- #
def test_clipping_no_speech_returns_note_not_error(tmp_path):
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"x")

    service = ClippingService(
        transcriber=lambda p, language="auto": [],  # no words
        ranker=lambda segs, *, language="auto": segs,
    )
    result = service.process(str(source), ClipRequest(), workdir=str(tmp_path))
    assert result.drafts == ()
    assert result.clip_count == 0
    assert "no speech" in result.note


def test_clipping_empty_transcript_plans_are_empty():
    assert policy.plan_clips([], []) == []
    assert policy.segments_from_words([]) == []


def test_clipping_very_long_input_is_capped_and_in_band(tmp_path):
    source = tmp_path / "marathon.mp4"
    source.write_bytes(b"x")

    # ~1 hour of speech -> dozens of candidate windows.
    words = _words(3600)

    def fake_ranker(segments, *, language="auto"):
        # Descending scores so ordering is exercised, all above the floor.
        return [{**s, "score": 90 - i} for i, s in enumerate(segments)]

    service = ClippingService(
        transcriber=lambda p, language="auto": words,
        ranker=fake_ranker,
    )
    request = ClipRequest(target_count=2, min_len_s=15, max_len_s=60)
    result = service.process(str(source), request, workdir=str(tmp_path))
    # Capped at target_count, every clip inside the duration band, no overlaps.
    assert result.clip_count == 2
    spans = sorted((d.source_in_s, d.source_out_s) for d in result.drafts)
    for start_s, end_s in spans:
        assert 15 <= (end_s - start_s) <= 61  # snapped, so allow +1s slack
    assert spans[0][1] <= spans[1][0]  # non-overlapping


# --------------------------------------------------------------------------- #
# 4. Ported cross-fade stitch primitive
# --------------------------------------------------------------------------- #
def test_clipping_xfade_chain_cumulative_offsets_deterministic():
    labels = ["0:v", "1:v", "2:v"]
    durations = [10.0, 8.0, 6.0]
    graph, out = transitions._xfade_chain(
        labels, durations, 0.5, ("fade",), pick=lambda i: "fade"
    )
    # offset_1 = 10 - 0.5 = 9.5 ; offset_2 = (10 + 8 - 0.5) - 0.5 = 17.0
    assert "offset=9.5" in graph
    assert "offset=17" in graph
    assert out == "vx2"
    assert graph.count("xfade=") == 2


def test_clipping_acrossfade_chain():
    graph, out = transitions._acrossfade_chain(["0:a", "1:a", "2:a"], 0.5)
    assert graph.count("acrossfade=d=0.5") == 2
    assert out == "ax2"


def test_clipping_validate_clips_fails_fast(tmp_path):
    with pytest.raises(ValueError):
        transitions._validate_clips([])
    with pytest.raises(FileNotFoundError):
        transitions._validate_clips([str(tmp_path / "missing.mp4")])


def test_clipping_stitch_single_clip_straight_copy(tmp_path):
    src = tmp_path / "only.mp4"
    src.write_bytes(b"solo-bytes")
    out = tmp_path / "out.mp4"
    result = transitions.stitch_with_transitions([str(src)], str(out))
    assert result == str(out)
    assert out.read_bytes() == b"solo-bytes"  # a genuine straight copy, no re-encode


def test_clipping_stitch_multi_clip_builds_filtergraph(tmp_path, monkeypatch):
    clips = []
    for i in range(3):
        p = tmp_path / f"c{i}.mp4"
        p.write_bytes(b"v")
        clips.append(str(p))

    class _Info:
        def __init__(self, d):
            self.duration = d

    monkeypatch.setattr(transitions, "_probe_video", lambda path: _Info(10.0))
    captured: dict = {}
    monkeypatch.setattr(
        transitions, "_run_ffmpeg", lambda cmd: captured.setdefault("cmd", cmd)
    )

    out = tmp_path / "reel.mp4"
    transitions.stitch_with_transitions(
        clips, str(out), transition_dur=0.5, pick=lambda i: "fade"
    )
    cmd = captured["cmd"]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade=transition=fade" in fc
    assert "acrossfade=d=0.5" in fc
    # Interchange-friendly encode flags per the port contract.
    for flag in ("-pix_fmt", "yuv420p", "libx264", "+faststart"):
        assert flag in cmd


# --------------------------------------------------------------------------- #
# 5. Boundary schema validation (fail-fast)
# --------------------------------------------------------------------------- #
def test_clipping_schema_requires_a_source():
    with pytest.raises(Exception):
        ClipJobCreateRequest()


def test_clipping_schema_rejects_both_sources():
    with pytest.raises(Exception):
        ClipJobCreateRequest(source_video_key="k", source_url="https://x")


def test_clipping_schema_length_band_sanity():
    with pytest.raises(Exception):
        ClipJobCreateRequest(source_video_key="k", min_len_s=60, max_len_s=30)


def test_clipping_schema_accepts_valid_request():
    req = ClipJobCreateRequest(source_video_key="uploads/a.mp4", target_count=4)
    assert req.target_count == 4
    assert req.captions == "hormozi"


@pytest.mark.parametrize(
    "source_url",
    (
        "http://example.com/video.mp4",
        "file:///tmp/video.mp4",
        "https://user:password@example.com/video.mp4",
        "https://example.com/video.mp4#fragment",
        "https://example.com\\@127.0.0.1/video.mp4",
        "https://example.com/video file.mp4",
    ),
)
def test_clipping_schema_rejects_unsafe_external_url_syntax(source_url):
    with pytest.raises(Exception):
        ClipJobCreateRequest(source_url=source_url)


class _DownloadResponse:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = tuple(chunks)
        self.closed = False

    def iter_content(self, chunk_size):
        assert chunk_size > 0
        yield from self._chunks

    def close(self):
        self.closed = True


class _DownloadSession:
    def __init__(self, response):
        self.response = response
        self.mounts = []
        self.requests = []
        self.trust_env = True
        self.closed = False

    def mount(self, prefix, adapter):
        self.mounts.append((prefix, adapter))

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response

    def close(self):
        self.closed = True


def test_external_video_download_streams_atomically_and_hides_query(tmp_path):
    response = _DownloadResponse(
        headers={"Content-Type": "video/mp4", "Content-Length": "6"},
        chunks=(b"abc", b"def"),
    )
    session = _DownloadSession(response)
    destination = tmp_path / "source.mp4"
    url = "https://93.184.216.34/video.mp4?temporary-secret=one"

    assert download_external_video(
        url, str(destination), session_factory=lambda: session
    ) == str(destination)
    assert destination.read_bytes() == b"abcdef"
    assert not (tmp_path / "source.mp4.part").exists()
    assert session.trust_env is False
    assert session.closed and response.closed
    assert session.requests[0][1]["allow_redirects"] is False
    reference = safe_external_source_ref(url)
    assert reference.startswith("external:")
    assert "temporary-secret" not in reference


@pytest.mark.parametrize(
    "url",
    (
        "https://127.0.0.1/video.mp4",
        "https://10.0.0.4/video.mp4",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/video.mp4",
    ),
)
def test_external_video_download_blocks_internal_targets_before_transport(
    tmp_path, url
):
    called = False

    def session_factory():
        nonlocal called
        called = True
        raise AssertionError("transport must not open")

    with pytest.raises(ExternalSourceError) as error:
        download_external_video(
            url, str(tmp_path / "blocked.mp4"), session_factory=session_factory
        )
    assert error.value.status_code == 422
    assert called is False


def test_external_video_never_honors_webhook_internal_network_override(
    tmp_path, monkeypatch
):
    from app.services import webhooks

    monkeypatch.setattr(webhooks, "_allow_internal", lambda: True)
    with pytest.raises(ExternalSourceError) as error:
        download_external_video(
            "https://127.0.0.1/video.mp4",
            str(tmp_path / "blocked.mp4"),
            session_factory=lambda: pytest.fail("transport must not open"),
        )
    assert error.value.status_code == 422


def test_external_video_redirect_is_revalidated_before_follow(tmp_path):
    response = _DownloadResponse(
        status=302,
        headers={"Location": "https://127.0.0.1/internal.mp4"},
    )
    sessions = []

    def session_factory():
        session = _DownloadSession(response)
        sessions.append(session)
        return session

    with pytest.raises(ExternalSourceError) as error:
        download_external_video(
            "https://93.184.216.34/redirect",
            str(tmp_path / "redirect.mp4"),
            session_factory=session_factory,
        )
    assert error.value.status_code == 422
    assert len(sessions) == 1
    assert sessions[0].closed and response.closed


def test_external_video_follows_only_revalidated_public_redirects(tmp_path):
    responses = iter(
        (
            _DownloadResponse(
                status=302,
                headers={"Location": "https://142.250.72.14/final.mp4"},
            ),
            _DownloadResponse(
                headers={"Content-Type": "video/mp4"}, chunks=(b"video",)
            ),
        )
    )
    sessions = []

    def session_factory():
        session = _DownloadSession(next(responses))
        sessions.append(session)
        return session

    destination = tmp_path / "redirected.mp4"
    download_external_video(
        "https://93.184.216.34/start",
        str(destination),
        session_factory=session_factory,
    )
    assert destination.read_bytes() == b"video"
    assert len(sessions) == 2
    assert sessions[1].requests[0][0] == "https://142.250.72.14/final.mp4"
    assert all(session.closed for session in sessions)


def test_external_video_rejects_non_video_and_cleans_partial_file(
    tmp_path, monkeypatch
):
    html = _DownloadResponse(
        headers={"Content-Type": "text/html"}, chunks=(b"not video",)
    )
    with pytest.raises(ExternalSourceError) as wrong_type:
        download_external_video(
            "https://93.184.216.34/page",
            str(tmp_path / "wrong.mp4"),
            session_factory=lambda: _DownloadSession(html),
        )
    assert wrong_type.value.status_code == 415

    monkeypatch.setattr(external_source, "MAX_EXTERNAL_SOURCE_BYTES", 4)
    oversized = _DownloadResponse(
        headers={"Content-Type": "video/mp4"}, chunks=(b"123", b"45")
    )
    destination = tmp_path / "oversized.mp4"
    with pytest.raises(ExternalSourceError) as too_large:
        download_external_video(
            "https://93.184.216.34/video.mp4",
            str(destination),
            session_factory=lambda: _DownloadSession(oversized),
        )
    assert too_large.value.status_code == 413
    assert not destination.exists()
    assert not (tmp_path / "oversized.mp4.part").exists()


def test_clipping_source_resolution_materializes_external_bytes_and_safe_ref(
    tmp_path, monkeypatch
):
    url = "https://example.com/source.webm?signed-secret=value"

    def fake_download(requested_url, destination):
        assert requested_url == url
        with open(destination, "wb") as output:
            output.write(b"video")
        return destination

    monkeypatch.setattr(external_source, "download_external_video", fake_download)
    path, source_ref = clipping_service._resolve_source(
        {"source_url": url}, str(tmp_path)
    )
    assert path.endswith("external_source.webm")
    assert (tmp_path / "external_source.webm").read_bytes() == b"video"
    assert source_ref.startswith("external:")
    assert "signed-secret" not in source_ref


def test_clipping_rendered_artifacts_become_durable_before_temp_cleanup(
    tmp_path, monkeypatch
):
    first = tmp_path / "clip_00.mp4"
    second = tmp_path / "clip_01.mp4"
    stitched = tmp_path / "stitched.mp4"
    for path in (first, second, stitched):
        path.write_bytes(b"video")
    drafts = (
        build_draft(ClipPlan(0, 10, 90), result_path=str(first)),
        build_draft(ClipPlan(20, 30, 80), result_path=str(second)),
    )
    uploaded = []

    def fake_upload(user_id, job_id, local_path):
        uploaded.append((user_id, job_id, local_path))
        return f"clipping/{user_id}/{job_id}/{local_path.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(clipping_service, "_upload_result", fake_upload)
    durable = clipping_service._durabilize_result(
        "user_1",
        "job_1",
        ClippingResult(
            drafts=drafts,
            clip_paths=(str(first), str(second)),
            stitched_path=str(stitched),
        ),
    )
    assert len(uploaded) == 3
    assert durable.clip_paths == () and durable.stitched_path == ""
    assert durable.stitched_key.endswith("/stitched.mp4")
    assert [draft.result_path for draft in durable.drafts] == ["", ""]
    assert [draft.result_key.rsplit("/", 1)[-1] for draft in durable.drafts] == [
        "clip_00.mp4",
        "clip_01.mp4",
    ]
    serialized = durable.to_dict()
    assert serialized["clips"][0]["result_key"].endswith("/clip_00.mp4")
    assert serialized["clips"][0]["start_s"] == 0
    assert serialized["clips"][0]["end_s"] == 10


# --------------------------------------------------------------------------- #
# 6. HTTP router flow (owner-scoped, enqueue faked)
# --------------------------------------------------------------------------- #

clipping_router_mod = importlib.import_module("app.domains.clipping.router")


def _key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.fixture()
def clip_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )


@pytest.fixture()
def clip_env(monkeypatch, clip_factory):
    @contextmanager
    def _fake_get_session():
        s = clip_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    class _FakeAsync:
        id = "celery-task-1"

    class _FakeTasks:
        class run_clipping:
            @staticmethod
            def apply_async(*a, **k):
                return _FakeAsync()

    monkeypatch.setattr(clipping_router_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(clipping_router_mod, "_DB_IMPORT_ERROR", None)
    monkeypatch.setattr(clipping_router_mod, "_import_worker", lambda rid: _FakeTasks)

    app = FastAPI()
    app.include_router(clipping_router_mod.router)

    def _handler(_request, exc: HttpException):
        return JSONResponse(
            status_code=exc.status_code,
            content=utils.get_response(exc.status_code, exc.data, exc.message),
        )

    app.add_exception_handler(HttpException, _handler)
    return TestClient(app), clip_factory


@pytest.fixture()
def clip_users(clip_factory):
    out = {}
    with clip_factory() as s:
        for label, raw in (("alice", "alice-key"), ("bob", "bob-key")):
            u = User(email=f"{label}@example.com", api_key_hash=_key_hash(raw))
            s.add(u)
            s.flush()
            out[label] = raw
        s.commit()
    return out


def _hdr(raw: str) -> dict:
    return {"x-api-key": raw}


def test_clipping_router_create_and_get(clip_env, clip_users):
    client, _ = clip_env
    created = client.post(
        "/api/v1/clipping/jobs",
        json={"source_video_key": "uploads/long.mp4", "target_count": 3},
        headers=_hdr(clip_users["alice"]),
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]

    got = client.get(
        f"/api/v1/clipping/jobs/{job_id}", headers=_hdr(clip_users["alice"])
    )
    assert got.status_code == 200
    assert got.json()["data"]["target_count"] == 3

    listed = client.get("/api/v1/clipping/jobs", headers=_hdr(clip_users["alice"]))
    assert [j["id"] for j in listed.json()["data"]["jobs"]] == [job_id]


def test_clipping_router_owner_scoping(clip_env, clip_users):
    client, _ = clip_env
    created = client.post(
        "/api/v1/clipping/jobs",
        json={"source_video_key": "uploads/x.mp4"},
        headers=_hdr(clip_users["alice"]),
    )
    job_id = created.json()["data"]["id"]
    assert (
        client.get(
            f"/api/v1/clipping/jobs/{job_id}", headers=_hdr(clip_users["bob"])
        ).status_code
        == 404
    )


def test_clipping_router_bad_source_is_422(clip_env, clip_users):
    client, _ = clip_env
    resp = client.post(
        "/api/v1/clipping/jobs", json={}, headers=_hdr(clip_users["alice"])
    )
    assert resp.status_code == 422


def test_clipping_router_list_and_promote_clips(clip_env, clip_users):
    client, factory = clip_env
    created = client.post(
        "/api/v1/clipping/jobs",
        json={"source_video_key": "uploads/pod.mp4"},
        headers=_hdr(clip_users["alice"]),
    )
    job_id = created.json()["data"]["id"]

    # Simulate the worker having produced two clip drafts on the job.
    with factory() as s:
        job = JobRepository(s).get(job_id)
        job.stages = {
            "clips": [
                {
                    "source_in_s": 0,
                    "source_out_s": 30,
                    "length_s": 30,
                    "title": "Hook",
                    "transcript": "first clip",
                    "result_key": f"clipping/alice/{job_id}/clip_00.mp4",
                },
                {
                    "source_in_s": 60,
                    "source_out_s": 90,
                    "title": "Part 2",
                    "transcript": "second clip",
                },
            ],
            "stitched_key": f"clipping/alice/{job_id}/stitched.mp4",
        }
        s.commit()

    status = client.get(
        f"/api/v1/clipping/jobs/{job_id}", headers=_hdr(clip_users["alice"])
    )
    assert status.json()["data"]["stitched_key"].endswith("/stitched.mp4")

    clips = client.get(
        f"/api/v1/clipping/jobs/{job_id}/clips", headers=_hdr(clip_users["alice"])
    )
    assert clips.status_code == 200
    rows = clips.json()["data"]["clips"]
    assert [r["id"] for r in rows] == [f"{job_id}:0", f"{job_id}:1"]

    promoted = client.post(
        f"/api/v1/clipping/clips/{job_id}:0/promote", headers=_hdr(clip_users["alice"])
    )
    assert promoted.status_code == 200
    draft = promoted.json()["data"]["reel_draft"]
    assert draft["video_script"] == "first clip"
    assert draft["source_ref"].endswith("/clip_00.mp4")
    assert draft["start_s"] == 0 and draft["end_s"] == 30
