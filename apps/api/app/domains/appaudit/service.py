"""Orchestrates one App Store / Play audit: classify the URL, fetch the public
listing (reusing :mod:`app.domains.capture.sources` and
``.store``), score the 5-point packaging checklist, check App Store search
visibility, and generate a rewrite suggestion. Pure data in, pure dict out —
the router is the only place that touches HTTP status codes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.domains.appaudit import packaging, terms as terms_mod, visibility
from app.domains.appaudit.rewrite import Rewrite, generate_rewrite
from app.domains.capture import store
from app.domains.capture.sources import KIND_AUTO, SourceError, classify
from app.domains.capture.store import StoreError

KIND_APP_STORE = "app_store"
KIND_PLAY_STORE = "play_store"

Getter = Callable[..., Any]


class AuditError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _listing_facts(listing: dict[str, Any], *, source_kind: str) -> dict[str, Any]:
    description = listing.get("description") or ""
    return {
        "store": source_kind,
        "url": listing.get("url") or "",
        "title": listing.get("title") or "",
        # The Lookup/Play APIs never expose Apple's dedicated "subtitle"
        # metadata field (it is App Store Connect-only); say so rather than
        # guessing one from the title.
        "subtitle": None,
        "subtitle_available": False,
        "developer": listing.get("developer") or "",
        "rating": listing.get("rating"),
        "rating_count": listing.get("rating_count"),
        "price_label": listing.get("price_label") or "",
        "genre": listing.get("genre") or "",
        "screenshot_count": len(listing.get("screenshots") or []),
        "description_length": len(description),
        "icon_url": listing.get("icon_url") or "",
        "last_updated": listing.get("current_version_release_date") if source_kind == KIND_APP_STORE else None,
        "version": listing.get("version") if source_kind == KIND_APP_STORE else None,
    }


def _packaging_checks(listing: dict[str, Any], facts: dict[str, Any], *, source_kind: str,
                       getter: Getter, now: datetime) -> list[packaging.Check]:
    icon_url = facts["icon_url"]
    if icon_url:
        try:
            result = getter(icon_url, accept="image/avif,image/webp,image/png,image/jpeg,*/*;q=0.5")
            icon_check = packaging.analyze_icon_bytes(result.body)
        except Exception:  # noqa: BLE001 - a failed icon fetch degrades the check, not the audit
            icon_check = packaging.icon_check_unavailable("Could not download the icon image to analyze it.")
    else:
        icon_check = packaging.icon_check_unavailable("No icon URL was found on the listing.")

    checks = [
        icon_check,
        packaging.screenshots_check(facts["screenshot_count"]),
        packaging.title_check(facts["title"]),
        packaging.promo_text_check(listing.get("description") or ""),
    ]
    if source_kind == KIND_APP_STORE:
        checks.append(packaging.freshness_check(facts["last_updated"], now=now))
    else:
        checks.append(packaging.Check(
            "freshness", "Updated in the last 90 days", "warn",
            "Google Play's public listing page does not reliably expose a last-update date; check the store listing directly.",
        ))
    return checks


def _visibility(listing: dict[str, Any], facts: dict[str, Any], *, source_kind: str, country: str,
                 app_id: str, search: Callable[..., list[dict[str, str]]] | None) -> dict[str, Any]:
    if source_kind != KIND_APP_STORE:
        return visibility.unavailable(
            "Google Play has no public keyword-rank API; search visibility runs for App Store listings only."
        )
    search_terms = terms_mod.derive_search_terms(facts["genre"], listing.get("description") or "", facts["title"])
    if not search_terms:
        return visibility.unavailable("Could not derive search terms from this listing's category and description.")
    kwargs: dict[str, Any] = {"country": country}
    if search is not None:
        kwargs["search"] = search
    return visibility.check_visibility(search_terms, app_id, **kwargs)


def run_audit(
    url: str,
    *,
    requested_kind: str = KIND_AUTO,
    getter: Getter | None = None,
    search: Callable[..., list[dict[str, str]]] | None = None,
    chat: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the full audit for a public App Store or Play listing URL.

    Raises :class:`AuditError` for anything user-presentable (bad URL, store
    lookup failure). ``getter``/``search``/``chat`` are injection points for
    tests; production callers leave them at their defaults.
    """
    from app.domains.adstudio.fetch import safe_get

    getter = getter or safe_get
    now = now or datetime.now(timezone.utc)

    try:
        source = classify(url, requested_kind)
    except SourceError as exc:
        raise AuditError(422, str(exc)) from exc

    if source.kind not in (KIND_APP_STORE, KIND_PLAY_STORE):
        raise AuditError(422, "paste an App Store or Google Play app link to audit it")

    try:
        if source.kind == KIND_APP_STORE:
            listing = store.fetch_app_store(source.ref, getter=getter)
            app_id = source.ref["app_id"]
            country = source.ref.get("country") or "us"
        else:
            listing = store.fetch_play_store(source.ref, getter=getter)
            app_id = source.ref["package"]
            country = (source.ref.get("gl") or "US").lower()
    except StoreError as exc:
        raise AuditError(exc.status_code, exc.message) from exc

    facts = _listing_facts(listing, source_kind=source.kind)
    checks = _packaging_checks(listing, facts, source_kind=source.kind, getter=getter, now=now)
    search_visibility = _visibility(listing, facts, source_kind=source.kind, country=country, app_id=app_id, search=search)

    rewrite_kwargs: dict[str, Any] = {}
    if chat is not None:
        rewrite_kwargs["chat"] = chat
    rewrite: Rewrite = generate_rewrite(
        facts["title"], listing.get("description") or "", facts["genre"], facts["rating"], **rewrite_kwargs
    )

    return {
        "input_url": url,
        "listing": facts,
        "packaging_score": packaging.score_packaging(checks),
        "search_visibility": search_visibility,
        "rewrite": {"promo_text": rewrite.promo_text, "subtitle": rewrite.subtitle, "source": rewrite.source},
        "generated_at": now.isoformat(),
    }


__all__ = ["AuditError", "KIND_APP_STORE", "KIND_PLAY_STORE", "run_audit"]
