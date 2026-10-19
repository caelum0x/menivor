"""Megaphone: weekly in-house marketing videos made through Menivor's public API."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from app.domains.megaphone import briefs as bf
from app.domains.megaphone import codeclip, endcard
from app.domains.megaphone import manifest as mf
from app.domains.megaphone import pipeline as pl

DAY = date(2026, 10, 8)  # ISO week 41
NOW = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)

ROWS = [
    {"country": "DE", "div": "45", "n": 412, "label": "Construction work",
     "buyers": ["DB InfraGO AG – Geschäftsbereich Fahrweg (Bukr 16)", "Stadt Köln, Amt 20"]},
    {"country": "FR", "div": "71", "n": 120, "label": "Architectural, construction, engineering and inspection services",
     "buyers": ["Ville de Lyon"]},
    {"country": "PL", "div": "33", "n": 300, "label": "Medical equipments", "buyers": []},
    {"country": "XX", "div": "45", "n": 999, "label": "Bad country", "buyers": []},
    {"country": "ES", "div": "4x", "n": 50, "label": "Bad code", "buyers": []},
    {"country": "IT", "div": "90", "n": 3, "label": "Too few", "buyers": []},
]
PATHS = {"/tenders/de/cpv-45000000", "/tenders/fr/cpv-71000000", "/tenders/it/cpv-90000000"}


def test_week_id_and_utm():
    assert bf.week_id(DAY) == "2026w41"
    url = bf.with_utm("https://bidstage.app/tenders/de/cpv-45000000?x=1", campaign="megaphone-2026w41", content="v1")
    q = parse_qs(urlsplit(url).query)
    assert q["x"] == ["1"] and q["utm_source"] == ["menivor"] and q["utm_medium"] == ["video"]
    assert q["utm_campaign"] == ["megaphone-2026w41"] and q["utm_content"] == ["v1"]


def test_bidstage_candidates_need_a_live_page_and_rotate():
    cands = bf.bidstage_candidates(ROWS, PATHS, set(), DAY)
    assert [c["pair_id"] for c in cands] == ["bidstage-de-cpv45", "bidstage-fr-cpv71"]  # PL has no page, IT too few
    assert cands[0]["buyers"] == ["DB InfraGO AG", "Stadt Köln"]
    rotated = bf.bidstage_candidates(ROWS, PATHS, {"bidstage-de-cpv45"}, DAY)
    assert [c["pair_id"] for c in rotated] == ["bidstage-fr-cpv71"]


def test_category_name_matches_bidstage_rule():
    assert bf.category_name("Construction work") == "Construction work"
    assert bf.category_name("Medical equipments, pharmaceuticals and personal care products") == "Medical equipments"
    assert bf.category_name("IT services: consulting, software development, Internet and support") == "IT services"
    assert bf.category_name("Sewage, refuse, cleaning and environmental services") == "Sewage and refuse"
    assert bf._short_buyer("118 Szpital Wojskowy z Przychodnią Samodzielny Publiczny Zakład") == ""


def test_bidstage_brief_states_only_input_facts():
    brief = bf.bidstage_brief(bf.bidstage_candidates(ROWS, PATHS, set(), DAY)[0], DAY)
    assert brief.id == "bidstage-de-cpv45-2026w41"
    assert brief.product == "bidstage"
    assert brief.script.startswith("412 new public tenders for construction work were published in Germany this week.")
    assert "DB InfraGO AG and Stadt Köln" in brief.script
    assert brief.page_path == "/tenders/de/cpv-45000000"
    assert brief.capture_url == "https://bidstage.app/tenders/de/cpv-45000000"
    assert brief.landing_url.startswith("https://bidstage.app/tenders/de/cpv-45000000?utm_source=menivor")
    assert "Made with Menivor" in brief.description


@pytest.mark.parametrize("builder", [bf.mail_brief, bf.menivor_brief])
def test_fixed_briefs_are_weekly_and_clean(builder):
    brief = builder(DAY)
    assert brief.id.endswith("-2026w41")
    assert brief.script and len(brief.script) < 900
    assert "utm_campaign=megaphone-2026w41" in brief.landing_url
    for text in (brief.title, brief.script, brief.description):
        assert text.isascii()  # no emoji
        assert "indie" not in text.lower()


def test_mail_brief_uses_code_footage_and_menivor_dubs():
    assert bf.mail_brief(DAY).footage_builder == "codeclip"
    assert bf.mail_brief(DAY).page_path == "/mail"
    assert bf.menivor_brief(DAY).dub_to == "es"


def test_oxhan_brief_uses_given_footage():
    brief = bf.oxhan_brief(DAY, ["uploads/a.mp4", "uploads/b.mp4"])  # week 41 -> index 1
    assert brief.footage_keys == ("uploads/b.mp4",)
    assert brief.title == bf.OXHAN_SCRIPTS[1][0]
    assert bf.oxhan_brief(date(2026, 10, 12), ["uploads/a.mp4", "uploads/b.mp4"]).footage_keys == ("uploads/a.mp4",)
    assert "forty" in brief.script.lower() and "€" not in brief.script


def _entry(vid: str, product: str, when: str) -> dict:
    return {"id": vid, "product": product, "upload_date": when}


def test_manifest_upsert_replaces_sorts_and_prunes():
    old = {"videos": [_entry("a-2026w40", "mail", "2026-10-01T00:00:00Z"),
                      _entry("b-2026w40", "bidstage", "2026-10-01T00:00:00Z"),
                      _entry("bad", "unknown", "2026-10-01T00:00:00Z")]}
    new = mf.upsert(old, [_entry("a-2026w40", "mail", "2026-10-08T00:00:00Z")], NOW)
    assert [v["id"] for v in new["videos"]] == ["a-2026w40", "b-2026w40"]
    assert new["updated_at"] == "2026-10-08T06:00:00Z" and new["version"] == 1
    many = [_entry(f"m-{i:02d}-2026w41", "menivor", f"2026-10-{i + 1:02d}T00:00:00Z") for i in range(20)]
    pruned = mf.upsert(None, many, NOW)
    assert len(pruned["videos"]) == mf.KEEP_PER_PRODUCT
    assert pruned["videos"][0]["id"] == "m-19-2026w41"


def test_manifest_product_split_and_recent_ids():
    m = mf.upsert(None, [_entry("bidstage-de-cpv45-2026w41", "bidstage", "2026-10-08T00:00:00Z"),
                         _entry("mail-x-2026w41", "mail", "2026-10-08T00:00:00Z")], NOW)
    assert [v["id"] for v in mf.for_product(m, "mail")["videos"]] == ["mail-x-2026w41"]
    assert mf.recent_ids(m, "bidstage") == {"bidstage-de-cpv45"}


def test_manifest_entry_shape():
    brief = bf.menivor_brief(DAY)
    e = mf.entry(brief, video_url="https://media.menivor.com/megaphone/menivor/x.mp4",
                 poster_url="https://media.menivor.com/megaphone/menivor/x.jpg", duration_s=31.234,
                 uploaded_at=NOW, dubs=[{"language": "es", "video_url": "u"}])
    assert e["made_with"] == "Menivor" and e["made_with_url"] == bf.MENIVOR_GALLERY_URL
    assert e["duration_s"] == 31.23 and e["upload_date"] == "2026-10-08T06:00:00Z"
    assert e["transcript"] == brief.script and e["dubs"] == [{"language": "es", "video_url": "u"}]
    json.dumps(e)


def test_endcard_and_codeclip_commands_use_textfiles(tmp_path):
    cmd = endcard.build_command(endcard.CARDS["oxhan"], str(tmp_path / "c.mp4"), str(tmp_path))
    vf = cmd[cmd.index("-vf") + 1]
    assert "textfile=" in vf and "Oxhan" not in vf  # names never inline in the filter graph
    assert (tmp_path / "name.txt").read_text() == "Oxhan Atelier"
    assert (tmp_path / "tagline.txt").read_text() == "Made with Menivor"
    code = codeclip.build_command(str(tmp_path / "code.mp4"), str(tmp_path))
    assert "mail-api.scribase.com" not in code[code.index("-vf") + 1]
    assert any("mail-api.scribase.com" in p.read_text() for p in tmp_path.glob("l16_*.txt"))


class _Resp:
    def __init__(self, status: int, data: dict):
        self.status_code = status
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return {"status": self.status_code, "data": self._data}


class _Session:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, headers))
        return self.replies.pop(0)


def test_create_reel_sends_footage_outro_and_idempotency():
    session = _Session([_Resp(200, {"job_id": "j1"})])
    api = pl.ApiClient(api_key="k", base="https://api.test/api/v1", session=session, sleep=lambda s: None)
    assert api.create_reel(bf.menivor_brief(DAY), screen_key="uploads/s.mp4", outro_key="uploads/o.mp4") == "j1"
    method, url, body, headers = session.calls[0]
    assert (method, url) == ("POST", "https://api.test/api/v1/jobs")
    assert body["params"]["screen_recording_key"] == "uploads/s.mp4"
    assert body["params"]["broll_outro_key"] == "uploads/o.mp4"
    assert body["params"]["background_id"] == "" and body["params"]["layout"] == "captions_only"
    assert headers["Idempotency-Key"] == pl.idempotency_key(bf.menivor_brief(DAY))
    assert headers["Idempotency-Key"].startswith(f"megaphone-{bf.menivor_brief(DAY).id}-")
    assert headers["x-api-key"] == "k"


def test_wait_reel_requires_clean_result_and_retries_502():
    session = _Session([_Resp(502, {}), _Resp(200, {"state": 4}), _Resp(200, {"state": 1, "result_url": ""})])
    api = pl.ApiClient(api_key="k", base="https://api.test", session=session, sleep=lambda s: None)
    with pytest.raises(pl.MegaphoneError, match="no clean result"):
        api.wait_reel("j1")


def test_client_errors_are_not_retried():
    session = _Session([_Resp(402, {"detail": "insufficient credits"})])
    api = pl.ApiClient(api_key="k", base="https://api.test", session=session, sleep=lambda s: None)
    with pytest.raises(pl.MegaphoneError, match="402"):
        api.create_reel(bf.mail_brief(DAY))
    assert len(session.calls) == 1


def test_idempotency_key_changes_with_script_or_look(monkeypatch):
    brief = bf.mail_brief(DAY)
    first = pl.idempotency_key(brief)
    assert first == pl.idempotency_key(bf.mail_brief(DAY))
    monkeypatch.setattr(codeclip, "VERSION", codeclip.VERSION + 1)
    assert pl.idempotency_key(brief) != first


def test_codeclip_keeps_the_caption_band_clear(tmp_path):
    vf = codeclip.build_command(str(tmp_path / "c.mp4"), str(tmp_path))
    graph = vf[vf.index("-vf") + 1]
    ys = [int(part.split(":y=")[1].split(":")[0]) for part in graph.split(",") if "drawtext" in part]
    assert min(ys) >= 700  # captions sit in the top third (about y 300-560)
