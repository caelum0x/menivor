"""Any-URL classifier (pure, no network) + meta/text heuristics."""

from __future__ import annotations

import pytest

from app.domains.ingest.classify import UrlClassifyError, classify_url, platform_for_host
from app.domains.ingest.inspired import build_inspired_draft, hook_style
from app.domains.ingest.meta import (
    first_line_hook, niche_from, parse_duration, parse_meta, topic_from, voice_from,
)

POST, PROFILE, WEB = "social_post", "social_profile", "website"

CASES = [
    # TikTok
    ("https://www.tiktok.com/@chef.anna/video/7301234567890123456", POST, "tiktok", "chef.anna", "TikTok post detected"),
    ("https://vm.tiktok.com/ZMabc123/", POST, "tiktok", None, "TikTok post detected"),
    ("https://vt.tiktok.com/ZSabc123/", POST, "tiktok", None, "TikTok post detected"),
    ("https://m.tiktok.com/@chef.anna", PROFILE, "tiktok", "chef.anna", "TikTok profile detected"),
    ("https://www.tiktok.com/explore", WEB, None, None, "Website detected"),
    # Instagram
    ("https://www.instagram.com/p/Cxyz123/", POST, "instagram", None, "Instagram post detected"),
    ("https://instagram.com/reel/Cabc987/?igsh=x", POST, "instagram", None, "Instagram reel detected"),
    ("https://www.instagram.com/reels/Cabc987/", POST, "instagram", None, "Instagram reel detected"),
    ("https://www.instagram.com/tv/Cabc987/", POST, "instagram", None, "Instagram video detected"),
    ("https://www.instagram.com/nike/", PROFILE, "instagram", "nike", "Instagram profile detected"),
    ("https://www.instagram.com/explore/", WEB, None, None, "Website detected"),
    ("https://www.instagram.com/accounts/login/", WEB, None, None, "Website detected"),
    # X / Twitter
    ("https://x.com/jack/status/20", POST, "x", "jack", "X post detected"),
    ("https://twitter.com/jack/status/1234567890123", POST, "x", "jack", "X post detected"),
    ("https://mobile.twitter.com/jack/status/1234567890123/photo/1", POST, "x", "jack", "X post detected"),
    ("https://x.com/jack", PROFILE, "x", "jack", "X profile detected"),
    ("https://x.com/home", WEB, None, None, "Website detected"),
    ("https://x.com/search?q=cats", WEB, None, None, "Website detected"),
    ("https://x.com/i/flow/login", WEB, None, None, "Website detected"),
    ("https://twitter.com/intent/tweet?text=hi", WEB, None, None, "Website detected"),
    # YouTube
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", POST, "youtube", None, "YouTube video detected"),
    ("https://youtu.be/dQw4w9WgXcQ?t=3", POST, "youtube", None, "YouTube video detected"),
    ("https://www.youtube.com/shorts/abcDEF12345", POST, "youtube", None, "YouTube Short detected"),
    ("https://www.youtube.com/live/abcDEF12345", POST, "youtube", None, "YouTube live video detected"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", POST, "youtube", None, "YouTube video detected"),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", POST, "youtube", None, "YouTube video detected"),
    ("https://www.youtube.com/@MrBeast", PROFILE, "youtube", "MrBeast", "YouTube channel detected"),
    ("https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA", PROFILE, "youtube", "UCX6OQ3DkcsbYNE6H8uQQuVA", "YouTube channel detected"),
    ("https://www.youtube.com/c/Veritasium", PROFILE, "youtube", "Veritasium", "YouTube channel detected"),
    ("https://www.youtube.com/user/pewdiepie", PROFILE, "youtube", "pewdiepie", "YouTube channel detected"),
    # Facebook
    ("https://fb.watch/abc123/", POST, "facebook", None, "Facebook video detected"),
    ("https://www.facebook.com/watch/?v=123456789", POST, "facebook", None, "Facebook video detected"),
    ("https://www.facebook.com/nasa/videos/123456789/", POST, "facebook", "nasa", "Facebook video detected"),
    ("https://www.facebook.com/reel/123456789", POST, "facebook", None, "Facebook reel detected"),
    ("https://m.facebook.com/nasa/posts/pfbid0abc", POST, "facebook", "nasa", "Facebook post detected"),
    ("https://www.facebook.com/share/r/1AbCdEf/", POST, "facebook", None, "Facebook post detected"),
    ("https://fb.com/nasa", PROFILE, "facebook", "nasa", "Facebook page detected"),
    ("https://www.facebook.com/groups/123", WEB, None, None, "Website detected"),
    # Threads
    ("https://www.threads.net/@zuck/post/C8abc", POST, "threads", "zuck", "Threads post detected"),
    ("https://www.threads.com/@zuck", PROFILE, "threads", "zuck", "Threads profile detected"),
    # Pinterest
    ("https://www.pinterest.com/pin/123456789012/", POST, "pinterest", None, "Pinterest pin detected"),
    ("https://pin.it/3abcDEF", POST, "pinterest", None, "Pinterest pin detected"),
    ("https://www.pinterest.co.uk/pin/123456789012/", POST, "pinterest", None, "Pinterest pin detected"),
    ("https://uk.pinterest.com/marthastewart/", PROFILE, "pinterest", "marthastewart", "Pinterest profile detected"),
    ("https://www.pinterest.de/marthastewart/recipes/", PROFILE, "pinterest", "marthastewart", "Pinterest profile detected"),
    ("https://www.pinterest.com/search/pins/?q=cake", WEB, None, None, "Website detected"),
    # LinkedIn
    ("https://www.linkedin.com/posts/satya_activity-7123-abcd", POST, "linkedin", None, "LinkedIn post detected"),
    ("https://www.linkedin.com/feed/update/urn:li:activity:7123456/", POST, "linkedin", None, "LinkedIn post detected"),
    ("https://www.linkedin.com/in/satyanadella/", PROFILE, "linkedin", "satyanadella", "LinkedIn profile detected"),
    ("https://www.linkedin.com/company/microsoft/", PROFILE, "linkedin", "microsoft", "LinkedIn company page detected"),
    # Stores + websites
    ("https://apps.apple.com/us/app/notion/id1232780281", "app_store", None, None, "App Store app detected"),
    ("https://play.google.com/store/apps/details?id=com.notion.id", "play_store", None, None, "Google Play app detected"),
    ("https://acme.example/pricing", WEB, None, None, "Website detected"),
    ("https://www.pinterest.evil.com/pin/1/", WEB, None, None, "Website detected"),
    ("https://tiktok.com.evil.example/@x", WEB, None, None, "Website detected"),
]


@pytest.mark.parametrize("url,kind,platform,handle,label", CASES)
def test_classify_table(url, kind, platform, handle, label):
    result = classify_url(url)
    assert (result.kind, result.platform, result.handle, result.label) == (kind, platform, handle, label)


def test_classify_normalizes_bare_domain_and_fragment():
    result = classify_url("  TikTok.com/@chef.anna#top ")
    assert result.url == "https://tiktok.com/@chef.anna"
    assert result.kind == PROFILE


def test_classify_to_dict_shape():
    assert classify_url("https://x.com/jack").to_dict() == {
        "kind": PROFILE, "platform": "x", "label": "X profile detected",
        "url": "https://x.com/jack", "handle": "jack",
    }


@pytest.mark.parametrize("bad", ["", "   ", "ftp://nope", "javascript:alert(1)", "not a url"])
def test_classify_rejects_non_links(bad):
    with pytest.raises(UrlClassifyError):
        classify_url(bad)


def test_platform_for_host():
    assert platform_for_host("publish.twitter.com") is None  # only listed hosts
    assert platform_for_host("www.youtube.com") == "youtube"
    assert platform_for_host("pinterest.com.au") == "pinterest"
    assert platform_for_host("evil.example") is None


# --------------------------------------------------------------------------- #
# Meta + heuristics
# --------------------------------------------------------------------------- #
def test_parse_meta_any_attribute_order():
    html = (
        '<meta content="Hello &amp; bye" property="og:title">'
        "<meta name='twitter:description' content='desc'>"
        '<meta itemprop="duration" content="PT1M3S"><title>T</title>'
    )
    meta = parse_meta(html)
    assert meta["og:title"] == "Hello & bye"
    assert meta["twitter:description"] == "desc"
    assert parse_duration(meta["duration"]) == 63
    assert meta["title"] == "T"


def test_parse_duration_variants():
    assert parse_duration("42") == 42
    assert parse_duration("PT2H") == 7200
    assert parse_duration("") is None
    assert parse_duration("soon") is None


def test_first_line_hook_and_topic():
    caption = "Stop meal prepping wrong! Here is why.\nMore text #mealprep #fitness https://t.co/x"
    assert first_line_hook(caption) == "Stop meal prepping wrong!"
    assert topic_from(caption).startswith("mealprep fitness")


def test_niche_and_voice():
    assert niche_from("Daily workout tips and gym motivation") == "fitness"
    assert voice_from("Learn how to cook: tips and tutorial every week") == "educational"
    assert voice_from("chaos and vibes only lol!!") == "playful"
    assert voice_from("Official account of the leading platform for enterprise teams") == "professional"
    assert voice_from("") == "casual"


@pytest.mark.parametrize("hook,style", [
    ("POV: you quit sugar", "pov"), ("Why is nobody talking about this?", "question"),
    ("5 apps I use daily", "list"), ("How to fall asleep fast", "howto"),
    ("Stop buying cheap pans", "warning"), ("This pan changed my life", "statement"),
])
def test_hook_style(hook, style):
    assert hook_style(hook) == style


def test_inspired_draft_never_copies_caption_or_author():
    insp = {"caption": "Anna's secret: 5 minute pasta #pasta", "hook": "Anna's secret: 5 minute pasta",
            "topic": "pasta dinner", "format": "short video", "author_name": "Anna Chef"}
    draft = build_inspired_draft(insp, "tiktok")
    text = " ".join([draft["video_script"], draft["hook"], draft["video_subject"], draft["angle"]])
    assert "Anna" not in text and "secret" not in text
    assert "pasta dinner" in draft["hook"]
    assert draft["inspired_by"] == {"platform": "tiktok", "format": "short video", "hook_style": "statement"}
    assert draft["broll_prompts"]
