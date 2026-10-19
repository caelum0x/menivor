"""Wave P PM3.5: MV12 QoE analytics, MV16 AI panel, MV19 discovery.

1. Numbers only from beacons; no third-party trackers; dashboard totals match
   raw beacon counts.
2. WebVTT per language as HLS subtitle renditions; dubs as alternate audio;
   chapters on sentence boundaries; every LLM call through Relay.
3. Search p95 under 300 ms on 5k titles (target, measured here); "ask this
   video" cites a timestamp or says it does not know; embeddings on CPU.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import statistics
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

import app.domains.ott.roles  # noqa: F401  (registers ott_channel_members)
import app.domains.ott_ai.models  # noqa: F401
import app.domains.ott_analytics.models  # noqa: F401
import app.domains.ott_discovery.models  # noqa: F401
from app.domains.ott.models import OttTitle
from app.domains.ott_access import tokens
from app.domains.ott_ai import audio_tracks, chapters, pipeline, router as ai_router, subtitles
from app.domains.ott_ai.models import OttAiOutput
from app.domains.ott_analytics import router as analytics_router, service as qoe
from app.domains.ott_discovery import ask as asking, router as discovery_router, search
from app.domains.ott_discovery.embeddings import HashingEmbedder
from app.services.billing import ott_usage

from tests.reelforge import _wp_p3_ott as h

REPO = Path(__file__).resolve().parents[2]
OWNER = {"x-api-key": h.OWNER_KEY}


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (analytics_router, ai_router, discovery_router))
    h.enable(monkeypatch, "analytics", "ai", "discovery")
    monkeypatch.setenv(tokens.SECRET_ENV, "x" * 40)
    monkeypatch.setenv("OTT_ANALYTICS_SALT", "salt-for-tests")
    monkeypatch.setenv("OTT_DISCOVERY_EMBEDDER", "hashing")
    monkeypatch.setattr(analytics_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(discovery_router, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr("app.domains.ott.catalog_public._art", lambda key: "")
    from app.domains.ott_discovery import embeddings

    embeddings.default_embedder.cache_clear()
    search.reset_cache()
    owner = h.owner(factory)
    cid, ids = h.channel(factory, owner, "maya", titles=3)
    client = h.app_client(analytics_router.router, ai_router.router, discovery_router.router)
    yield {"factory": factory, "client": client, "owner": owner, "cid": cid, "ids": ids}
    embeddings.default_embedder.cache_clear()


# --------------------------------------------------------------------------- #
# MV12
# --------------------------------------------------------------------------- #
def _beacons(env, events, device_id="dev-1", headers=None):
    return env["client"].post("/api/v1/ott/beacons", json={"events": events, "device_id": device_id},
                              headers=headers or {})


def test_beacons_roll_up_and_the_dashboard_matches_raw_counts(env):
    t0, t1 = env["ids"][0], env["ids"][1]
    sessions = [f"sess-{n:04d}" for n in range(6)]
    for n, sid in enumerate(sessions):
        title = t0 if n < 4 else t1
        events = [{"event": "start", "session_id": sid, "title_id": title, "startup_ms": 800 + 100 * n}]
        events += [{"event": "heartbeat", "session_id": sid, "title_id": title, "watched_s": 10} for _ in range(3)]
        if n % 2 == 0:
            events.append({"event": "stall", "session_id": sid, "title_id": title, "stall_ms": 1200})
        if n == 5:
            events.append({"event": "error", "session_id": sid, "title_id": title, "error_code": "net/404"})
        assert _beacons(env, events, device_id=f"device-{n % 3}").status_code == 204
    junk = [{"event": "nope", "session_id": "sess-0000", "title_id": t0},
            {"event": "start", "session_id": "x", "title_id": t0},
            {"event": "start", "session_id": "sess-9999", "title_id": "missing"},
            {"event": "heartbeat", "session_id": "sess-0001", "title_id": t0, "watched_s": 99999}]
    _beacons(env, junk, device_id="device-1")
    with env["factory"]() as s:
        hour = qoe.hour_key(datetime.now(timezone.utc))
        assert qoe.rollup(s, hour) == 2
        assert qoe.rollup(s, hour) == 2  # idempotent
        s.commit()
        from app.domains.ott.models import OttChannel

        channel = s.get(OttChannel, env["cid"])
        raw = qoe.raw_totals(s, channel)
    data = env["client"].get("/api/v1/ott/studio/analytics?days=7", headers=OWNER).json()["data"]
    totals = data["totals"]
    assert {k: totals[k] for k in raw} == raw
    assert totals["plays"] == 6 and totals["stalls"] == 3 and totals["errors"] == 1
    assert raw["watch_minutes"] == pytest.approx((18 * 10 + 60) / 60, abs=0.01)  # the 99999 s beat clamps to 60
    assert totals["viewers"] == 3 and data["source"] == "first-party player beacons"
    top = data["titles"][0]
    assert top["title_id"] == t0 and top["plays"] == 4 and top["startup_p95_ms"] == 1100


def test_no_third_party_tracker_and_no_personal_data_is_stored(env):
    _beacons(env, [{"event": "start", "session_id": "sess-abcdefgh", "title_id": env["ids"][0]}], device_id="dev-x")
    from app.domains.ott_analytics.models import OttBeacon

    with env["factory"]() as s:
        row = s.execute(select(OttBeacon)).scalar_one()
    assert row.viewer_hash != "dev-x" and len(row.viewer_hash) == 32 and row.country == "XX"
    web = REPO / "apps/web/src/features/ott-analytics"
    source = "\n".join(p.read_text() for p in web.glob("*.ts*") if ".test." not in p.name)
    assert not re.search(r"google-analytics|googletagmanager|segment\.io|mixpanel|amplitude|posthog|facebook",
                         source, re.I)
    assert "/ott/beacons" in source


def test_raw_beacons_are_swept_after_thirty_days(env):
    with env["factory"]() as s:
        qoe.ingest(s, [{"event": "start", "session_id": "sess-oldoldold", "title_id": env["ids"][0]}], identity="d",
                   at=datetime.now(timezone.utc) - timedelta(days=31))
        s.commit()
        assert qoe.sweep(s) == 1


def test_team_roles_share_analytics_but_not_the_team(env):
    member_id = h.owner(env["factory"], "analyst@example.com", "analyst-key")
    added = env["client"].post("/api/v1/ott/studio/team", headers=OWNER,
                               json={"email": "Analyst@example.com", "role": "analyst"})
    assert added.json()["data"]["members"][0]["role"] == "analyst"
    analyst = {"x-api-key": "analyst-key"}
    shared = env["client"].get("/api/v1/ott/studio/analytics?channel=maya", headers=analyst)
    assert shared.status_code == 200 and shared.json()["data"]["channel"] == "maya"
    # Wave Q QM1.0 (P-M15): an unknown email gets the same answer as a known one.
    assert env["client"].post("/api/v1/ott/studio/team", headers=OWNER,
                              json={"email": "nobody@example.com", "role": "analyst"}).status_code == 200
    other = h.owner(env["factory"], "x@example.com", "x-key")
    assert env["client"].get("/api/v1/ott/studio/analytics?channel=maya", headers={"x-api-key": "x-key"}
                             ).status_code == 403
    del member_id, other


# --------------------------------------------------------------------------- #
# MV16
# --------------------------------------------------------------------------- #
class Word:
    def __init__(self, text, start, end):
        self.text, self.start, self.end = text, start, end


def _words(script: str, *, gap: float = 0.4):
    out, at = [], 0.0
    for token in script.split():
        out.append(Word(token, at, at + gap))
        at += gap
    return out


SCRIPT = ("Welcome to the kitchen. Today we bake bread. First mix flour and water. Let it rest for an hour. "
          "Now knead the dough firmly. Shape it into a round loaf. Bake it until the crust is golden. "
          "Let it cool before slicing. That is all for today.")


def test_cues_split_on_sentences_and_stay_readable():
    cues = subtitles.cues_from_words(_words(SCRIPT))
    assert cues[0].text == "Welcome to the kitchen."
    assert all(c.end - c.start <= subtitles.MAX_CUE_S + 0.5 and len(c.text) <= subtitles.MAX_CUE_CHARS for c in cues)
    vtt = subtitles.to_vtt(cues)
    assert vtt.startswith("WEBVTT") and "00:00:00.000 --> " in vtt


def test_translation_keeps_the_cue_count_or_fails():
    cues = subtitles.cues_from_words(_words(SCRIPT))
    prompts = []

    def good(prompt):
        prompts.append(prompt)
        lines = json.loads(prompt.split("\n", 1)[1])
        return "```json\n" + json.dumps([f"ES {x}" for x in lines]) + "\n```"

    out = subtitles.translate(cues, "es", llm=good)
    assert [c.start for c in out] == [c.start for c in cues] and out[0].text.startswith("ES ")
    assert "Español" in prompts[0]
    with pytest.raises(ValueError):
        subtitles.translate(cues, "es", llm=lambda p: json.dumps(["just one"]))


def test_subtitle_and_audio_renditions_join_the_master():
    master = ("#EXTM3U\n#EXT-X-VERSION:6\n"
              '#EXT-X-MEDIA:TYPE=AUDIO,URI="a_main.m3u8",GROUP-ID="audio",NAME="Main",DEFAULT=YES,AUTOSELECT=YES\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=720x1280,AUDIO="audio"\nv_720p.m3u8\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=480x854,AUDIO="audio"\nv_480p.m3u8\n')
    out = subtitles.add_rendition(master, kind="SUBTITLES", group="subs", language="es", name="Español",
                                  uri="subs/es.m3u8")
    out = subtitles.add_rendition(out, kind="SUBTITLES", group="subs", language="es", name="Español",
                                  uri="subs/es.m3u8")  # replacing, not duplicating
    out = subtitles.add_rendition(out, kind="AUDIO", group="audio", language="es", name="Español",
                                  uri="a_dub_es.m3u8")
    assert out.count('TYPE=SUBTITLES,GROUP-ID="subs",LANGUAGE="es"') == 1
    assert 'TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="es"' in out
    variants = [line for line in out.splitlines() if line.startswith("#EXT-X-STREAM-INF")]
    assert all('SUBTITLES="subs"' in v and v.count('AUDIO="audio"') == 1 for v in variants)
    playlist = subtitles.media_playlist("es.vtt", 95.2)
    assert "#EXT-X-TARGETDURATION:96" in playlist and "es.vtt" in playlist and "#EXT-X-ENDLIST" in playlist


def test_chapters_start_on_sentence_boundaries():
    sentences = subtitles.sentences(subtitles.cues_from_words(_words(SCRIPT, gap=4.0)))
    answer = json.dumps([{"start": 0, "title": "Welcome"}, {"start": 2, "title": "Mixing"},
                         {"start": 3, "title": "Too soon"}, {"start": 4, "title": "Kneading"},
                         {"start": 99, "title": "Out of range"}, {"start": 6, "title": "Baking with Sora"}])
    chosen = chapters.choose(sentences, llm=lambda p: answer)
    starts = {round(s.start, 3) for s in sentences}
    assert [c["title"] for c in chosen] == ["Welcome", "Mixing", "Kneading"]
    assert all(c["start_s"] in starts for c in chosen)
    assert chosen[-1]["end_s"] == round(sentences[-1].end, 3)
    assert chapters.to_vtt(chosen).startswith("WEBVTT\n\nchapter-1\n00:00:00.000 -->")


class MemoryStore:
    def __init__(self, master: str):
        self.objects = {}
        self.master_key = None
        self._master = master

    def read(self, key):
        return self.objects.get(key, self._master.encode())

    def put(self, key, data, content_type):
        self.objects[key] = data

    def source_url(self, source_key):
        return f"https://r2.example/{source_key}"


def _llm(prompt: str) -> str:
    if "JSON array of" in prompt:
        lines = json.loads(prompt.split("\n", 1)[1])
        return json.dumps([f"[es] {x}" for x in lines])
    if "chapters" in prompt:
        return json.dumps([{"start": 0, "title": "Start"}, {"start": 4, "title": "Kneading"}])
    return json.dumps({"title": "Bake bread at home", "synopsis": "A short bread lesson.", "tags": ["baking", "bread"]})


def test_the_ai_panel_run_adds_subtitles_chapters_metadata_and_meters_minutes(env, monkeypatch):
    counted = []
    monkeypatch.setattr(ott_usage, "count_ai_minutes", lambda uid, minutes, now=None: counted.append((uid, minutes)))
    monkeypatch.setattr(ai_router, "enqueue", lambda title_id, lang: None)
    title_id = env["ids"][0]
    queued = env["client"].post(f"/api/v1/ott/studio/titles/{title_id}/ai", headers=OWNER,
                                json={"kinds": ["subtitles", "chapters", "metadata"], "languages": ["es"],
                                      "source_language": "en"})
    assert queued.status_code == 200, queued.text
    assert {(o["kind"], o["language"]) for o in queued.json()["data"]["outputs"]} >= {
        ("transcript", "en"), ("subtitles", "en"), ("subtitles", "es"), ("chapters", "en"), ("metadata", "")}
    master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="audio"\nv_720p.m3u8\n'
    store = MemoryStore(master)
    deps = pipeline.Deps(store=store, llm=_llm, download=lambda url, path: Path(path).write_bytes(b"x"),
                         transcribe=lambda wav, lang: _words(SCRIPT, gap=2.0), ffmpeg="true")
    with env["factory"]() as s:
        title = s.get(OttTitle, title_id)
        result = pipeline.run(s, title, "en", deps)
        s.commit()
    assert result["failed"] == 0 and result["done"] == 5
    prefix = f"ott/{env['cid']}/t0/j"
    assert store.objects[f"{prefix}/subs/es.vtt"].decode().startswith("WEBVTT")
    assert b"[es] Welcome" in store.objects[f"{prefix}/subs/es.vtt"]
    final = store.objects[f"{prefix}/master.m3u8"].decode()
    assert 'LANGUAGE="en"' in final and 'LANGUAGE="es"' in final and 'SUBTITLES="subs"' in final
    assert f"{prefix}/chapters.vtt" in store.objects
    view = env["client"].get(f"/api/v1/ott/studio/titles/{title_id}/ai", headers=OWNER).json()["data"]
    meta = next(o for o in view["outputs"] if o["kind"] == "metadata")
    assert meta["suggestion"]["title"] == "Bake bread at home"
    public = env["client"].get(f"/api/v1/ott/titles/{title_id}/chapters").json()["data"]["chapters"]
    assert [c["title"] for c in public] == ["Start", "Kneading"]
    assert counted and counted[0][0] == env["owner"] and counted[0][1] == pytest.approx(10.0)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_a_dub_becomes_an_alternate_audio_rendition(tmp_path):
    def speak(text, voice, out_path):
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", out_path],
                       check=True, capture_output=True)

    cues = [subtitles.Cue(0.5, 2.0, "Hola"), subtitles.Cue(3.0, 3.8, "Adiós a todos")]
    track = audio_tracks.build(cues, "es", total_s=6.0, work=str(tmp_path / "clips"), ffmpeg="ffmpeg",
                               ffprobe="ffprobe", speak=speak)
    assert audio_tracks.duration("ffprobe", track) == pytest.approx(6.0, abs=0.2)
    out = tmp_path / "hls"
    out.mkdir()
    name = audio_tracks.package(track, str(out), language="es", ffmpeg="ffmpeg")
    playlist = (out / name).read_text()
    assert name == "a_dub_es.m3u8" and '#EXT-X-MAP:URI="a_dub_es/init.mp4"' in playlist
    segments = [line for line in playlist.splitlines() if line and not line.startswith("#")]
    assert segments and all((out / s).exists() for s in segments)


def test_ai_routes_need_the_owner_or_an_editor(env, monkeypatch):
    monkeypatch.setattr(ai_router, "enqueue", lambda title_id, lang: None)
    h.owner(env["factory"], "x@example.com", "x-key")
    res = env["client"].post(f"/api/v1/ott/studio/titles/{env['ids'][0]}/ai", headers={"x-api-key": "x-key"},
                             json={"kinds": ["metadata"]})
    assert res.status_code == 404
    bad = env["client"].post(f"/api/v1/ott/studio/titles/{env['ids'][0]}/ai", headers=OWNER,
                             json={"kinds": ["dub"], "languages": ["xx-notalang!"]})
    assert bad.status_code == 400


def test_every_llm_call_goes_through_relay():
    for folder in ("ott_ai", "ott_discovery"):
        for path in (REPO / "apps/api/app/domains" / folder).glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                for name in names:
                    assert not re.match(r"(openai|anthropic|google\.generativeai|litellm|dashscope)", name), (path, name)


# --------------------------------------------------------------------------- #
# MV19
# --------------------------------------------------------------------------- #
def test_search_finds_titles_by_meaning_and_words(env):
    with env["factory"]() as s:
        for tid, name, synopsis in zip(env["ids"], ("Sourdough basics", "Mountain bike repair", "Knife skills"),
                                       ("Bake bread with a starter", "Fix a flat tyre on the trail",
                                        "Chop onions fast and safely")):
            title = s.get(OttTitle, tid)
            title.title, title.synopsis = name, synopsis
        s.commit()
        assert search.reindex(s, embedder=HashingEmbedder()) == 3
        assert search.reindex(s, embedder=HashingEmbedder()) == 0
        s.commit()
    res = env["client"].get("/api/v1/ott/search?q=bake bread")
    top = res.json()["data"]["results"]
    assert res.status_code == 200 and top[0]["title"] == "Sourdough basics" and top[0]["channel"] == "maya"
    scoped = env["client"].get("/api/v1/ott/search?q=bike&channel=maya").json()["data"]["results"]
    assert scoped[0]["title"] == "Mountain bike repair"


def test_search_p95_is_under_300_ms_on_5000_titles(env):
    import random

    from app.domains.ott.models import OttChannel
    from app.domains.ott_discovery.models import OttTitleEmbedding

    rng = random.Random(7)
    vocab = ["bread", "bike", "garden", "coffee", "travel", "yoga", "guitar", "camera", "code", "paint", "soccer",
             "chess", "piano", "cooking", "hiking", "startup", "design", "science", "history", "music"]
    embedder = HashingEmbedder()
    with env["factory"]() as s:
        channel = s.get(OttChannel, env["cid"])
        texts, titles = [], []
        for n in range(5000):
            words = rng.sample(vocab, 4)
            titles.append(OttTitle(channel_id=channel.id, title=" ".join(words[:2]).title(), synopsis=" ".join(words),
                                   kind="episode", genres=[], geo_countries=[], status="published",
                                   package_status="ready", duration_s=60, access_tier="free",
                                   published_at=datetime.now(timezone.utc)))
            texts.append(" ".join(words))
        s.add_all(titles)
        s.flush()
        vectors = embedder.embed(texts)
        s.add_all([OttTitleEmbedding(title_id=t.id, channel_id=channel.id, model=embedder.name, dim=embedder.dim,
                                     vector=[round(float(x), 6) for x in v], text_hash="x")
                   for t, v in zip(titles, vectors)])
        s.commit()
    timings = []
    with env["factory"]() as s:
        search.search(s, "warm up", embedder=embedder)
        for query in [" ".join(rng.sample(vocab, 2)) for _ in range(40)]:
            started = time.perf_counter()
            result = search.search(s, query, embedder=embedder)
            timings.append((time.perf_counter() - started) * 1000)
            assert result["results"]
    p95 = statistics.quantiles(timings, n=20)[18]
    assert p95 < 300, f"search p95 {p95:.1f} ms"


def _transcript(env, title_id, cues):
    with env["factory"]() as s:
        s.add(OttAiOutput(title_id=title_id, kind="transcript", language="en", status="done",
                          data={"cues": [[a, b, t] for a, b, t in cues]}))
        s.commit()


LESSON = [(0, 8, "Welcome to the kitchen."), (8, 20, "Today we bake bread."),
          (40, 55, "Mix flour and water."), (70, 90, "Let the dough rest for an hour."),
          (95, 120, "Bake at 230 degrees until golden.")]


def test_ask_this_video_cites_a_time_from_the_excerpts(env, monkeypatch):
    monkeypatch.setattr(asking, "_default_llm", lambda prompt: "Rest the dough for an hour [01:10].")
    _transcript(env, env["ids"][0], LESSON)
    res = env["client"].post(f"/api/v1/ott/titles/{env['ids'][0]}/ask", json={"question": "How long does it rest?"})
    data = res.json()["data"]
    assert data["answer"] == "Rest the dough for an hour [01:10]."
    assert data["citations"][0]["start_s"] == 70 and "rest" in data["citations"][0]["text"]


def test_ask_says_it_does_not_know_instead_of_guessing(env, monkeypatch):
    _transcript(env, env["ids"][0], LESSON)
    for reply in ("Probably 2 hours.", "It rests for an hour [09:59].", "I do not know from this video."):
        monkeypatch.setattr(asking, "_default_llm", lambda prompt, r=reply: r)
        data = env["client"].post(f"/api/v1/ott/titles/{env['ids'][0]}/ask",
                                  json={"question": "What oven brand?"}).json()["data"]
        assert data == {"answer": asking.DONT_KNOW, "citations": []}
    none = env["client"].post(f"/api/v1/ott/titles/{env['ids'][1]}/ask", json={"question": "Anything?"}).json()["data"]
    assert none["answer"] == asking.DONT_KNOW


def test_discovery_routes_404_until_the_flag(env, monkeypatch):
    monkeypatch.delenv("OTT_DISCOVERY_LIVE")
    assert env["client"].get("/api/v1/ott/search?q=bread").status_code == 404


def test_search_hides_a_title_blocked_by_its_own_id(env):
    from app.domains.compliance.takedown import STATUS_BLOCKED, TakedownReport

    with env["factory"]() as s:
        title = s.get(OttTitle, env["ids"][0])
        title.title = "Sourdough basics"
        s.commit()
        search.reindex(s, embedder=HashingEmbedder())
        s.commit()
    assert env["client"].get("/api/v1/ott/search?q=sourdough").json()["data"]["results"]
    with env["factory"]() as s:
        s.add(TakedownReport(job_id=env["ids"][0], content_ref=env["ids"][0], status=STATUS_BLOCKED, reason="other",
                             reporter_email="r@example.com", details="x"))
        s.commit()
    search.reset_cache()
    assert env["client"].get("/api/v1/ott/search?q=sourdough").json()["data"]["results"] == []
