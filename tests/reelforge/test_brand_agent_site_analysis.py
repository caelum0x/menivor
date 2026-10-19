"""Brand Agent site analysis: fixture HTML + CSS -> positioning facts (no network).

Covers text (name, one-liner, sample lines, features), brand colours (HSL CSS
variables, inline hex, theme-color), fonts (next/font class names, generic
families dropped), logo detection (<img alt="... logo">, icons as fallback),
pricing hook, category, and the fetch wrapper (same-origin stylesheets only,
fetch errors surfaced as a plain reason).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domains.brand_agent import site_analysis as sa

FIXTURES = Path(__file__).parent / "fixtures" / "brand_agent"
URL = "https://basepoint.example/"


@pytest.fixture()
def html() -> str:
    return (FIXTURES / "site.html").read_text()


@pytest.fixture()
def css() -> str:
    return (FIXTURES / "app.css").read_text()


def test_hsl_triplet_converts_to_hex():
    assert sa.hsl_to_hex("239 44% 43%") == "#3d3f9e"
    assert sa.hsl_to_hex("0 0% 100%") == "#ffffff"
    assert sa.hsl_to_hex("nonsense") == ""


def test_next_font_class_names_become_family_names():
    assert sa.font_family_name("__Instrument_Sans_3d9088") == "Instrument Sans"
    assert sa.font_family_name("__Fraunces_eaa818") == "Fraunces"
    assert sa.font_family_name("'Inter'") == "Inter"
    assert sa.font_family_name("var(--font-mono)") == ""
    assert sa.font_family_name("ui-monospace") == ""


def test_analysis_reads_text_colors_fonts_and_logo(html, css):
    result = sa.analyze_html(html, URL, stylesheets=[css])
    assert result["name"] == "Basepoint"
    assert "backend your coding agent sets up" in result["one_liner"]
    hexes = [c["hex"] for c in result["colors"]]
    # CSS brand variable (light theme first), then accent, then inline hex.
    assert hexes[0] == "#3d3f9e"
    assert "#4f46e5" in hexes and "#e8743b" in hexes
    assert "#ffffff" not in hexes and "#9ca3af" not in hexes  # whites and greys are not brand colours
    families = [f["family"] for f in result["fonts"]]
    assert families[:2] == ["Instrument Sans", "Fraunces"]
    assert result["logo"] == {"url": "https://basepoint.example/brand/basepoint-logo.svg", "origin": "img"}


def test_analysis_reads_sample_lines_features_and_pricing_hook(html, css):
    result = sa.analyze_html(html, URL, stylesheets=[css])
    assert "Tell your agent. Get a backend." in result["sample_lines"]
    assert any("start before you sign up" in line for line in result["sample_lines"])
    assert not any("ignore me" in line for line in result["sample_lines"])  # scripts never read
    assert "Postgres with branching" in result["features"]
    assert "Built for agents" in result["headings"]
    assert result["pricing_hook"] == "$25 a project, flat"
    assert "Pricing" not in result["features"] and "Changelog" not in result["features"]  # nav is not copy
    assert result["category"] == "Developer tools: backend platform"


def test_logo_falls_back_to_icons_when_no_logo_image():
    page = '<html><head><title>Acme</title><link rel="apple-touch-icon" href="/touch.png"></head><body></body></html>'
    assert sa.analyze_html(page, URL)["logo"] == {"url": "https://basepoint.example/touch.png",
                                                 "origin": "apple-touch-icon"}
    bare = "<html><head><title>Acme</title></head><body></body></html>"
    assert sa.analyze_html(bare, URL)["logo"] == {"url": "", "origin": ""}


def test_svg_logo_is_detected_inline():
    page = '<html><body><a href="/"><svg aria-label="Acme logo" class="logo"></svg></a></body></html>'
    assert sa.analyze_html(page, URL)["logo"]["origin"] == "inline-svg"


def test_stylesheet_links_are_same_origin_and_capped(html):
    links = sa.stylesheet_links(html, URL)
    assert links == ["https://basepoint.example/_next/static/css/app.css"]


class _Result:
    def __init__(self, url, body, content_type="text/html"):
        self.url = url
        self._body = body
        self.content_type = content_type

    def text(self):
        return self._body


def test_analyze_site_fetches_page_and_stylesheets(html, css):
    calls = []

    def getter(url, **_kw):
        calls.append(url)
        if url.endswith(".css"):
            return _Result(url, css, "text/css")
        return _Result(URL, html)

    result = sa.analyze_site(URL, getter=getter)
    assert calls == [URL, "https://basepoint.example/_next/static/css/app.css"]
    assert result["colors"][0]["hex"] == "#3d3f9e"
    assert result["website_url"] == URL


def test_analyze_site_turns_fetch_errors_into_plain_reasons():
    from app.domains.adstudio.fetch import FetchError

    def blocked(url, **_kw):
        raise FetchError(424, "blocked")

    with pytest.raises(sa.SiteAnalysisError) as err:
        sa.analyze_site(URL, getter=blocked)
    assert "blocked the automated visit" in err.value.message


def test_a_broken_stylesheet_never_fails_the_analysis(html):
    from app.domains.adstudio.fetch import FetchError

    def getter(url, **_kw):
        if url.endswith(".css"):
            raise FetchError(502, "could not reach the URL")
        return _Result(URL, html)

    result = sa.analyze_site(URL, getter=getter)
    assert result["name"] == "Basepoint"
    assert "#4f46e5" in [c["hex"] for c in result["colors"]]
