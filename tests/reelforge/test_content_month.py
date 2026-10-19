"""Content Month: website -> ~30 viral-format ideas -> swipe -> carousels (PNG/PDF/MP4) and reel jobs.

Pure pieces (formats, brief, rules, LLM validation, slides, raster) plus the
service flow on in-memory SQLite with R2, the site fetch, the logo fetch and
FFmpeg faked (one real FFmpeg run when the binary exists).
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.content_month import brief as br
from app.domains.content_month import formats as fm
from app.domains.content_month import ideas, raster, reel, rules, service, slides
from app.domains.content_month.models import ContentIdea
from app.domains.design import canvas as canvas_mod
from app.domains.design import service as design_service
from app.domains.design.layouts import BrandStyle
from app.domains.design.models import DesignDoc
from app.models.db.base import Base
from app.models.db.models import Asset, Job, User

ANALYSIS = {
    "name": "Acme Backend",
    "website_url": "https://acme.test/",
    "one_liner": "Postgres, Auth and Storage live in one minute, $25 a project.",
    "headings": ["Tell your agent. Get a backend.", "One flat price", "1. Paste one line", "2. Keys land in your app"],
    "sample_lines": ["For small teams, agencies and founders. Plans from $25 a month.", "Sign in"],
    "features": ["Postgres with branching", "Auth with Google and Apple", "Storage and Realtime"],
    "pricing_hook": "$25 a project",
    "category": "Developer tools: backend platform",
    "colors": [{"hex": "#3d3f9e", "origin": "css-variable"}, {"hex": "#e0794d", "origin": "css-variable"}],
    "fonts": [{"family": "Instrument Sans", "origin": "stylesheet"}],
    "logo": {"url": "https://acme.test/logo.png", "origin": "json-ld"},
    "language": "en",
}


def _png(w: int, h: int, color=(10, 20, 30, 255)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture()
def brief() -> br.SiteBrief:
    return br.from_analysis(ANALYSIS)


# --------------------------------------------------------------------------- #
# Formats + brief
# --------------------------------------------------------------------------- #
def test_rotation_mixes_carousels_and_reels_without_repeats():
    slots = fm.rotation(30)
    assert len(slots) == 30
    kinds = [s.kind for s in slots]
    assert kinds.count(fm.KIND_CAROUSEL) == 18 and kinds.count(fm.KIND_REEL) == 12
    assert all(a.id != b.id for a, b in zip(slots, slots[1:]))
    assert len({s.id for s in slots}) == len(fm.FORMATS)
    assert {f["id"] for f in fm.catalog()} == set(fm.BY_ID)


def test_brief_reads_audience_numbers_and_brand(brief):
    assert brief.name == "Acme Backend" and brief.domain == "acme.test"
    assert brief.audience == "small teams, agencies and founders"
    assert "25" in brief.allowed_numbers
    assert "Sign in" not in brief.value_lines
    assert brief.colors == ("#3d3f9e", "#e0794d") and brief.fonts == ("Instrument Sans",)
    assert brief.logo_url == "https://acme.test/logo.png"
    assert brief.brand()["colors"] == ["#3d3f9e", "#e0794d"]


def test_brief_ignores_non_audience_for_phrases():
    data = {**ANALYSIS, "one_liner": "Built for agents.", "sample_lines": ["For agents and robots."]}
    assert br.from_analysis(data).audience == "developers"


# --------------------------------------------------------------------------- #
# Rules + LLM
# --------------------------------------------------------------------------- #
def test_rule_month_has_unique_hooks_and_no_invented_numbers(brief):
    month = ideas.month_ideas(brief, use_llm=False)
    assert len(month) >= 28
    hooks = [i["hook"].lower() for i in month]
    assert len(hooks) == len(set(hooks))
    allowed = set(brief.allowed_numbers) | ideas.LIST_COUNTS
    for idea in month:
        assert idea["source"] == "rules"
        assert idea["slides"][0] == idea["hook"] and len(idea["slides"]) >= 3
        assert br.numbers_in(" ".join(idea["slides"]) + idea["caption"]) <= allowed, idea
        assert (idea["script"] != "") == (idea["kind"] == fm.KIND_REEL)


def test_validate_rejects_invented_numbers_and_strips_emoji(brief):
    fmt = fm.BY_ID["checklist"]
    bad = {"hook": "Save this", "slides": ["Save this", "Used by 10000 teams", "Try acme.test"]}
    assert ideas.validate(bad, fmt, brief) is None
    good = {"hook": "Save this \U0001F680", "slides": ["Ship in 3 steps", "Only $25 a project", "Try acme.test"],
            "caption": "Rated 4.9 by everyone"}
    idea = ideas.validate(good, fmt, brief)
    assert idea is not None and idea["hook"] == "Save this" and idea["slides"][0] == "Save this"
    assert "4.9" not in idea["caption"] and idea["source"] == "llm"
    md = ideas.validate({"hook": "**Ship** it", "slides": ["x", "Run `npx acme init`", "Try acme.test"]}, fmt, brief)
    assert md["hook"] == "Ship it" and md["slides"][2] == "Run npx acme init"


def test_month_ideas_uses_llm_where_valid_and_rules_elsewhere(brief):
    def generate(prompt: str) -> str:
        assert "Never invent numbers" in prompt and "acme.test" in prompt
        slots = json.loads(prompt.split("Write one post per slot (JSON): ")[1].split("\nRules:")[0])
        posts = []
        for slot in slots:
            if slot["slot"] % 2 == 0:
                posts.append({"slot": slot["slot"], "hook": f"LLM hook {slot['format']} {len(posts)}",
                              "slides": ["a", "Fast backend for small teams", "Try acme.test"]})
            else:
                posts.append({"slot": slot["slot"], "hook": "Loved by 99999 devs", "slides": ["x", "y", "z"]})
        return json.dumps({"posts": posts})

    month = ideas.month_ideas(brief, generate=generate)
    sources = {i["source"] for i in month}
    assert sources == {"llm", "rules"}
    assert not any("99999" in i["hook"] for i in month)


def test_month_ideas_falls_back_when_llm_errors_or_hangs(brief):
    assert all(i["source"] == "rules" for i in ideas.month_ideas(brief, generate=lambda p: "Error: no key"))

    def boom(prompt: str) -> str:
        raise RuntimeError("provider down")

    assert len(ideas.month_ideas(brief, count=10, generate=boom)) == 10


def test_reel_job_is_a_valid_captions_only_request():
    job = reel.reel_job("abc", "Hook", "Script text.", "en", 3)
    params = job["body"]["params"]
    assert job["idempotency_key"] == "month-abc"
    assert params["layout"] == "captions_only" and params["aspect"] == "9:16"
    assert params["video_script"] == "Script text." and params["background_id"] in reel.BACKGROUNDS


# --------------------------------------------------------------------------- #
# Slides + raster
# --------------------------------------------------------------------------- #
def test_deck_is_a_valid_design_canvas_for_both_sizes(brief):
    style = BrandStyle(name="Acme", logo_key="uploads/logo.png")
    texts = rules.rule_idea(fm.BY_ID["checklist"], brief, 0)["slides"]
    for size, (_preset, w, h) in slides.SIZES.items():
        clean = canvas_mod.sanitize(slides.deck(texts, style, size))
        assert len(clean["pages"]) == len(texts)
        for page in clean["pages"]:
            for layer in page["layers"]:
                assert -1 <= layer["x"] and layer["x"] + layer["width"] <= w + 2, (size, layer)
                assert -1 <= layer["y"] and layer["y"] + layer["height"] <= h + 2, (size, layer)
    with pytest.raises(ValueError):
        slides.deck(texts, style, "billboard")


def test_raster_renders_pages_pdf_and_video_args():
    style = BrandStyle(name="Acme", logo_key="uploads/logo.png")
    canvas = slides.deck(["A hook that stops the scroll", "Point one", "Try acme.test"], style, "instagram")
    pngs = raster.render_pages(canvas, 1080, 1350, load_image=lambda key: _png(120, 40))
    assert len(pngs) == 3
    assert Image.open(io.BytesIO(pngs[0])).size == (1080, 1350)
    cover = Image.open(io.BytesIO(pngs[0])).convert("RGB")
    assert len(set(cover.getdata())) > 2  # text and shapes were drawn
    assert raster.to_pdf(pngs).startswith(b"%PDF")
    args = raster.slideshow_args(["a.png", "b.png"], 1080, 1350, "out.mp4")
    assert args.count("-i") == 2 and "xfade" in args[args.index("-filter_complex") + 1]
    with pytest.raises(raster.RasterError):
        raster.to_pdf([])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_slideshow():
    data = raster.to_mp4([_png(216, 384, (200, 30, 30, 255)), _png(216, 384, (30, 30, 200, 255))], 216, 384)
    assert data[4:8] == b"ftyp" and len(data) > 1000


# --------------------------------------------------------------------------- #
# Service flow
# --------------------------------------------------------------------------- #
@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        session = Factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    store: dict[str, bytes] = {}
    for mod in (service, design_service):
        monkeypatch.setattr(mod, "get_session", _session)
    monkeypatch.setattr(design_service, "_upload", lambda key, data, ctype: store.__setitem__(key, data))
    monkeypatch.setattr(design_service, "_download", lambda key: store[key])
    monkeypatch.setattr(design_service, "_fetch_remote", lambda url: _png(200, 80))
    monkeypatch.setattr(design_service, "_presign",
                        lambda key, download_name=None: f"https://r2.test/{key}" if key else None)
    with _session() as s:
        user = User(email="m@example.com", api_key_hash=hashlib.sha256(b"m").hexdigest(), credits=0)
        other = User(email="o@example.com", api_key_hash=hashlib.sha256(b"o").hexdigest(), credits=0)
        s.add_all([user, other])
        s.flush()
        ids = SimpleNamespace(user=user.id, other=other.id)
    return SimpleNamespace(session=_session, store=store, ids=ids)


def _plan(db, count: int = 30) -> dict:
    return service.create_plan(db.ids.user, "acme.test", count=count, use_llm=False, analyze=lambda url: ANALYSIS)


def test_create_plan_stores_ideas_style_and_logo(db):
    plan = _plan(db)
    assert plan["name"] == "Acme Backend" and plan["counts"]["pending"] == len(plan["ideas"]) >= 28
    assert plan["style"]["logo_key"].startswith("uploads/") and plan["style"]["logo_key"] in db.store
    first = plan["ideas"][0]
    assert first["preview"]["width"] == 1080 and first["preview"]["page"]["layers"]
    reels = [i for i in plan["ideas"] if i["kind"] == "reel"]
    assert reels and all(i["reel_job"]["body"]["params"]["video_script"] for i in reels)
    assert service.list_plans(db.ids.user)["plans"][0]["id"] == plan["id"]
    assert service.list_plans(db.ids.other)["plans"] == []
    with pytest.raises(service.MonthError) as err:
        service.get_plan(db.ids.other, plan["id"])
    assert err.value.status_code == 404


def test_bad_url_and_blocked_site_are_clear_errors(db):
    with pytest.raises(service.MonthError):
        service.create_plan(db.ids.user, "not a url", use_llm=False, analyze=lambda u: ANALYSIS)

    def blocked(url):
        raise service.MonthError("the website blocked the automated visit", status_code=424)

    with pytest.raises(service.MonthError) as err:
        service.create_plan(db.ids.user, "acme.test", use_llm=False, analyze=blocked)
    assert err.value.status_code == 424


def _fake_mp4(pngs, w, h):
    return b"\x00\x00\x00\x18ftypmp42" + b"0" * 64


def test_swipe_render_carousel_pdf_then_worker_video(db):
    from app.domains.content_month import video

    plan = _plan(db, count=10)
    carousel = next(i for i in plan["ideas"] if i["kind"] == "carousel")
    with pytest.raises(service.MonthError):
        service.render_carousel(db.ids.user, carousel["id"])  # not kept yet
    out = service.decide(db.ids.user, carousel["id"], "kept")
    assert out["idea"]["decision"] == "kept" and out["counts"]["kept"] == 1
    queued: list[tuple[str, str]] = []
    made = service.render_carousel(db.ids.user, carousel["id"], size="instagram",
                                   enqueue=lambda u, i: queued.append((u, i)))
    outputs = made["idea"]["outputs"]
    assert queued == [(db.ids.user, carousel["id"])]
    assert made["idea"]["render_status"] == "done" and outputs["video_status"] == "queued"
    assert "stem" not in outputs and outputs["mp4_url"] is None
    assert len(outputs["png_keys"]) == len(carousel["slides"])
    assert db.store[outputs["pdf_key"]].startswith(b"%PDF") and outputs["pdf_url"].startswith("https://r2.test/")
    # The render worker builds the video from the stored slides.
    assert video.build_video(db.ids.user, carousel["id"], to_mp4=_fake_mp4) == "done"
    ready = service.get_idea(db.ids.user, carousel["id"])["idea"]["outputs"]
    assert ready["video_status"] == "done" and ready["mp4_url"] and ready["mp4_key"] in db.store
    with db.session() as s:
        doc = s.get(DesignDoc, outputs["design_id"])
        assert doc.user_id == db.ids.user and doc.status == "exported" and doc.size_preset == "portrait"
        kinds = {a.kind for a in s.query(Asset).filter(Asset.user_id == db.ids.user)}
        assert {"image", "document", "video"} <= kinds
    with pytest.raises(service.MonthError) as err:
        service.render_carousel(db.ids.other, carousel["id"])
    assert err.value.status_code == 404


def test_video_failures_are_shown_and_retryable(db):
    from datetime import datetime, timedelta, timezone

    from app.domains.content_month import video

    plan = _plan(db, count=5)
    carousel = next(i for i in plan["ideas"] if i["kind"] == "carousel")
    service.decide(db.ids.user, carousel["id"], "kept")

    def broker_down(user_id, idea_id):
        raise ConnectionError("redis down")

    made = service.render_carousel(db.ids.user, carousel["id"], enqueue=broker_down)
    assert made["idea"]["render_status"] == "done" and made["idea"]["outputs"]["png_keys"]
    assert made["idea"]["outputs"]["video_status"] == "failed"

    def broken(pngs, w, h):
        raise raster.RasterError("ffmpeg missing")

    service.retry_video(db.ids.user, carousel["id"], enqueue=lambda u, i: None)
    assert video.build_video(db.ids.user, carousel["id"], to_mp4=broken) == "failed"
    failed = service.get_idea(db.ids.user, carousel["id"])["idea"]["outputs"]
    assert failed["video_status"] == "failed" and "try again" in failed["video_error"]
    again = service.retry_video(db.ids.user, carousel["id"], enqueue=lambda u, i: None)
    assert again["idea"]["outputs"]["video_status"] == "queued"
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert video.effective_status({"video_status": "rendering", "video_started_at": old}) == "failed"
    assert video.effective_status({"video_status": "rendering",
                                   "video_started_at": datetime.now(timezone.utc).isoformat()}) == "rendering"
    reel_idea = next(i for i in plan["ideas"] if i["kind"] == "reel")
    with pytest.raises(service.MonthError):
        service.retry_video(db.ids.user, reel_idea["id"])


def test_reel_idea_links_only_the_callers_job(db):
    plan = _plan(db, count=5)
    reel_idea = next(i for i in plan["ideas"] if i["kind"] == "reel")
    with pytest.raises(service.MonthError):
        service.render_carousel(db.ids.user, reel_idea["id"])
    with db.session() as s:
        mine = Job(user_id=db.ids.user, kind="reel", params={})
        theirs = Job(user_id=db.ids.other, kind="reel", params={})
        s.add_all([mine, theirs])
        s.flush()
        mine_id, theirs_id = mine.id, theirs.id
    with pytest.raises(service.MonthError) as err:
        service.attach_job(db.ids.user, reel_idea["id"], theirs_id)
    assert err.value.status_code == 404
    out = service.attach_job(db.ids.user, reel_idea["id"], mine_id)
    assert out["idea"]["render_status"] == "queued" and out["idea"]["outputs"]["job_id"] == mine_id
    assert out["idea"]["decision"] == "kept"


def test_edit_idea_updates_hook_slides_and_script(db):
    plan = _plan(db, count=5)
    reel_idea = next(i for i in plan["ideas"] if i["kind"] == "reel")
    out = service.edit_idea(db.ids.user, reel_idea["id"], hook="A sharper hook \U0001F680",
                            slides_in=["old", "Second beat", "Try acme.test"], caption="New caption")
    idea = out["idea"]
    assert idea["hook"].startswith("A sharper hook") and idea["slides"][0] == idea["hook"]
    assert "Second beat" in idea["script"] and idea["caption"] == "New caption"
    with pytest.raises(service.MonthError):
        service.edit_idea(db.ids.user, reel_idea["id"], slides_in=["only one"])
    with pytest.raises(service.MonthError):
        service.decide(db.ids.user, reel_idea["id"], "maybe")


def test_delete_plan_removes_ideas(db):
    plan = _plan(db, count=5)
    assert service.delete_plan(db.ids.user, plan["id"]) == {"deleted": True}
    with db.session() as s:
        assert s.query(ContentIdea).filter(ContentIdea.plan_id == plan["id"]).count() == 0


def test_cli_writes_ideas_and_rendered_carousels(tmp_path, monkeypatch):
    from app.domains.brand_agent import site_analysis
    from app.domains.content_month import __main__ as cli

    monkeypatch.setattr(site_analysis, "analyze_site", lambda url: ANALYSIS)
    monkeypatch.setattr(cli, "_logo", lambda brief: _png(120, 40))
    assert cli.main(["run", "acme.test", "--out", str(tmp_path), "--render", "2", "--no-video", "--no-llm"]) == 0
    site = tmp_path / "acme.test"
    data = json.loads((site / "ideas.json").read_text())
    assert len(data["ideas"]) >= 28 and data["site"]["name"] == "Acme Backend"
    folders = [p for p in site.iterdir() if p.is_dir()]
    assert len(folders) == 2
    for folder in folders:
        assert (folder / "slide-01.png").exists() and (folder / "carousel.pdf").exists()
    assert any("reel_job" in i for i in data["ideas"])


def test_default_analyze_maps_site_errors(monkeypatch):
    from app.domains.brand_agent import site_analysis

    def blocked(url):
        raise site_analysis.SiteAnalysisError("the website blocked the automated visit", 424)

    monkeypatch.setattr(site_analysis, "analyze_site", blocked)
    with pytest.raises(service.MonthError) as err:
        service._default_analyze("https://acme.test")
    assert err.value.status_code == 424 and "blocked" in str(err.value)


def test_truncated_llm_reply_keeps_complete_posts_and_drops_bad_slides(brief):
    good = {"slot": 0, "hook": "Hook one", "slides": ["Hook one", "Used by 5000 teams", "Point", "Try acme.test"]}
    second = {"slot": 1, "hook": "Hook two", "slides": ["Hook two", "x", "y"]}
    raw = '{"posts": [' + json.dumps(good) + ", " + json.dumps(second) + ', {"slot": 2, "hook": "cut of'
    posts = ideas.parse_posts(raw)
    assert [p["slot"] for p in posts] == [0, 1]
    idea = ideas.validate(posts[0], fm.BY_ID["checklist"], brief)
    assert idea is not None and not any("5000" in s for s in idea["slides"]) and len(idea["slides"]) == 3
