"""App Store / Play audit (Menivor Growth phase 1): packaging score, search
visibility, rewrite suggestions and the end-to-end service. No live network:
every test injects a fake ``getter``/``search``/``chat``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domains.appaudit import packaging, visibility
from app.domains.appaudit.rewrite import fallback_rewrite, generate_rewrite
from app.domains.appaudit.service import AuditError, run_audit
from app.domains.appaudit.terms import derive_search_terms
from app.domains.capture.store import StoreError, parse_itunes, parse_itunes_search

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# terms
# --------------------------------------------------------------------------- #
def test_derive_search_terms_uses_genre_and_description() -> None:
    terms = derive_search_terms(
        "Health & Fitness",
        "CalDesk AI is an AI calorie counter and macro tracker for photo-first meal logging. "
        "Snap a photo of your meal to get a calorie and macro breakdown, scan barcodes, "
        "and log every meal with AI photo scanning.",
        "CalDesk AI: Calorie Counter",
    )
    assert 6 <= len(terms) <= 10
    assert "fitness tracker" in terms
    assert "calorie tracker" in terms
    assert "caldesk" not in " ".join(terms)  # brand name never becomes a search term


def test_derive_search_terms_falls_back_for_unknown_genre() -> None:
    terms = derive_search_terms("Some New Genre", "", "Brand")
    assert terms == ["some new genre app"]


# --------------------------------------------------------------------------- #
# packaging
# --------------------------------------------------------------------------- #
def test_screenshots_check_statuses() -> None:
    assert packaging.screenshots_check(0).status == "fail"
    assert packaging.screenshots_check(2).status == "fail"
    assert packaging.screenshots_check(5).status == "warn"


def test_title_check_rewards_outcome_words() -> None:
    assert packaging.title_check("CalDesk AI: Calorie Counter").status == "pass"
    assert packaging.title_check("CalDesk AI").status == "warn"
    assert packaging.title_check("").status == "fail"


def test_promo_text_check_flags_generic_openers_and_rewards_benefits() -> None:
    assert packaging.promo_text_check("Welcome to our app, the home for everything.").status == "fail"
    assert packaging.promo_text_check("Track calories in seconds with AI photo scanning.").status == "pass"
    assert packaging.promo_text_check("Our app helps with things people like.").status == "warn"
    assert packaging.promo_text_check("").status == "fail"


def test_freshness_check_bands() -> None:
    fresh = (NOW.replace(day=1)).isoformat().replace("+00:00", "Z")
    assert packaging.freshness_check(fresh, now=NOW).status == "pass"
    stale = "2025-01-01T00:00:00Z"
    assert packaging.freshness_check(stale, now=NOW).status == "fail"
    assert packaging.freshness_check(None, now=NOW).status == "warn"
    assert packaging.freshness_check("not-a-date", now=NOW).status == "warn"


def test_analyze_icon_bytes_flags_low_contrast_and_handles_bad_data() -> None:
    from io import BytesIO

    from PIL import Image

    flat = Image.new("RGB", (128, 128), color=(120, 120, 120))
    buf = BytesIO()
    flat.save(buf, "PNG")
    flat_check = packaging.analyze_icon_bytes(buf.getvalue())
    assert flat_check.status == "warn"
    assert flat_check.heuristic is True

    checker = Image.new("RGB", (128, 128), color=(255, 255, 255))
    pixels = checker.load()
    for x in range(128):
        for y in range(128):
            if (x // 16 + y // 16) % 2 == 0:
                pixels[x, y] = (10, 10, 10)
    buf2 = BytesIO()
    checker.save(buf2, "PNG")
    contrast_check = packaging.analyze_icon_bytes(buf2.getvalue())
    assert contrast_check.status == "pass"

    broken = packaging.analyze_icon_bytes(b"not an image")
    assert broken.status == "warn"


def test_score_packaging_averages_statuses() -> None:
    checks = [
        packaging.Check("a", "A", "pass", "ok"),
        packaging.Check("b", "B", "warn", "meh"),
        packaging.Check("c", "C", "fail", "bad"),
        packaging.Check("d", "D", "pass", "ok"),
        packaging.Check("e", "E", "pass", "ok"),
    ]
    result = packaging.score_packaging(checks)
    assert result["score"] == 70  # (20+10+0+20+20)/100*100
    assert len(result["checks"]) == 5


# --------------------------------------------------------------------------- #
# visibility
# --------------------------------------------------------------------------- #
def _fake_search(rows_by_term: dict[str, list[dict[str, str]]]):
    def search(term: str, *, country: str = "us") -> list[dict[str, str]]:
        return rows_by_term.get(term, [])
    return search


def test_rank_in_results_and_top_competitors() -> None:
    rows = [{"app_id": "1", "title": "Rival"}, {"app_id": "2", "title": "Target"}, {"app_id": "3", "title": "Other"}]
    assert visibility.rank_in_results(rows, "2") == 2
    assert visibility.rank_in_results(rows, "99") is None
    competitors = visibility.top_competitors([("term", rows)], "2", limit=3)
    assert {c["app_id"] for c in competitors} == {"1", "3"}


def test_check_visibility_reports_rank_and_competitors(monkeypatch: pytest.MonkeyPatch) -> None:
    visibility.reset_cache()
    rows_by_term = {
        "calorie tracker": [{"app_id": "rival-1", "title": "Rival One"}, {"app_id": "target", "title": "CalDesk"}],
        "macro tracker": [{"app_id": "rival-1", "title": "Rival One"}],
    }
    result = visibility.check_visibility(
        ["calorie tracker", "macro tracker"], "target", search=_fake_search(rows_by_term), now=0.0,
    )
    assert result["available"] is True
    assert result["results"][0]["position"] == 2
    assert result["results"][1]["position"] is None
    assert result["top_competitors"][0]["app_id"] == "rival-1"
    assert result["cached"] is False


def test_cached_search_reuses_within_ttl() -> None:
    visibility.reset_cache()
    calls = {"n": 0}

    def search(term: str, *, country: str = "us") -> list[dict[str, str]]:
        calls["n"] += 1
        return [{"app_id": "x", "title": "X"}]

    rows1, cached1 = visibility.cached_search("term", "us", search=search, now=1000.0)
    rows2, cached2 = visibility.cached_search("term", "us", search=search, now=1000.0 + 60)
    assert cached1 is False
    assert cached2 is True
    assert calls["n"] == 1
    rows3, cached3 = visibility.cached_search("term", "us", search=search, now=1000.0 + visibility.CACHE_TTL_S + 1)
    assert cached3 is False
    assert calls["n"] == 2


def test_check_visibility_collects_store_errors() -> None:
    visibility.reset_cache()

    def failing_search(term: str, *, country: str = "us") -> list[dict[str, str]]:
        raise StoreError(502, "boom")

    result = visibility.check_visibility(["term"], "x", search=failing_search, now=1.0)
    assert result["results"] == []
    assert "boom" in result["errors"][0]


# --------------------------------------------------------------------------- #
# rewrite
# --------------------------------------------------------------------------- #
def test_fallback_rewrite_uses_only_listing_facts() -> None:
    rewrite = fallback_rewrite(
        "CalDesk AI: Calorie Counter",
        "Snap a photo of your meal to get an estimated calorie and macro breakdown.",
        "Health & Fitness",
    )
    assert rewrite.source == "fallback"
    assert len(rewrite.promo_text) <= 170
    assert len(rewrite.subtitle) <= 30
    assert rewrite.subtitle == "Calorie Counter"


def test_generate_rewrite_falls_back_when_relay_not_configured() -> None:
    rewrite = generate_rewrite("App", "A description.", "Games", 4.5, env={})
    assert rewrite.source == "fallback"


def test_generate_rewrite_uses_relay_when_configured_and_parses_json() -> None:
    def chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
        assert base_url == "https://relay.example.com/openai/v1"
        return '{"promo_text": "Track calories fast with AI.", "subtitle": "AI Calorie Tracker"}'

    rewrite = generate_rewrite(
        "App", "A description.", "Health & Fitness", 4.5,
        env={"RELAY_URL": "https://relay.example.com", "RELAY_API_KEY": "k"}, chat=chat,
    )
    assert rewrite.source == "relay"
    assert rewrite.promo_text == "Track calories fast with AI."
    assert rewrite.subtitle == "AI Calorie Tracker"


def test_generate_rewrite_accepts_railyard_prefixed_env_names() -> None:
    # The box env sets RAILYARD_RELAY_URL / RAILYARD_RELAY_API_KEY (the names
    # moderation_safeguard reads), not RELAY_URL.
    seen: dict[str, str] = {}

    def chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
        seen["base_url"], seen["api_key"] = base_url, api_key
        return '{"promo_text": "Track calories fast with AI.", "subtitle": "AI Calorie Tracker"}'

    rewrite = generate_rewrite(
        "App", "A description.", "Health & Fitness", 4.5,
        env={"RAILYARD_RELAY_URL": "https://relay.example.com", "RAILYARD_RELAY_API_KEY": "k2"}, chat=chat,
    )
    assert rewrite.source == "relay"
    assert seen == {"base_url": "https://relay.example.com/openai/v1", "api_key": "k2"}


def test_generate_rewrite_falls_back_on_relay_failure() -> None:
    def broken_chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
        raise RuntimeError("network down")

    rewrite = generate_rewrite(
        "App", "A description.", "Games", None,
        env={"RELAY_URL": "https://relay.example.com"}, chat=broken_chat,
    )
    assert rewrite.source == "fallback"


def test_generate_rewrite_falls_back_on_unusable_relay_output() -> None:
    def junk_chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
        return "not json at all"

    rewrite = generate_rewrite(
        "App", "A description.", "Games", None,
        env={"RELAY_URL": "https://relay.example.com"}, chat=junk_chat,
    )
    assert rewrite.source == "fallback"


# --------------------------------------------------------------------------- #
# store.py extras (search API + freshness fields)
# --------------------------------------------------------------------------- #
def test_parse_itunes_includes_version_and_release_date() -> None:
    listing = parse_itunes({
        "results": [{
            "kind": "software",
            "trackName": "CalDesk AI: Calorie Counter",
            "version": "1.0.18",
            "currentVersionReleaseDate": "2026-09-09T15:14:03Z",
            "trackViewUrl": "https://apps.apple.com/us/app/x/id6780166477",
        }],
    })
    assert listing["version"] == "1.0.18"
    assert listing["current_version_release_date"] == "2026-09-09T15:14:03Z"


def test_parse_itunes_search_rows() -> None:
    rows = parse_itunes_search({
        "resultCount": 2,
        "results": [
            {"trackId": 111, "trackName": "Rival One", "sellerName": "Dev A"},
            {"trackId": "bad", "trackName": "", "sellerName": "Dev B"},  # no title: dropped
        ],
    })
    assert rows == [{"app_id": "111", "title": "Rival One", "developer": "Dev A"}]


# --------------------------------------------------------------------------- #
# service (end to end)
# --------------------------------------------------------------------------- #
ITUNES_PAYLOAD = {
    "results": [{
        "kind": "software",
        "trackName": "CalDesk AI: Calorie Counter",
        "sellerName": "Umut Arhan Suba",
        "description": "Track calories and macros fast with AI photo scanning and a 400,000+ food database.",
        "artworkUrl512": "https://is1.mzstatic.com/icon512.png",
        "screenshotUrls": [f"https://is1.mzstatic.com/s{i}.png" for i in range(5)],
        "averageUserRating": 4.6,
        "userRatingCount": 120,
        "formattedPrice": "Free",
        "primaryGenreName": "Health & Fitness",
        "trackViewUrl": "https://apps.apple.com/us/app/caldesk/id6780166477",
        "version": "1.0.18",
        "currentVersionReleaseDate": "2026-09-09T15:14:03Z",
    }],
}


class _FakeIconResult:
    def __init__(self, body: bytes) -> None:
        self.body = body


def _fake_icon_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (64, 64), color=(10, 200, 30))
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_run_audit_end_to_end_app_store(monkeypatch: pytest.MonkeyPatch) -> None:
    visibility.reset_cache()
    import json as json_mod

    def getter(url: str, **kwargs):
        if "lookup" in url:
            return SimpleNamespace(text=lambda: json_mod.dumps(ITUNES_PAYLOAD))
        if "icon512" in url:
            return _FakeIconResult(_fake_icon_bytes())
        raise AssertionError(f"unexpected getter call: {url}")

    def search(term: str, *, country: str = "us") -> list[dict[str, str]]:
        if term == "fitness tracker":
            return [{"app_id": "6780166477", "title": "CalDesk AI: Calorie Counter"}]
        return [{"app_id": "999", "title": "Someone Else"}]

    def chat(prompt: str, base_url: str, api_key: str, model: str | None) -> str:
        return '{"promo_text": "Track calories fast with AI photo scanning.", "subtitle": "Calorie Counter"}'

    result = run_audit(
        "https://apps.apple.com/us/app/caldesk/id6780166477",
        getter=getter,
        search=search,
        chat=chat,
        now=NOW,
    )
    assert result["listing"]["title"] == "CalDesk AI: Calorie Counter"
    assert result["listing"]["subtitle_available"] is False
    assert result["packaging_score"]["score"] >= 0
    assert len(result["packaging_score"]["checks"]) == 5
    assert result["search_visibility"]["available"] is True
    assert result["search_visibility"]["results"][0]["term"] == "fitness tracker"
    assert result["rewrite"]["source"] == "fallback"  # chat is routed through Relay config, not injected here
    assert result["generated_at"]


def test_run_audit_play_store_marks_visibility_unavailable() -> None:
    page = (
        '<html><head>'
        '<meta property="og:title" content="Some Game - Apps on Google Play">'
        '<meta property="og:image" content="https://play-lh.googleusercontent.com/abc=w512">'
        '<meta name="description" content="A fun game you will love to play every day.">'
        '</head><body>Rated 4.2 stars out of five</body></html>'
    )

    def getter(url: str, **kwargs):
        return SimpleNamespace(text=lambda: page)

    result = run_audit("https://play.google.com/store/apps/details?id=com.example.game", getter=getter)
    assert result["listing"]["store"] == "play_store"
    assert result["search_visibility"]["available"] is False
    freshness = next(c for c in result["packaging_score"]["checks"] if c["id"] == "freshness")
    assert freshness["status"] == "warn"


def test_run_audit_rejects_non_store_urls() -> None:
    with pytest.raises(AuditError):
        run_audit("https://example.com/")


def test_run_audit_surfaces_store_errors() -> None:
    def getter(url: str, **kwargs):
        return SimpleNamespace(text=lambda: '{"results": []}')

    with pytest.raises(AuditError) as exc_info:
        run_audit("https://apps.apple.com/us/app/x/id123456789", getter=getter)
    assert exc_info.value.status_code == 404
