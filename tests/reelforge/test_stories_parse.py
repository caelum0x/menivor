"""Unit: stories.parse — Reddit 2-listing JSON → cleaned, frozen RedditThread."""

from __future__ import annotations

import json

import pytest

from app.domains.stories.parse import RedditParseError, RedditThread, parse_thread


def _listing(
    *,
    title="AITA for eating the last slice?",
    subreddit="AmItheAsshole",
    author="throwaway_99",
    selftext="So this happened last night. My roommate ate my leftovers.",
    selftext_html="",
    comments=(("t1", "You are NTA, that was your food."),),
):
    post = {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "title": title,
                        "subreddit": subreddit,
                        "author": author,
                        "selftext": selftext,
                        "selftext_html": selftext_html,
                    },
                }
            ]
        },
    }
    comment_children = [{"kind": k, "data": {"body": b}} for k, b in comments]
    comment_listing = {"kind": "Listing", "data": {"children": comment_children}}
    return [post, comment_listing]


def test_parse_basic_listing():
    thread = parse_thread(json.dumps(_listing()))
    assert isinstance(thread, RedditThread)
    assert thread.title.startswith("AITA")
    assert thread.subreddit == "AmItheAsshole"
    assert thread.author == "throwaway_99"
    assert "roommate ate my leftovers" in thread.body
    assert thread.top_comments == ("You are NTA, that was your food.",)


def test_parse_accepts_prelisting_list_object():
    # Already-decoded list (not a JSON string) is accepted too.
    thread = parse_thread(_listing())
    assert thread.body


def test_selftext_html_is_cleaned_and_preferred():
    html = "&lt;div&gt;&lt;p&gt;Bold &lt;b&gt;twist&lt;/b&gt; here.&lt;/p&gt;&lt;/div&gt;"
    thread = parse_thread(_listing(selftext="plain fallback", selftext_html=html))
    # HTML path wins and is stripped of tags/entities.
    assert "twist" in thread.body
    assert "<" not in thread.body and "&lt;" not in thread.body
    assert thread.body != "plain fallback"


def test_removed_and_more_comment_stubs_dropped():
    thread = parse_thread(
        _listing(
            comments=(
                ("t1", "[removed]"),
                ("t1", "[deleted]"),
                ("more", "load more comments"),
                ("t1", "Real keeper comment."),
            )
        )
    )
    assert thread.top_comments == ("Real keeper comment.",)


def test_removed_body_raises_parse_error():
    with pytest.raises(RedditParseError):
        parse_thread(_listing(selftext="[removed]", selftext_html=""))


def test_empty_body_raises_parse_error():
    with pytest.raises(RedditParseError):
        parse_thread(_listing(selftext="   ", selftext_html=""))


def test_malformed_json_raises_parse_error():
    with pytest.raises(RedditParseError):
        parse_thread("{not json")


def test_missing_post_listing_raises():
    with pytest.raises(RedditParseError):
        parse_thread([{"data": {"children": []}}])


def test_reddit_error_envelope_dict_raises():
    # Deleted/private/banned/quarantined threads + 429s return a 200 body of
    # {"error": <code>, ...} (a dict, not a 2-element listing) — surfaced as 422.
    with pytest.raises(RedditParseError, match="reddit returned an error"):
        parse_thread({"error": 404, "message": "Not Found"})


def test_reddit_error_envelope_json_string_raises():
    # default_fetch hands parse_thread the raw 200 body text; a removed/private
    # thread yields this error envelope as a JSON string.
    with pytest.raises(RedditParseError, match="reddit returned an error"):
        parse_thread('{"error": 403, "message": "Forbidden"}')


def test_thread_is_frozen():
    thread = parse_thread(_listing())
    with pytest.raises(Exception):
        thread.body = "mutated"  # type: ignore[misc]
