"""Tests for the branded Menivor email renderer (``app.services.email_templates``)."""

from __future__ import annotations

import re

import pytest

from app.services.email_templates import (
    LOGO_URL,
    SUPPORT_EMAIL,
    EmailAction,
    EmailContent,
    EmailTemplateError,
    credits_low_email,
    render_email,
    sign_in_link_email,
    video_ready_email,
)


def _content(**overrides) -> EmailContent:
    base = dict(
        subject="Subject",
        title="Title",
        paragraphs=("Hello",),
        action=EmailAction(label="Open", url="https://menivor.com/app"),
    )
    base.update(overrides)
    return EmailContent(**base)


def test_logo_is_absolute_png_with_size_and_alt():
    html = render_email(_content()).html
    assert LOGO_URL == "https://menivor.com/email/logo%402x.png"
    img = re.search(r"<img [^>]*>", html).group(0)
    assert f'src="{LOGO_URL}"' in img
    assert 'width="40"' in img and 'height="40"' in img
    assert 'alt="Menivor"' in img


def test_no_data_uris_svg_or_flexbox():
    html = render_email(_content()).html
    assert "data:" not in html
    assert "<svg" not in html
    assert "flex" not in html


def test_layout_is_table_based_600px_light_scheme():
    html = render_email(_content()).html
    assert html.startswith("<!DOCTYPE html>")
    assert "max-width:600px" in html
    assert 'role="presentation"' in html
    assert '<meta name="color-scheme" content="light">' in html
    assert 'bgcolor="#16161A"' in html  # bulletproof button cell


def test_exactly_one_primary_button_with_escaped_href():
    html = render_email(
        _content(action=EmailAction(label="Go", url="https://menivor.com/a?x=1&y=2"))
    ).html
    assert html.count('bgcolor="#16161A"') == 1
    assert 'href="https://menivor.com/a?x=1&amp;y=2"' in html


def test_content_is_escaped():
    rendered = render_email(
        _content(title="<script>x</script>", paragraphs=('a "b" & <i>c</i>',))
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "&lt;i&gt;c&lt;/i&gt;" in rendered.html
    assert "<script>x</script>" in rendered.text


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "data:text/html,x", "/relative", "ftp://x.com", "https://a.com/ b"],
)
def test_rejects_non_http_urls(url):
    with pytest.raises(EmailTemplateError):
        render_email(_content(action=EmailAction(label="Go", url=url)))
    with pytest.raises(EmailTemplateError):
        render_email(_content(unsubscribe_url=url))


def test_rejects_multiline_subject_and_empty_title():
    with pytest.raises(EmailTemplateError):
        render_email(_content(subject="a\r\nBcc: x@y.com"))
    with pytest.raises(EmailTemplateError):
        render_email(_content(title="  "))


def test_text_alternative_has_link_and_footer():
    rendered = render_email(_content(reason="Because."))
    assert "Open: https://menivor.com/app" in rendered.text
    assert SUPPORT_EMAIL in rendered.text
    assert "Because." in rendered.text
    assert "<" not in rendered.text


def test_unsubscribe_only_when_given():
    plain = render_email(_content())
    assert "Unsubscribe" not in plain.html
    assert "Unsubscribe" not in plain.text
    assert plain.headers == {}

    marketing = render_email(_content(unsubscribe_url="https://menivor.com/u/abc"))
    assert 'href="https://menivor.com/u/abc"' in marketing.html
    assert "Unsubscribe: https://menivor.com/u/abc" in marketing.text
    assert marketing.headers["List-Unsubscribe"] == "<https://menivor.com/u/abc>"


def test_footer_has_company_and_support():
    html = render_email(_content()).html
    assert f'href="mailto:{SUPPORT_EMAIL}"' in html
    assert "Menivor &middot;" in html


def test_sign_in_preset():
    rendered = sign_in_link_email(url="https://menivor.com/auth?t=1", code="123 456")
    assert rendered.subject == "Your Menivor sign-in link"
    assert "123 456" in rendered.html and "123 456" in rendered.text
    assert "expires in 15 minutes" in rendered.text
    assert "Unsubscribe" not in rendered.html


def test_video_ready_and_credits_presets():
    ready = video_ready_email(title="Launch <teaser>", url="https://menivor.com/v/1")
    assert "Launch &lt;teaser&gt;" in ready.html
    assert "Watch video: https://menivor.com/v/1" in ready.text

    low = credits_low_email(credits_left=1, url="https://menivor.com/billing")
    assert low.subject == "Your Menivor credits are running low"
    assert "1 credit left" in low.html
    with pytest.raises(EmailTemplateError):
        credits_low_email(credits_left=-1, url="https://menivor.com/billing")


def test_no_emoji_in_output():
    for rendered in (
        sign_in_link_email(url="https://menivor.com/a", code="123 456"),
        video_ready_email(title="Clip", url="https://menivor.com/v"),
        credits_low_email(credits_left=3, url="https://menivor.com/b"),
    ):
        assert all(ord(ch) < 0x2190 for ch in rendered.html + rendered.text)
