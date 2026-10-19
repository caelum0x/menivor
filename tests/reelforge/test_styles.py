"""One-click reel styles: catalog, meme hooks, hook writer, scene graphs, glue.

Covers:
  * the style catalog is internally consistent (layouts, caption presets,
    background loops and hook families all resolve);
  * meme hook formats are opt-in (never in the default rotation), validate
    their shape, and have template fallbacks that pass their own check;
  * the link-mode hook writer keeps model hooks that match and falls back to
    templates per format otherwise;
  * every scene builds a valid-looking filtergraph that only draws text from
    files (never inline user text);
  * visuals: preview-image extraction, anime prompts that never name a
    franchise, spend accounting and caps;
  * compose glue + job-API folding (overrides, 400 on unknown, hook family).
"""

from __future__ import annotations

import dataclasses
import importlib
import json
from types import SimpleNamespace

import pytest

from app.domains.content import background_library as bglib
from app.domains.experiments import hook_styles as hs
from app.domains.styles import catalog
from app.domains.styles import hooks as style_hooks
from app.services.captions.presets import CAPTION_STYLE_PRESETS
from app.services.compose.compose_ffmpeg import supported_layouts
from app.services.reelforge import ReelForgeParams
from app.services.styles import pipeline, scene, visuals


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """Page recording launches Chromium; tests opt in explicitly."""
    monkeypatch.setattr(pipeline, "_record_page", lambda *args, **kwargs: "")


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def test_catalog_ids_are_unique_and_cover_the_formats() -> None:
    ids = [style.id for style in catalog.list_styles()]
    assert len(ids) == len(set(ids))
    for wanted in (
        "gameplay_split",
        "meme_hook",
        "anime",
        "satisfying_split",
        "pov_text",
        "before_after",
        "ugc_avatar",
        "greenscreen",
        "story_gameplay",
        "character_story",
    ):
        assert wanted in ids


@pytest.mark.parametrize("style", catalog.list_styles(), ids=lambda s: s.id)
def test_every_style_resolves_against_the_pipeline(style: catalog.StyleSpec) -> None:
    assert style.layout in supported_layouts()
    assert style.caption_style in CAPTION_STYLE_PRESETS
    assert style.hook_family
    for hook in style.hook_family:
        assert hs.normalize_hook_style(hook) == hook
    if style.background_id:
        assert bglib.get(style.background_id) is not None
    assert style.scene in ("",) + scene.SCENES
    assert style.visual in ("page", "anime", "character", "none")
    assert style.script_mode in ("page", "story")
    assert (style.layout != "captions_only") == style.needs_presenter
    assert "template" not in (style.label + style.blurb).lower()


def test_require_style_blank_unknown_and_aliases() -> None:
    assert catalog.require_style("") is None
    assert catalog.require_style("Gameplay-Split").id == "gameplay_split"
    with pytest.raises(catalog.UnknownStyleError):
        catalog.require_style("minecraft")


def test_style_overrides_fill_hook_only_when_absent() -> None:
    meme = catalog.get_style("meme_hook")
    filled = catalog.style_overrides(meme)
    assert filled["hook_style"] == "met_me_at"
    assert filled["layout"] == "captions_only"
    assert filled["background_id"] == "block-runner"
    kept = catalog.style_overrides(meme, hook_style="nobody_me")
    assert "hook_style" not in kept


def test_public_catalog_is_json_serializable() -> None:
    payload = [style.to_public() for style in catalog.list_styles()]
    assert json.loads(json.dumps(payload))[0]["hook_family"]


# --------------------------------------------------------------------------- #
# Meme hook formats
# --------------------------------------------------------------------------- #
def test_meme_formats_are_accepted_but_not_rotated() -> None:
    for style in hs.MEME_HOOK_STYLES:
        assert hs.normalize_hook_style(style) == style
        assert style not in hs.rotate_hook_styles(99)
    assert hs.normalize_hook_style("met-me-at") == "met_me_at"


# ``stat``'s legacy template ("One number ...") is intentionally digit-free.
@pytest.mark.parametrize("style", [s for s in hs.ALL_HOOK_STYLES if s != "stat"])
def test_template_hooks_match_their_own_shape(style: str) -> None:
    for language in ("en", "tr"):
        hook = hs.template_hook(style, "Menivor", language)
        assert hs.hook_matches_style(hook, style), (style, language, hook)


@pytest.mark.parametrize(
    ("style", "good", "bad"),
    [
        ("met_me_at", "You met me at a very chaotic time in my life.", "Meet the best tool."),
        ("nobody_me", "Nobody: / Me: pasting links at 3am.", "Nobody tells you this."),
        ("wish_i_knew", "Things I wish I knew before launching an app.", "Things to know."),
        ("before_after", "Before: 3 tools. After: one link.", "After all this time."),
        ("tell_me_without", "Tell me you ship daily without telling me.", "Tell me more."),
        ("day_in_life", "A day in the life of a solo founder.", "My life changed."),
    ],
)
def test_meme_shape_checks(style: str, good: str, bad: str) -> None:
    assert hs.hook_matches_style(good, style)
    assert not hs.hook_matches_style(bad, style)


def test_rotate_family_cycles_and_validates() -> None:
    assert hs.rotate_family(3, ("pov",)) == ["pov", "pov", "pov"]
    assert hs.rotate_family(2, ("met_me_at", "nobody_me", "wish_i_knew")) == [
        "met_me_at",
        "nobody_me",
    ]
    assert hs.rotate_family(3, ()) == []
    with pytest.raises(hs.HookStyleError):
        hs.rotate_family(2, ("nope",))


def test_meme_directives_forbid_invented_numbers() -> None:
    assert "Never invent numbers" in hs.directive_for("before_after")
    assert "met me at a very" in hs.directive_for("met_me_at")


# --------------------------------------------------------------------------- #
# Link-mode hook writer
# --------------------------------------------------------------------------- #
_PAGE = {
    "title": "Scribase",
    "description": "The backend for your apps: Postgres, auth and storage in one place.",
    "features": ["Branch a database per task", "Hosted MCP for agents"],
}


def test_write_hooks_keeps_matching_model_hooks() -> None:
    prompts: list[str] = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(
            {
                "met_me_at": "You met me at a very database-less time in my life.",
                "nobody_me": "Nobody: / Me: branching a database for every task.",
                "wish_i_knew": "Things I wish I knew before wiring auth by hand.",
            }
        )

    out = style_hooks.write_hooks(
        **_PAGE, formats=["met_me_at", "nobody_me", "wish_i_knew"], generate=generate
    )
    assert [item["source"] for item in out] == ["model"] * 3
    assert [item["hook_style"] for item in out] == ["met_me_at", "nobody_me", "wish_i_knew"]
    assert len(prompts) == 1
    assert "Postgres, auth and storage" in prompts[0]
    assert "never invent" in prompts[0].lower()


def test_write_hooks_falls_back_per_format() -> None:
    calls = {"n": 0}

    def generate(prompt: str) -> str:
        calls["n"] += 1
        return 'Sure! {"met_me_at": "Try Scribase today", "nobody_me": "Nobody: / Me: shipping."}'

    out = style_hooks.write_hooks(
        **_PAGE, formats=["met_me_at", "nobody_me"], generate=generate, attempts=2
    )
    by_style = {item["hook_style"]: item for item in out}
    assert by_style["nobody_me"]["source"] == "model"
    assert by_style["met_me_at"]["source"] == "template"
    assert hs.hook_matches_style(by_style["met_me_at"]["hook"], "met_me_at")
    assert calls["n"] == 2  # retried only the missing format


def test_write_hooks_survives_provider_errors() -> None:
    def boom(prompt: str) -> str:
        raise RuntimeError("provider down")

    out = style_hooks.write_hooks(**_PAGE, formats=["pov", "before_after"], generate=boom)
    assert [item["source"] for item in out] == ["template", "template"]
    for item in out:
        assert hs.hook_matches_style(item["hook"], item["hook_style"])


def test_write_hooks_rejects_overlong_hooks() -> None:
    long_hook = "POV: " + "very " * 60

    out = style_hooks.write_hooks(
        **_PAGE, formats=["pov"], generate=lambda p: json.dumps({"pov": long_hook})
    )
    assert out[0]["source"] == "template"


def test_parse_hooks_is_tolerant() -> None:
    assert style_hooks.parse_hooks("no json here") == {}
    assert style_hooks.parse_hooks("{not json}") == {}
    assert style_hooks.parse_hooks('x {"POV": "POV: hi"} y') == {"pov": "POV: hi"}


def test_normalize_formats_dedupes_and_caps() -> None:
    assert style_hooks.normalize_formats(["pov", "POV", "question", "story", "stat"]) == [
        "pov",
        "question",
        "story",
    ]


# --------------------------------------------------------------------------- #
# Scene graphs
# --------------------------------------------------------------------------- #
def _spec(name: str, *, images: int = 2, loop: str = "/tmp/loop.mp4", texts=None) -> scene.SceneSpec:
    return scene.SceneSpec(
        scene=name,
        images=tuple(f"/tmp/plate-{i}.png" for i in range(images)),
        duration_s=12.0,
        font_path="/fonts/Montserrat-ExtraBold.ttf",
        loop_path=loop,
        texts=texts or {},
    )


@pytest.mark.parametrize("name", scene.SCENES)
def test_every_scene_builds_a_graph_ending_in_out(name: str) -> None:
    texts = {key: f"/tmp/{key}.txt" for key in scene.texts_for(name, "Before: a. After: b.", "T")}
    graph = scene.build_filtergraph(_spec(name, texts=texts))
    assert graph.rstrip().endswith("[out]")
    if name not in ("story", "character"):
        assert "concat=n=2" in graph
    if texts:
        assert "textfile=" in graph
    assert "text='" not in graph  # never inline text


def test_stack_scene_stacks_visuals_over_loop() -> None:
    graph = scene.build_filtergraph(_spec("stack"))
    assert "vstack=inputs=2" in graph
    assert f"scale={scene.WIDTH}:{scene.HALF}" in graph  # loop fills the bottom half


def test_meme_scene_draws_the_white_band() -> None:
    graph = scene.build_filtergraph(_spec("meme", texts={"band": "/tmp/band.txt"}))
    assert f"color=c=white:s={scene.WIDTH}x{scene.MEME_BAND}" in graph
    assert "vstack=inputs=3" in graph


def test_scene_validation_errors() -> None:
    with pytest.raises(ValueError):
        scene.build_filtergraph(_spec("nope"))
    with pytest.raises(ValueError):
        scene.build_filtergraph(_spec("stack", images=0))
    with pytest.raises(ValueError):
        scene.build_filtergraph(_spec("stack", loop=""))
    # full and before/after need no loop clip
    scene.build_filtergraph(_spec("full", loop=""))
    scene.build_filtergraph(_spec("before_after", loop=""))


def test_build_command_inputs_and_output() -> None:
    argv = scene.build_command(_spec("stack"), "/tmp/out.mp4", ffmpeg="ffmpeg")
    assert argv.count("-loop") == 2
    assert "-stream_loop" in argv
    assert argv[-1] == "/tmp/out.mp4"
    assert "-an" in argv
    full = scene.build_command(_spec("full"), "/tmp/out.mp4")
    assert "-stream_loop" not in full


def test_escape_neutralizes_filter_syntax() -> None:
    escaped = scene._escape("/tmp/a:b,c'd")
    assert "\\:" in escaped and "\\," in escaped and "\\'" in escaped


def test_texts_and_before_after_split() -> None:
    before, after = scene.split_before_after("Before Scribase: three dashboards. After: one.", "X")
    assert before == "Three dashboards"
    assert after == "One"
    assert scene.split_before_after("no shape", "Scribase")[1] == "Scribase"
    assert set(scene.texts_for("before_after", "Before: a. After: b.", "t")) == {
        "before_label",
        "after_label",
        "before",
        "after",
    }
    assert scene.texts_for("stack", "x", "t") == {}
    wrapped = scene.wrap("word " * 200, 20, 3)
    assert wrapped.count("\n") == 2 and wrapped.endswith("…")



def test_wrap_prefers_first_sentence_over_ellipsis() -> None:
    """A long two-sentence hook shows its first sentence whole instead of a cut-off '…'."""
    from app.services.styles import scene

    hook = ("You met me at a very chaotic time in my life. Scribase handed me hosted Postgres, "
            "Auth, Storage and branching for just $25 a project.")
    wrapped = scene.wrap(hook, 26, 4)
    assert "…" not in wrapped
    assert wrapped.replace("\n", " ") == "You met me at a very chaotic time in my life."

def test_plate_command_oversizes_panel() -> None:
    argv = scene.plate_command("/tmp/in.png", 1080, 960, "/tmp/plate.png")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "1166:1036" in graph
    assert scene.panel_size("meme") == (1080, (scene.HEIGHT - scene.MEME_BAND) // 2)


# --------------------------------------------------------------------------- #
# Visuals
# --------------------------------------------------------------------------- #
def test_meta_image_url_extraction() -> None:
    html = '<meta property="og:image" content="/img/cover.png"><title>x</title>'
    assert visuals.meta_image_url(html, "https://scribase.com/pricing") == (
        "https://scribase.com/img/cover.png"
    )
    tw = "<meta name='twitter:image' content='https://cdn.x.com/a.jpg'>"
    assert visuals.meta_image_url(tw, "https://x.com") == "https://cdn.x.com/a.jpg"
    assert visuals.meta_image_url("<p>nothing</p>", "https://x.com") == ""
    assert visuals.meta_image_url('<meta property="og:image" content="javascript:x">', "") == ""


def test_page_image_downloads_through_the_fetcher(tmp_path) -> None:
    calls: list[str] = []

    def fetch(url: str, **kwargs):
        calls.append(url)
        if url.endswith(".png"):
            return SimpleNamespace(url=url, content_type="image/png", body=b"PNG", text=lambda: "")
        html = '<meta property="og:image" content="https://x.com/c.png">'
        return SimpleNamespace(url=url, content_type="text/html", body=b"", text=lambda: html)

    paths = visuals.page_image("https://x.com", str(tmp_path), fetch=fetch)
    assert calls == ["https://x.com", "https://x.com/c.png"]
    assert paths and open(paths[0], "rb").read() == b"PNG"
    assert visuals.page_image("", str(tmp_path), fetch=fetch) == []


def test_page_image_rejects_non_images(tmp_path) -> None:
    def fetch(url: str, **kwargs):
        html = '<meta property="og:image" content="https://x.com/c.svg">'
        return SimpleNamespace(url=url, content_type="image/svg+xml", body=b"<svg/>", text=lambda: html)

    assert visuals.page_image("https://x.com", str(tmp_path), fetch=fetch) == []


def test_anime_prompt_is_original_only() -> None:
    prompt = visuals.anime_prompt("like Studio Ghibli and Naruto, a founder ships", "Menivor")
    lowered = prompt.lower()
    assert "ghibli" not in lowered and "naruto" not in lowered
    assert "original" in lowered and "no logos" in lowered


def test_anime_images_counts_spend_and_keeps_partial_results(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    prompts: list[str] = []

    def generate(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 2:
            raise RuntimeError("one scene failed")
        return f"https://replicate.delivery/{len(prompts)}.webp"

    def download(url: str, dest: str) -> str:
        return dest

    script = "Hook line.\n\nFirst beat here.\n\nSecond beat here.\n\nCall to action."
    paths, spend = visuals.anime_images(
        script, "Menivor", str(tmp_path), count=3, generate=generate, download=download
    )
    assert len(prompts) == 3
    assert len(paths) == 2
    assert spend == pytest.approx(2 * visuals.ANIME_COST_PER_IMAGE_USD)


def test_anime_images_without_token_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    assert visuals.anime_images("x", "y", str(tmp_path)) == ([], 0.0)


def test_anime_image_count_is_capped(monkeypatch) -> None:
    monkeypatch.setenv("STYLE_ANIME_IMAGES", "50")
    assert visuals.anime_image_count() == visuals.MAX_ANIME_IMAGES
    monkeypatch.setenv("STYLE_ANIME_IMAGES", "abc")
    assert visuals.anime_image_count() == visuals.DEFAULT_ANIME_IMAGES


# --------------------------------------------------------------------------- #
# Compose glue
# --------------------------------------------------------------------------- #
def _params(**overrides) -> ReelForgeParams:
    return dataclasses.replace(ReelForgeParams(video_subject="Scribase"), **overrides)


def test_hook_line_is_first_paragraph() -> None:
    assert pipeline.hook_line("\n\nPOV: you shipped.\n\nBody.") == "POV: you shipped."
    assert pipeline.hook_line("") == ""


def test_build_style_screen_skips_plain_jobs(tmp_path) -> None:
    assert pipeline.build_style_screen("j1", _params(), {}, str(tmp_path)) == ""


def test_build_style_screen_anime_falls_back_to_page(tmp_path, monkeypatch) -> None:
    rendered: dict = {}
    monkeypatch.setattr(pipeline, "_font_path", lambda: "/fonts/x.ttf")
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")

    def render(**kwargs):
        rendered.update(kwargs)
        return kwargs["out_path"]

    ctx = {"script": "Let me tell you a story.\n\nBody.", "audio_duration": 21.0}
    out = pipeline.build_style_screen(
        "j1",
        _params(style="anime", source_url="https://menivor.com", target_duration_s=15),
        ctx,
        str(tmp_path),
        render=render,
        anime=lambda *a, **k: ([], 0.0),
        page=lambda url, dest: [f"{dest}/page.png"],
    )
    assert out.endswith("style-screen.mp4")
    assert rendered["scene"] == "full"
    assert rendered["images"][0].endswith("page.png")
    assert rendered["hook"] == "Let me tell you a story."
    assert rendered["duration_s"] >= 21.0
    assert ctx["style_provider_spend_usd"] == 0.0


def test_build_style_screen_uses_the_style_loop(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(pipeline, "_font_path", lambda: "/fonts/x.ttf")
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(
        pipeline, "_loop_path", lambda bg, job, dur, *rest: seen.setdefault("bg", bg) and "/tmp/loop.mp4"
    )
    out = pipeline.build_style_screen(
        "j2",
        _params(style="satisfying_split"),
        {"script": "Nobody tells you this."},
        str(tmp_path),
        render=lambda **kwargs: kwargs["out_path"],
        page=lambda url, dest: [],
    )
    assert out
    assert seen["bg"] == "sand-slice"


def test_build_style_screen_degrades_on_render_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "_font_path", lambda: "/fonts/x.ttf")
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")

    def render(**kwargs):
        raise RuntimeError("ffmpeg exploded")

    out = pipeline.build_style_screen(
        "j3", _params(style="before_after"), {}, str(tmp_path), render=render, page=lambda u, d: []
    )
    assert out == ""


# --------------------------------------------------------------------------- #
# Job API folding
# --------------------------------------------------------------------------- #
def test_apply_style_folds_defaults_and_clears_avatar() -> None:
    reels_router = importlib.import_module("app.domains.reels.router")

    params = _params(style="gameplay_split", avatar_id="av1", layout="pip")
    folded = reels_router._apply_style(params, "req")
    assert folded.layout == "captions_only"
    assert folded.avatar_id == ""
    assert folded.caption_style == "split_center"
    assert folded.background_id == "block-runner"
    assert folded.hook_style == "pov"

    presenter = reels_router._apply_style(_params(style="greenscreen", avatar_id="av1"), "req")
    assert presenter.avatar_id == "av1"
    assert presenter.layout == "pip"


def test_apply_style_rejects_unknown_and_bad_source_url() -> None:
    reels_router = importlib.import_module("app.domains.reels.router")
    from app.models.exception import HttpException

    with pytest.raises(HttpException):
        reels_router._apply_style(_params(style="clickbait"), "req")
    cleaned = reels_router._apply_style(_params(source_url="file:///etc/passwd"), "req")
    assert cleaned.source_url == ""
    kept = reels_router._apply_style(_params(source_url="https://scribase.com"), "req")
    assert kept.source_url == "https://scribase.com"


def test_variant_hooks_follow_the_style_family() -> None:
    reels_router = importlib.import_module("app.domains.reels.router")

    meme = reels_router._apply_style(_params(style="meme_hook"), "req")
    assert reels_router._variant_hook_styles(meme, 3) == ["met_me_at", "nobody_me", "tell_me_without"]
    pov = reels_router._apply_style(_params(style="pov_text"), "req")
    assert reels_router._variant_hook_styles(pov, 2) == ["pov", "pov"]
    plain = _params()
    assert reels_router._variant_hook_styles(plain, 2) == ["pov", "question"]


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _client(monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    styles_router = importlib.import_module("app.domains.styles.router")

    monkeypatch.setattr(styles_router, "_authenticate", lambda request, rid: "user-1")
    import app.services.ratelimit as ratelimit

    monkeypatch.setattr(ratelimit, "enforce_rate_limit", lambda *a, **k: None)
    from fastapi.responses import JSONResponse

    from app.models.exception import HttpException

    app = FastAPI()
    app.add_exception_handler(
        HttpException,
        lambda request, exc: JSONResponse({"message": exc.message}, status_code=exc.status_code),
    )
    app.include_router(styles_router.router)
    return TestClient(app), styles_router


def test_get_styles_endpoint(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    body = client.get("/api/v1/styles").json()
    ids = [style["id"] for style in body["data"]["styles"]]
    assert "meme_hook" in ids and "gameplay_split" in ids


def test_post_style_hooks_endpoint(monkeypatch) -> None:
    client, module = _client(monkeypatch)
    seen: dict = {}

    def fake_write_hooks(**kwargs):
        seen.update(kwargs)
        return [{"hook_style": f, "hook": "x", "source": "template"} for f in kwargs["formats"]]

    monkeypatch.setattr(module, "write_hooks", fake_write_hooks)
    response = client.post(
        "/api/v1/styles/hooks", json={"style": "meme_hook", "title": "Scribase"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["style"] == "meme_hook"
    assert seen["formats"] == ["met_me_at", "nobody_me", "tell_me_without"]

    bad = client.post("/api/v1/styles/hooks", json={"style": "nope", "title": "x"})
    assert bad.status_code == 400
    empty = client.post("/api/v1/styles/hooks", json={"title": "x"})
    assert empty.status_code == 400
    extra = client.post("/api/v1/styles/hooks", json={"title": "x", "evil": 1})
    assert extra.status_code == 422


def test_background_library_ids_are_unique() -> None:
    ids = [clip.id for clip in bglib._CLIPS]
    assert len(ids) == len(set(ids))
    for style in catalog.list_styles():
        if style.background_id:
            assert bglib.get(style.background_id).source == "bundled"


def test_top_text_scenes_keep_captions_at_the_bottom() -> None:
    for style in catalog.list_styles():
        if style.scene in ("meme", "pov"):
            assert CAPTION_STYLE_PRESETS[style.caption_style].alignment == 2


def test_story_scenes_draw_a_timed_card_over_gameplay() -> None:
    texts = {"card_head": "/tmp/h.txt", "card": "/tmp/c.txt"}
    story = scene.build_filtergraph(_spec("story", images=0, texts=texts))
    assert "enable='lt(t,5.0)'" in story
    assert story.rstrip().endswith("[out]")
    character = scene.build_filtergraph(_spec("character", images=1, texts=texts))
    assert "sin(2*PI*t)" in character and "[narrator]" in character
    with pytest.raises(ValueError):
        scene.build_filtergraph(_spec("story", images=0, loop=""))
    argv = scene.build_command(_spec("story", images=0, texts=texts), "/tmp/o.mp4")
    assert "-stream_loop" in argv and "-loop" not in argv


def test_character_image_is_original_and_costed(tmp_path) -> None:
    prompts: list[str] = []
    paths, spend = visuals.character_image(
        str(tmp_path),
        generate=lambda p: prompts.append(p) or "https://x/y.webp",
        download=lambda url, dest: dest,
    )
    assert len(paths) == 1 and spend == visuals.ANIME_COST_PER_IMAGE_USD
    assert "not based on any existing show" in prompts[0]
    assert "stewie" not in prompts[0].lower() and "family guy" not in prompts[0].lower()


def test_character_style_uses_the_narrator(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(pipeline, "_font_path", lambda: "/fonts/x.ttf")
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(pipeline, "_loop_path", lambda bg, job, dur, *rest: "/tmp/loop.mp4")
    ctx: dict = {"script": "I almost gave up.\n\nThen this."}
    out = pipeline.build_style_screen(
        "j9",
        _params(style="character_story"),
        ctx,
        str(tmp_path),
        render=lambda **kwargs: seen.update(kwargs) or kwargs["out_path"],
        character=lambda dest: ([f"{dest}/narrator.img"], 0.003),
    )
    assert out and seen["scene"] == "character"
    assert seen["images"][0].endswith("narrator.img")
    assert ctx["style_provider_spend_usd"] == 0.003


def test_english_prompts_never_mention_turkish() -> None:
    formats = list(hs.MEME_HOOK_STYLES)[:3] + ["before_after"]
    prompt = style_hooks.build_prompt("Product: X", formats, "en")
    assert "turkish" not in prompt.lower() and "önce" not in prompt.lower()
    assert "Kimse" in style_hooks.directive_in("nobody_me", "tr")


def test_before_after_grain_is_static() -> None:
    graph = scene.build_filtergraph(_spec("before_after", loop=""))
    assert "allf=t" not in graph


def test_empty_catalog_lists_keep_their_data_field() -> None:
    reels_router = importlib.import_module("app.domains.reels.router")
    from app.models.schema import AvatarListResponse, VoiceListResponse

    empty = reels_router._list_response([])
    assert empty == {"status": 200, "data": []}
    AvatarListResponse.model_validate(empty)
    VoiceListResponse.model_validate(empty)


# --------------------------------------------------------------------------- #
# Moving visuals + loop variety
# --------------------------------------------------------------------------- #
def test_video_visual_replaces_images_in_every_panel_scene() -> None:
    for name in ("stack", "meme", "full", "pov", "before_after"):
        spec = dataclasses.replace(_spec(name, images=0), visual_video="/tmp/rec.webm")
        graph = scene.build_filtergraph(spec)
        assert "[0:v]fps=30,scale=" in graph and graph.rstrip().endswith("[out]")
        argv = scene.build_command(spec, "/tmp/o.mp4")
        assert argv[argv.index("/tmp/rec.webm") - 7] == "-ss"
        assert "-loop" not in argv


def test_scroll_plan_moves_and_returns_to_top() -> None:
    from app.services.styles import page_recording as rec

    plan = rec.scroll_plan(5000, 480, 25)
    assert plan[-1][0] == 0 and len(plan) >= 3
    assert all(hold >= 400 for _, hold in plan)
    assert sum(hold for _, hold in plan) <= 26_000
    assert rec.scroll_plan(300, 480, 10)[-1][0] == 0


def test_page_recording_refuses_private_targets(monkeypatch) -> None:
    from app.services.styles import page_recording as rec

    rec._host_is_public.cache_clear()
    assert not rec.url_is_public("http://localhost:8080/admin")
    assert not rec.url_is_public("http://127.0.0.1/")
    assert not rec.url_is_public("http://169.254.169.254/latest/meta-data")
    assert not rec.url_is_public("file:///etc/passwd")
    assert not rec.url_is_public("https://user:pw@example.com/")
    called = []
    assert rec.record_page("http://10.0.0.5/", "/tmp/x", width=1080, height=960,
                           duration_s=10, playwright_factory=lambda: called.append(1)) == ""
    assert called == []


def test_mix_order_is_deterministic_and_varies_by_job() -> None:
    paths = [f"/loops/block-runner-{n}.mp4" for n in range(1, 7)]
    first = pipeline.mix_order(paths, "job-a", 30)
    assert first == pipeline.mix_order(paths, "job-a", 30)
    assert len(first) == 4 and len(set(first)) == 4
    orders = {tuple(pipeline.mix_order(paths, f"job-{n}", 30)) for n in range(8)}
    assert len(orders) > 1


def test_variants_of_groups_numbered_loops() -> None:
    ids = [clip.id for clip in bglib.variants_of("block-runner")]
    assert ids[0] == "block-runner" and "block-runner-2" in ids
    assert all(i == "block-runner" or i.startswith("block-runner-") for i in ids)
    assert [c.id for c in bglib.variants_of("marble-loop")][0] == "marble-loop"


def test_page_styles_prefer_the_page_recording(tmp_path, monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(pipeline, "_font_path", lambda: "/fonts/x.ttf")
    monkeypatch.setattr(pipeline, "_ffmpeg", lambda: "ffmpeg")
    out = pipeline.build_style_screen(
        "j10",
        _params(style="gameplay_split", source_url="https://scribase.com"),
        {"script": "POV: hi"},
        str(tmp_path),
        render=lambda **kwargs: seen.update(kwargs) or kwargs["out_path"],
        recorder=lambda url, dest, w, h, d: f"{dest}/page.webm",
        loops=lambda *args: "/tmp/mix.mp4",
        page=lambda *a: pytest.fail("image fallback should not run"),
    )
    assert out and seen["visual_video"].endswith("page.webm")
    assert seen["images"] == [] and seen["loop_path"] == "/tmp/mix.mp4"
