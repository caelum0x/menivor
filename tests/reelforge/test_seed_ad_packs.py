"""Menivor ad packs: validator, honesty lint, exact request bodies and the idempotent seeder.

``apps/api/tools/ops/ad_packs.py`` mirrors API limits so pack files can be
checked without the app; the drift tests below fail if those mirrors diverge
from the app's constants, and the body tests validate generated requests
against the real pydantic request models.
"""

from __future__ import annotations

import copy
import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

OPS = Path(__file__).resolve().parents[2] / "apps" / "api" / "tools" / "ops"
sys.path.insert(0, str(OPS))

import ad_packs  # noqa: E402
import seed_ad_packs  # noqa: E402

REAL_PACKS = seed_ad_packs.DEFAULT_PACKS_DIR


def _concept(i: int, **over: Any) -> dict[str, Any]:
    concept = {
        "id": f"c{i}",
        "angle_kind": "demo",
        "angle_note": "note",
        "hook": f"Hook number {i}.",
        "pain": "A real pain.",
        "proof": "A real feature.",
        "offer": "",
        "cta": "See example.com.",
        "format": "captions_only",
        "platform": "tiktok",
        "aspect": "9:16",
        "studio_format": "showcase",
        "script": f"Hook number {i}.\nA real feature.\nSee example.com.",
    }
    concept.update(over)
    return concept


def _pack(**over: Any) -> dict[str, Any]:
    pack = {
        "schema": ad_packs.SCHEMA,
        "product_id": "demo-app",
        "product_name": "Demo App",
        "language": "en",
        "availability": {"web": "https://example.com", "app_store": None, "play_store": None},
        "facts": [{"claim": "Hooks 1 2 3 4 5 are placeholders; the grid is 8x8.", "source": "test"}],
        "captures": [{"kind": "website", "url": "https://example.com", "formats": ["9:16", "1:1"], "duration_s": 20}],
        "product": {"title": "Demo App", "brand": "Demo", "description": "A demo.", "bullets": ["One"], "images": []},
        "concepts": [_concept(i) for i in range(1, 6)],
    }
    pack.update(over)
    return pack


def _mutate(path: list[Any], value: Any) -> dict[str, Any]:
    pack = _pack()
    target: Any = pack
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return pack


def _as_pack(data: dict[str, Any]) -> ad_packs.AdPack:
    ad_packs.validate(data)
    return ad_packs.AdPack(path=Path("demo.json"), data=data)


# --------------------------------------------------------------------------- #
# validator
# --------------------------------------------------------------------------- #
def test_valid_pack_passes() -> None:
    ad_packs.validate(_pack())


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (["schema"], "v0", "schema"),
        (["product_id"], "Demo App", "slug"),
        (["language"], "de", "language"),
        (["concepts"], [_concept(1)], "exactly 5"),
        (["captures", 0, "kind"], "web_game", "web game capture was removed"),
        (["captures", 0, "formats"], ["4:5"], "unsupported aspect"),
        (["captures", 0, "duration_s"], 90, "10-45"),
        (["captures", 0, "url"], "https://apps.apple.com/us/app/x/id123456", "store links"),
        (["concepts", 0, "angle_kind"], "social_proof", "social_proof"),
        (["concepts", 0, "angle_kind"], "viral", "angle_kind"),
        (["concepts", 0, "format"], "avatar_reel", "free format"),
        (["concepts", 0, "platform"], "linkedin", "platform"),
        (["concepts", 0, "aspect"], "16:9", "not recorded by any capture"),
        (["concepts", 0, "studio_format"], "ugc_avatar", "studio_format"),
        (["concepts", 0, "hook"], "x" * 221, "longer than 220"),
        (["concepts", 0, "script"], "Something else entirely.", "hook"),
        (["concepts", 1, "id"], "c1", "unique"),
        (["product", "price"], 9.99, "unknown or unsupported"),
    ],
)
def test_invalid_packs_are_rejected(path: list[Any], value: Any, message: str) -> None:
    with pytest.raises(ad_packs.PackError, match=message):
        ad_packs.validate(_mutate(path, value))


def test_voice_rules() -> None:
    voiced = _concept(1, format="faceless_free_voice", voice_name="en-US-AriaNeural-Female")
    ad_packs.validate(_mutate(["concepts", 0], voiced))
    with pytest.raises(ad_packs.PackError, match="voice_name must be one of"):
        ad_packs.validate(_mutate(["concepts", 0], {**voiced, "voice_name": "elevenlabs:rachel"}))
    with pytest.raises(ad_packs.PackError, match="pack language"):
        ad_packs.validate(_mutate(["concepts", 0], {**voiced, "voice_name": "tr-TR-EmelNeural-Female"}))
    with pytest.raises(ad_packs.PackError, match="only used by faceless"):
        ad_packs.validate(_mutate(["concepts", 0], _concept(1, voice_name="en-US-AriaNeural-Female")))


def test_native_game_capture_rules() -> None:
    native = {"kind": "native_game", "formats": ["9:16"], "duration_s": 30,
              "native": {"platform": "ios", "app_id": "com.example.game", "deep_link": "game://play?menivor_demo=1"}}
    ad_packs.validate(_mutate(["captures"], [native]))
    with pytest.raises(ad_packs.PackError, match="not a URL"):
        ad_packs.validate(_mutate(["captures"], [{**native, "url": "https://example.com"}]))
    with pytest.raises(ad_packs.PackError, match="app_id"):
        ad_packs.validate(_mutate(["captures"], [{**native, "native": {"platform": "ios"}}]))
    with pytest.raises(ad_packs.PackError, match="adb serial"):
        ad_packs.validate(_mutate(["captures"], [{**native, "native": {"platform": "android", "app_id": "com.x.y"}}]))
    with pytest.raises(ad_packs.PackError, match="deep_link"):
        bad = {**native, "native": {**native["native"], "deep_link": "game://play now"}}
        ad_packs.validate(_mutate(["captures"], [bad]))


def test_store_capture_takes_no_duration() -> None:
    store = {"kind": "app_store", "url": "https://apps.apple.com/us/app/x/id6780166477", "formats": ["9:16"],
             "duration_s": None}
    ad_packs.validate(_mutate(["captures"], [store]))
    with pytest.raises(ad_packs.PackError, match="not used for store"):
        ad_packs.validate(_mutate(["captures"], [{**store, "duration_s": 20}]))
    with pytest.raises(ad_packs.PackError, match="App Store app link"):
        ad_packs.validate(_mutate(["captures"], [{**store, "url": "https://apps.apple.com/us/charts"}]))


# --------------------------------------------------------------------------- #
# honesty lint
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("field", "text", "message"),
    [
        ("pain", "Loved by founders everywhere.", "loved by"),
        ("proof", "Rated 4.8 by our users.", "rated"),
        ("proof", "Join 10,000 happy readers.", "10.000"),
        ("offer", "Save 50 percent today.", "50"),
        ("pain", "So good \U0001F525", "emoji"),
        ("cta", "Get it on the App Store.", "app_store"),
        ("cta", "Download now.", "download now"),
        ("proof", "Binlerce öğrenci kullanıyor.", "binlerce"),
    ],
)
def test_honesty_lint_rejects_ungrounded_copy(field: str, text: str, message: str) -> None:
    with pytest.raises(ad_packs.PackError, match=message):
        ad_packs.validate(_mutate(["concepts", 0, field], text))


def test_honesty_lint_allows_grounded_numbers_and_word_boundaries() -> None:
    pack = _mutate(["concepts", 0, "proof"], "An 8x8 grid, generated fresh.")  # "generated" is not "rated"
    ad_packs.validate(pack)


def test_store_cta_allowed_when_listing_is_live() -> None:
    pack = _mutate(["availability", "app_store"], "https://apps.apple.com/us/app/x/id6780166477")
    pack["concepts"][0]["cta"] = "Get it on the App Store."
    ad_packs.validate(pack)


# --------------------------------------------------------------------------- #
# exact request bodies
# --------------------------------------------------------------------------- #
def test_bodies_match_the_real_request_models() -> None:
    capture_router = import_module("app.domains.capture.router")
    adstudio = import_module("app.controllers.v1.adstudio")
    voiced = _concept(2, format="faceless_free_voice", voice_name="en-US-GuyNeural-Male")
    data = _pack()
    data["concepts"][1] = voiced
    data["captures"].append({"kind": "native_game", "formats": ["9:16"], "duration_s": 30,
                             "native": {"platform": "ios", "device": "booted", "app_id": "com.example.game"}})
    pack = _as_pack(data)
    plan = ad_packs.plan(pack)

    project = adstudio.CreateProjectBody.model_validate(plan["project"])
    assert project.use_llm is False and project.title == "Menivor ad pack: Demo App"
    assert [a.kind for a in project.angles] == ["demo"] * 5
    for body in plan["captures"]:
        capture_router.CreateBody.model_validate(body)
    for item in plan["ads_after_capture"]:
        ads = capture_router.AdsBody.model_validate(item["body"])
        assert ads.platforms == []  # never an auto-publish instruction
    assert plan["ads_after_capture"][1]["body"]["mode"] == "voiceover"
    assert plan["ads_after_capture"][1]["body"]["voice_name"] == "en-US-GuyNeural-Male"


def test_capture_match_key_mirrors_native_source_url() -> None:
    from app.domains.capture.native import parse_target

    native = {"platform": "ios", "app_id": "com.example.game", "title": "Game"}
    body = {"kind": "native_game", "formats": ["9:16"], "native": native}
    assert ad_packs.capture_match_key(body) == ("native_game", parse_target(native).source_url())
    linked = {**native, "deep_link": "game://play?menivor_demo=1&seed=7"}
    assert ad_packs.capture_match_key({**body, "native": linked})[1] == parse_target(linked).source_url()
    assert ad_packs.capture_match_key({"kind": "website", "url": "https://Example.com/a/"}) == (
        "website", "https://example.com/a")


# --------------------------------------------------------------------------- #
# drift against the app's own constants
# --------------------------------------------------------------------------- #
def test_mirrored_constants_match_the_app() -> None:
    from app.core.launch import formats as launch_formats
    from app.domains.adstudio import angles, variants
    from app.domains.capture import ads, models, service

    assert ad_packs.ANGLE_KINDS == angles.ANGLE_KINDS
    assert ad_packs.ANGLE_FIELD_MAX == angles.FIELD_MAX
    assert set(ad_packs.STUDIO_FORMATS) == set(variants.FORMATS) - {"ugc_avatar"}
    assert ad_packs.ASPECTS == service.FORMATS
    assert set(ad_packs.CAPTURE_KINDS) == set(models.SOURCE_KINDS)
    assert ad_packs.DURATION_LIMITS == {k: (v[0], v[2]) for k, v in service.DURATION_LIMITS.items()}
    assert ad_packs.FREE_VOICES == ads.FREE_VOICES
    assert ad_packs.MAX_SCRIPT_CHARS == ads.MAX_SCRIPT_CHARS
    assert set(ad_packs.FREE_FORMATS.values()) <= set(ads.AD_MODES)
    # Both pack formats are free tier: no provider key unlocks them.
    unlock = {fid: env_names for fid, _label, _needs, env_names in launch_formats._FORMATS}
    assert unlock["captions_only_byov"] == () and unlock["faceless_free_voice"] == ()
    assert "faceless_free_voice" in ad_packs.FREE_FORMATS
    social = import_module("app.controllers.v1.social")
    assert set(ad_packs.PLATFORMS) == set(social._SUPPORTED_PLATFORMS)


# --------------------------------------------------------------------------- #
# the seeder
# --------------------------------------------------------------------------- #
class FakeApi:
    def __init__(self, *, projects=(), captures=(), native_enabled=False, capture_status=200) -> None:
        self.projects = [dict(p) for p in projects]
        self.captures = [dict(c) for c in captures]
        self.native_enabled = native_enabled
        self.capture_status = capture_status
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        self.calls.append((method, path, copy.deepcopy(body)))
        route = path.split("?")[0]
        if (method, route) == ("GET", "/ad-studio/projects"):
            return {"projects": self.projects, "has_more": False}
        if (method, route) == ("GET", "/capture"):
            return {"captures": self.captures, "has_more": False}
        if (method, route) == ("GET", "/capture/native"):
            return {"enabled": self.native_enabled}
        if (method, route) == ("POST", "/ad-studio/projects"):
            row = {"id": f"p{len(self.projects) + 1}", "title": body["title"]}
            self.projects.append(row)
            return row
        if (method, route) == ("POST", "/capture"):
            if self.capture_status != 200:
                raise seed_ad_packs.ApiError(self.capture_status, "at most 3 captures can run at once")
            row = {"id": f"cap{len(self.captures) + 1}", "status": "queued", "source_kind": body["kind"],
                   "source_url": body.get("url") or ad_packs.capture_match_key(body)[1]}
            self.captures.append(row)
            return row
        raise AssertionError(f"unexpected call {method} {path}")

    def posts(self) -> list[str]:
        return [path for method, path, _ in self.calls if method == "POST"]


def _packs() -> list[ad_packs.AdPack]:
    data = _pack()
    data["captures"].append({"kind": "native_game", "formats": ["9:16"], "duration_s": 30,
                             "native": {"platform": "ios", "app_id": "com.example.game"}})
    return [_as_pack(data)]


def test_apply_creates_drafts_then_is_idempotent() -> None:
    api = FakeApi()
    first = seed_ad_packs.apply_packs(_packs(), api)
    assert [a["result"] for a in first] == ["created", "created", "skipped"]
    assert api.posts() == ["/ad-studio/projects", "/capture"]
    assert not any("/variants" in p or "/jobs" in p or "/ads" in p for p in api.posts())

    second = seed_ad_packs.apply_packs(_packs(), api)
    assert [a["result"] for a in second] == ["exists", "exists", "skipped"]
    assert api.posts() == ["/ad-studio/projects", "/capture"]  # nothing new


def test_failed_captures_are_recreated_and_trailing_slash_matches() -> None:
    api = FakeApi(captures=[{"id": "old", "status": "failed", "source_kind": "website",
                             "source_url": "https://example.com/"}])
    actions = seed_ad_packs.apply_packs(_packs(), api, skip_captures=False)
    assert actions[1]["result"] == "created"
    api2 = FakeApi(captures=[{"id": "ok", "status": "succeeded", "source_kind": "website",
                              "source_url": "https://example.com/"}])
    assert seed_ad_packs.apply_packs(_packs(), api2)[1]["result"] == "exists"


def test_capture_limit_is_deferred_not_fatal() -> None:
    api = FakeApi(capture_status=429)
    actions = seed_ad_packs.apply_packs(_packs(), api)
    assert actions[1]["result"] == "deferred"


def test_native_capture_needs_flag_and_server_support() -> None:
    assert seed_ad_packs.apply_packs(_packs(), FakeApi(), native=True)[2]["reason"].startswith("native capture is not")
    api = FakeApi(native_enabled=True)
    actions = seed_ad_packs.apply_packs(_packs(), api, native=True)
    assert actions[2]["result"] == "created"
    assert api.calls[-1][2]["native"] == {"platform": "ios", "app_id": "com.example.game"}


def test_skip_captures_only_touches_projects() -> None:
    api = FakeApi()
    actions = seed_ad_packs.apply_packs(_packs(), api, skip_captures=True)
    assert [a["type"] for a in actions] == ["project"]
    assert all(path.split("?")[0] == "/ad-studio/projects" for _, path, _ in api.calls)


def test_cli_dry_run_sends_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    (tmp_path / "demo.json").write_text(json.dumps(_pack()), encoding="utf-8")
    monkeypatch.setattr(seed_ad_packs, "http_transport", lambda *a, **k: pytest.fail("dry run must not call the API"))
    assert seed_ad_packs.main(["--packs-dir", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["packs"][0]["project"]["title"] == "Menivor ad pack: Demo App"


def test_cli_apply_requires_key_and_rejects_bad_packs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MENIVOR_API_KEY", raising=False)
    (tmp_path / "demo.json").write_text(json.dumps(_pack()), encoding="utf-8")
    assert seed_ad_packs.main(["--packs-dir", str(tmp_path), "--apply", "--api-key", ""]) == 2
    assert seed_ad_packs.main(["--packs-dir", str(tmp_path), "--only", "nope"]) == 2
    (tmp_path / "bad.json").write_text(json.dumps(_mutate(["language"], "de")), encoding="utf-8")
    assert seed_ad_packs.main(["--packs-dir", str(tmp_path)]) == 2


@pytest.mark.skipif(not REAL_PACKS.is_dir(), reason="gtm/menivor-ads is not next to this checkout")
def test_real_portfolio_packs_are_valid() -> None:
    capture_router = import_module("app.domains.capture.router")
    adstudio = import_module("app.controllers.v1.adstudio")
    packs = ad_packs.load_dir(REAL_PACKS)
    assert {"caldesk", "menivor", "rally"} <= {p.product_id for p in packs}
    for pack in packs:
        plan = ad_packs.plan(pack)
        adstudio.CreateProjectBody.model_validate(plan["project"])
        for body in plan["captures"]:
            capture_router.CreateBody.model_validate(body)
        for item in plan["ads_after_capture"]:
            capture_router.AdsBody.model_validate(item["body"])
