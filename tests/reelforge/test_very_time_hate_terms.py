"""Curated slur / hate-symbol list in the Very ___ Time guard-rail (item 7)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.domains.film import hate_terms, very_time

ROOT = Path(__file__).resolve().parents[2]


def _inputs(**over):
    base = {"place_word": "Turkish", "ritual": "tea poured into a tulip glass", "line": "",
            "garment": "", "chest_text": ""}
    return {**base, **over}


def test_list_loads_with_licensed_sources():
    data = hate_terms.load()
    ldnoobw = data["sources"][0]
    assert ldnoobw["licence"] == "CC-BY-4.0" and len(ldnoobw["commit"]) == 40
    cats = hate_terms.by_category()
    assert {"ethnic_slurs", "homophobic_slurs", "hate_symbols"} <= set(cats)
    assert "swastika" in hate_terms.terms() and "kummelturke" in hate_terms.terms()
    assert len(hate_terms.terms()) == len(set(hate_terms.terms()))


def test_attribution_is_in_third_party_notices():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "LDNOOBW" in notices and "CC-BY-4.0" in notices


@pytest.mark.parametrize("field,text,term", [
    ("ritual", "drawing a swastika on the steam", "swastika"),
    ("ritual", "a Kümmeltürke joke at the kiosk", "kummelturke"),
    ("line", "Sieg Heil at breakfast", "sieg heil"),
    ("place_word", "Çingene", "cingene"),
    ("chest_text", "very 1488 time", "1488"),
    ("garment", "a shirt with a Hakenkreuz print", "hakenkreuz"),
    ("ritual", "the gavurlar next door", "gavur"),
])
def test_guard_blocks_curated_terms_in_every_field(field, text, term):
    assert term in very_time.guard(_inputs(**{field: text}))


@pytest.mark.parametrize("text", [
    "a raccoon steals simit", "black tea in a tulip glass", "cafe negro at dawn",
    "the steam goes poof", "a Hmong grandmother", "the iron cross stitch on a cushion",
])
def test_guard_does_not_refuse_ordinary_words(text):
    assert very_time.guard(_inputs(ritual=text)) == []


def test_refresh_tool_diffs_offline(tmp_path):
    spec = importlib.util.spec_from_file_location("refresh", ROOT / "apps/api/tools/moderation/refresh_hate_terms.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = hate_terms.load()
    kept = [t for g in data["categories"].values() for t in g.get("upstream", [])]
    (tmp_path / "en").write_text("\n".join([*kept, "newword"]), encoding="utf-8")
    (tmp_path / "tr").write_text("", encoding="utf-8")
    (tmp_path / "de").write_text("", encoding="utf-8")
    result = mod.diff(data, mod.upstream_terms(["en", "tr", "de"], tmp_path))
    assert result["gone_upstream"] == [] and "newword" in result["not_reviewed"]
    assert mod.main(["--offline", str(tmp_path)]) == 0
