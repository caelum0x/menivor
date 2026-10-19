"""Integration (in-proc): RedditStoryService.thread_to_reel with a fake fetcher."""

from __future__ import annotations

import json

import pytest

from app.domains.stories.contract import StoryDraftResult
from app.domains.stories.service import RedditStoryService, StoryIngestError
from app.domains.templates.service import instantiate_draft

_LISTING = [
    {
        "kind": "Listing",
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "title": "AITA for locking my roommate out?",
                        "subreddit": "AmItheAsshole",
                        "author": "op_throwaway",
                        "selftext": (
                            "My roommate keeps eating my food. Last night I finally "
                            "snapped and changed the locks. Was I wrong?"
                        ),
                        "selftext_html": "",
                    },
                }
            ]
        },
    },
    {
        "kind": "Listing",
        "data": {
            "children": [
                {"kind": "t1", "data": {"body": "NTA, set boundaries."}},
                {"kind": "more", "data": {"body": "load more"}},
            ]
        },
    },
]


def _fake_fetch(_url: str) -> str:
    return json.dumps(_LISTING)


def test_thread_to_reel_produces_submittable_draft():
    result = RedditStoryService().thread_to_reel(
        "https://www.reddit.com/r/AmItheAsshole/comments/abc/title/",
        fetcher=_fake_fetch,
    )
    assert isinstance(result, StoryDraftResult)
    # Normalized URL is the .json API form.
    assert result.url.endswith(".json")
    assert result.thread.subreddit == "AmItheAsshole"
    assert result.thread.top_comments == ("NTA, set boundaries.",)
    assert result.script.endswith("Comment if you want Part 2.")

    draft = result.reel_draft
    assert draft["layout"] == "split"
    assert draft["background_id"] == "voxel-parkour"

    # The draft is genuinely submittable: re-running it through the real template
    # compiler validates it against JobCreateRequest without raising.
    recompiled = instantiate_draft(
        "minecraft-reddit-split",
        {"story": result.script, "subject": result.thread.title},
    )
    assert recompiled["reel_draft"]["video_script"] == result.script


def test_thread_to_reel_uses_subject_override():
    result = RedditStoryService().thread_to_reel(
        "https://reddit.com/r/x/comments/abc/t/",
        fetcher=_fake_fetch,
        subject="Custom Subject",
    )
    assert result.reel_draft["video_subject"] == "Custom Subject"


def test_thread_to_reel_maps_bad_url_to_ingest_error():
    with pytest.raises(StoryIngestError) as ei:
        RedditStoryService().thread_to_reel("ftp://nope", fetcher=_fake_fetch)
    assert ei.value.status_code == 400


def test_thread_to_reel_maps_malformed_json_to_422():
    with pytest.raises(StoryIngestError) as ei:
        RedditStoryService().thread_to_reel(
            "https://reddit.com/r/x/comments/abc/t/", fetcher=lambda _u: "{bad json"
        )
    assert ei.value.status_code == 422


def test_thread_to_reel_does_not_persist(monkeypatch):
    # No DB session factory should ever be constructed by the stateless flow.
    import app.models.db.base as db_base

    def _boom(*_a, **_k):
        raise AssertionError("thread_to_reel must not touch the database")

    monkeypatch.setattr(db_base, "get_session", _boom, raising=False)
    result = RedditStoryService().thread_to_reel(
        "https://reddit.com/r/x/comments/abc/t/", fetcher=_fake_fetch
    )
    assert result.reel_draft
