"""Stateless orchestrator: Reddit URL → submittable story reel draft.

Mirrors :class:`app.domains.ingest.service.IngestService`. ``thread_to_reel`` runs
normalize → fetch → parse → narrate → template-bind and returns a
:class:`StoryDraftResult`; it never persists. The fetcher is an injectable seam so
tests drive the whole flow with canned Reddit JSON and never hit the network.

An invalid story surfaces as a ``TemplateError`` from the template compiler's
``_assert_pipeline_valid`` (before any credit spend); malformed Reddit JSON and
fetch/normalization failures surface as :class:`StoryIngestError`.
"""

from __future__ import annotations

from app.domains.stories.contract import (
    DEFAULT_MAX_WORDS,
    StoryDraftResult,
    build_story_reel_draft,
)
from app.domains.stories.fetch import Fetcher, RedditFetchError, default_fetch, normalize_thread_url
from app.domains.stories.parse import RedditParseError, parse_thread
from app.domains.stories.script import build_story_script


class StoryIngestError(Exception):
    """Fetch/parse failure carrying an HTTP status (mirrors IngestError)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class RedditStoryService:
    def thread_to_reel(
        self,
        url: str,
        *,
        fetcher: Fetcher | None = None,
        max_words: int = DEFAULT_MAX_WORDS,
        subject: str | None = None,
        voice_id: str | None = None,
    ) -> StoryDraftResult:
        """Turn a Reddit thread URL into a submittable reel draft (no persistence)."""
        try:
            normalized = normalize_thread_url(url)
        except RedditFetchError as exc:
            raise StoryIngestError(exc.status_code, exc.message) from exc

        fetch = fetcher or default_fetch
        try:
            raw = fetch(normalized)
        except RedditFetchError as exc:
            raise StoryIngestError(exc.status_code, exc.message) from exc

        try:
            thread = parse_thread(raw)
        except RedditParseError as exc:
            raise StoryIngestError(422, str(exc)) from exc

        script = build_story_script(thread, max_words=max_words)
        resolved_subject = (subject or thread.title or thread.subreddit or "").strip()

        # An invalid story raises TemplateError here (before any credit spend); the
        # router maps it to a clean 422.
        reel_draft = build_story_reel_draft(
            script, subject=resolved_subject, voice_id=voice_id
        )

        return StoryDraftResult(
            url=normalized, thread=thread, script=script, reel_draft=reel_draft
        )
