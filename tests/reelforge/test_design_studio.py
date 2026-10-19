"""Design Studio (M-1): layouts, copy rules, canvas validation and the generate -> export -> schedule flow.

In-memory SQLite; R2, the logo fetch, the LLM and the media gateway are faked.
"""

from __future__ import annotations

import base64
import hashlib
import io
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.approvals import service as approvals_service
from app.domains.design import canvas as canvas_mod
from app.domains.design import layouts, service
from app.domains.design.copy import design_copy, rule_copy
from app.domains.design.models import SIZE_PRESETS, DesignDoc
from app.models.db.base import Base
from app.models.db.models import Asset, User, UserPreset


def _png(w: int, h: int, color=(10, 20, 30, 255)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(out, format="PNG")
    return out.getvalue()


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
    monkeypatch.setattr(service, "get_session", _session)
    monkeypatch.setattr(approvals_service, "get_session", _session)
    monkeypatch.setattr(service, "_upload", lambda key, data, ctype: store.__setitem__(key, data))
    monkeypatch.setattr(service, "_download", lambda key: store[key])
    monkeypatch.setattr(service, "_fetch_remote", lambda url: _png(200, 80))  # never touch the network
    monkeypatch.setattr(service, "_presign", lambda key, download_name=None: f"https://r2.test/{key}" if key else None)
    with _session() as s:
        user = User(email="d@example.com", api_key_hash=hashlib.sha256(b"d").hexdigest(), credits=0)
        other = User(email="x@example.com", api_key_hash=hashlib.sha256(b"x").hexdigest(), credits=0)
        s.add_all([user, other])
        s.flush()
        kit = UserPreset(user_id=user.id, name="Acme kit", config={"brand": {
            "name": "Acme", "tagline": "Tools that last", "logo_url": "https://acme.test/logo.png",
            "colors": ["#1d4ed8", "#f97316", "#ffffff", "#0b1020"], "fonts": ["Poppins", "Inter"]}})
        s.add(kit)
        s.flush()
        ids = SimpleNamespace(user=user.id, other=other.id, kit=kit.id)
    return SimpleNamespace(session=_session, store=store, ids=ids)


# --------------------------------------------------------------------------- #
# Pure pieces
# --------------------------------------------------------------------------- #
def test_every_template_builds_valid_canvas_for_every_size():
    style = layouts.BrandStyle(name="Acme", logo_key="uploads/logo.png")
    copy = layouts.Copy(headline="Ship faster with Acme", subline="Built for small teams", cta="Try it",
                        badge="20% off", points=("One", "Two", "Three"))
    for preset, (w, h) in SIZE_PRESETS.items():
        for template in layouts.templates_for(preset):
            doc = layouts.build(template.slug, w, h, copy, style)
            clean = canvas_mod.sanitize(doc)
            assert clean["pages"] and all(p["layers"] for p in clean["pages"])
            for page in clean["pages"]:
                for layer in page["layers"]:
                    assert layer["x"] >= -1 and layer["x"] + layer["width"] <= w + 2, (preset, template.slug, layer)


def test_ink_picks_readable_text_colour():
    style = layouts.BrandStyle()
    assert layouts.ink_on("#ffffff", style) == style.dark
    assert layouts.ink_on("#000000", style) == style.light


def test_rule_copy_uses_only_the_prompt_and_brand():
    copy = rule_copy("New habit tracker app. Download it on iOS. Streaks and reminders.", {"tagline": "Build habits"})
    assert copy.headline == "New habit tracker app"
    assert copy.cta == "Download the app"
    assert copy.badge.lower() == "new"
    assert "Streaks and reminders" in copy.points


def test_llm_copy_rejects_invented_numbers_and_emoji():
    raw = '{"headline": "Save 50% today", "subline": "Loved by teams \U0001F680", "cta": "Shop now", "points": ["4.9 stars"]}'
    copy, source = design_copy("Spring sale on garden tools", {}, "square", generate=lambda _p: raw)
    assert source == "rules"  # headline had an invented number -> rules headline kept
    assert "50" not in copy.headline and "4.9" not in " ".join(copy.points)
    ok, source = design_copy("Spring sale: 30% off garden tools", {}, "square",
                             generate=lambda _p: '{"headline": "30% off garden tools", "subline": "Loved by teams \U0001F680"}')
    assert source == "llm" and ok.headline == "30% off garden tools" and "\U0001F680" not in ok.subline


def test_sanitize_rejects_urls_in_image_layers_and_clamps():
    bad = {"pages": [{"layers": [{"type": "image", "props": {"key": "https://evil.test/x.png"}}]}]}
    with pytest.raises(canvas_mod.CanvasError):
        canvas_mod.sanitize(bad)
    clean = canvas_mod.sanitize({"pages": [{"background": "red", "layers": [
        {"type": "text", "x": "nan", "width": 1e9, "props": {"text": "x" * 5000, "color": "#abc", "fontFamily": "<b>"}},
        {"type": "script"} if False else {"type": "rect", "props": {"fill": "transparent"}},
    ]}]})
    text = clean["pages"][0]["layers"][0]
    assert clean["pages"][0]["background"] == "#ffffff"
    assert len(text["props"]["text"]) == canvas_mod.MAX_TEXT and text["props"]["color"] == "#aabbcc"
    assert text["props"]["fontFamily"] == "Inter" and text["width"] == canvas_mod.MAX_COORD
    with pytest.raises(canvas_mod.CanvasError):
        canvas_mod.sanitize({"pages": [{"layers": [{"type": "script"}]}]})


def test_style_from_brand_maps_colours_and_fonts():
    style = service.style_from_brand({"colors": ["#1d4ed8", "#f97316", "#ffffff", "#0b1020"],
                                      "fonts": ["Poppins", "Inter"]})
    assert style.primary == "#1d4ed8" and style.accent == "#f97316"
    assert style.light == "#ffffff" and style.dark == "#0b1020"
    assert (style.heading_font, style.body_font) == ("Poppins", "Inter")


# --------------------------------------------------------------------------- #
# End to end: generate -> create -> edit -> export -> schedule
# --------------------------------------------------------------------------- #
def test_generate_edit_export_schedule(db):
    fetched: list[str] = []

    def fetch(url):
        fetched.append(url)
        return _png(300, 120)

    gen = service.generate(db.ids.user, prompt="Launch week for Acme drills. Order before Friday.",
                           size_preset="square", brand_kit_id=db.ids.kit, use_llm=False, fetch=fetch)
    assert len(gen["options"]) == 4 and gen["copy_source"] == "rules"
    assert gen["brand"]["colors"]["primary"] == "#1d4ed8" and gen["brand"]["fonts"]["heading"] == "Poppins"
    logo_key = gen["brand"]["logo_key"]
    assert logo_key and logo_key in db.store
    first = gen["options"][0]["canvas"]
    assert first["pages"][0]["background"] == "#1d4ed8"
    fonts = canvas_mod.fonts_used(canvas_mod.sanitize(first))
    assert "Poppins" in fonts

    # The logo is imported once and reused.
    service.generate(db.ids.user, prompt="Another post for Acme", size_preset="story", brand_kit_id=db.ids.kit,
                     use_llm=False, fetch=fetch)
    assert fetched == ["https://acme.test/logo.png"]

    doc = service.create_doc(db.ids.user, title="Launch", size_preset="square", canvas=first,
                             template=gen["options"][0]["template"], brand_kit_id=db.ids.kit, prompt="x")
    assert doc["status"] == "draft" and doc["page_count"] == 1

    # Edit: move the headline, add an uploaded image.
    up = service.upload_image(db.ids.user, "data:image/png;base64," + base64.b64encode(_png(64, 64)).decode())
    canvas = doc["canvas"]
    canvas["pages"][0]["layers"].append({"id": "img1", "type": "image", "x": 10, "y": 10, "width": 64,
                                         "height": 64, "props": {"key": up["key"], "fit": "cover"}})
    saved = service.update_doc(db.ids.user, doc["id"], title="Launch v2", canvas=canvas)
    assert saved["title"] == "Launch v2" and len(saved["canvas"]["pages"][0]["layers"]) == len(canvas["pages"][0]["layers"])
    data, ctype = service.media(db.ids.user, up["key"])
    assert ctype == "image/png" and data == db.store[up["key"]]

    # Wrong size is refused; the right one is stored as an owned asset.
    with pytest.raises(service.DesignError):
        service.export(db.ids.user, doc["id"], [base64.b64encode(_png(100, 100)).decode()])
    exported = service.export(db.ids.user, doc["id"], [base64.b64encode(_png(1080, 1080)).decode()])
    assert exported["status"] == "exported" and len(exported["exports"]) == 1
    key = exported["exports"][0]["key"]
    with db.session() as s:
        assert s.query(Asset).filter(Asset.r2_key == key, Asset.user_id == db.ids.user).count() == 1

    out = service.schedule(db.ids.user, doc["id"], platforms=["instagram", "linkedin"], caption="Launch week",
                           scheduled_at=datetime.now(timezone.utc) + timedelta(days=1))
    assert out["design"]["status"] == "scheduled"
    assert out["approval"]["source"] == "design_publish" and out["approval"]["payload"]["image_keys"] == [key]
    again = service.schedule(db.ids.user, doc["id"], platforms=["instagram"], caption="Launch week v2")
    assert again["approval"]["id"] == out["approval"]["id"]


def test_owner_scoping_and_foreign_images(db):
    gen = service.generate(db.ids.user, prompt="Summer sale on shoes", size_preset="landscape", use_llm=False,
                           fetch=lambda _u: _png(10, 10))
    doc = service.create_doc(db.ids.user, title="", size_preset="landscape", canvas=gen["options"][1]["canvas"])
    with pytest.raises(service.DesignError) as exc:
        service.get_doc(db.ids.other, doc["id"])
    assert exc.value.status_code == 404
    foreign = service.upload_image(db.ids.other, base64.b64encode(_png(8, 8)).decode())
    canvas = doc["canvas"]
    canvas["pages"][0]["layers"].append({"type": "image", "props": {"key": foreign["key"]}})
    with pytest.raises(service.DesignError) as exc:
        service.update_doc(db.ids.user, doc["id"], canvas=canvas)
    assert exc.value.status_code == 403
    with pytest.raises(service.DesignError):
        service.media(db.ids.user, foreign["key"])
    with pytest.raises(service.DesignError) as exc:
        service.generate(db.ids.other, prompt="hello there", size_preset="square", brand_kit_id=db.ids.kit)
    assert exc.value.status_code == 404
    with pytest.raises(service.DesignError):
        service.schedule(db.ids.user, doc["id"], platforms=["instagram"])  # not exported yet


def test_ai_image_is_metered_through_the_gateway(db):
    gen = service.generate(db.ids.user, prompt="Coffee shop opening", size_preset="square", use_llm=False)
    doc = service.create_doc(db.ids.user, title="Cafe", size_preset="square", canvas=gen["options"][0]["canvas"])
    calls = []

    def create(session, *, user_id, model, prompt):
        calls.append((user_id, prompt))
        return {"id": "gen1", "model": "img-1", "url": "https://cdn.test/a.png", "cost_micros": 40_000}

    out = service.ai_image(db.ids.user, doc["id"], prompt="latte art on a wooden table", create=create,
                           fetch=lambda _u: _png(512, 512))
    assert calls == [(db.ids.user, "latte art on a wooden table")]
    assert out["cost_micros"] == 40_000 and out["key"] in db.store
    with db.session() as s:
        assert s.get(DesignDoc, doc["id"]).used_ai_image is True


def test_templates_and_saved_template(db):
    listing = service.list_templates(db.ids.user)
    assert {s["id"] for s in listing["sizes"]} >= {"square", "story", "landscape", "carousel", "app_store"}
    gen = service.generate(db.ids.user, prompt="Five tips for better sleep. Keep a schedule. Dim the lights.",
                           size_preset="carousel", use_llm=False)
    assert gen["options"][0]["template"] == "carousel-story" and len(gen["options"][0]["canvas"]["pages"]) >= 3
    doc = service.create_doc(db.ids.user, title="Sleep", size_preset="carousel", canvas=gen["options"][0]["canvas"])
    tpl = service.save_template(db.ids.user, doc["id"], name="My carousel")
    from_tpl = service.create_doc(db.ids.user, title="From template", size_preset="carousel", canvas=None,
                                  template_id=tpl["id"])
    assert from_tpl["page_count"] == doc["page_count"]
    assert any(t["id"] == tpl["id"] for t in service.list_templates(db.ids.user)["templates"])
    with pytest.raises(service.DesignError):
        service.create_doc(db.ids.other, title="", size_preset="carousel", canvas=None, template_id=tpl["id"])
