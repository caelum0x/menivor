"""Static reference data for Launch Kit (Menivor Growth phase 3): launch
directories, the 10-step distribution playbook, and the portfolio's product
names. None of this is a table -- it is curated, versioned-in-code reference
data, the same pattern as
:mod:`app.domains.competitors.sources.meta_ad_library`'s ``DEFAULT_COUNTRIES``
or :mod:`app.domains.store_connect`'s provider constants. Per-product state
(which platform a product was submitted to, which playbook step is done)
lives in :mod:`app.domains.launch_kit.models`, not here.

Playbook source: ``~/products/gtm/DISTRIBUTION-PLAYBOOK-OWNER-2026-10-13.md``
(owner, 2026-10-13) -- read for reference while building this, never edited
by this service. The product catalog mirrors
``~/products/gtm/PORTFOLIO.md`` as of 2026-10-15; it is embedded rather than
read from that path at runtime because the Menivor API process does not run
on a machine with ``~/products`` checked out. :func:`refresh_products_from_portfolio_md`
is an optional owner-box convenience that re-reads the live file when it is
reachable; production always falls back to :data:`PRODUCTS`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

#: Launch/submission directories a founder lists a new product on. ``url`` is
#: the real submission page (not just the homepage) wherever the site has
#: one. ``categories`` loosely tags what kind of product fits the site, used
#: only to filter :func:`list_launch_platforms`'s ``product_category``.
PLATFORMS: tuple[dict[str, Any], ...] = (
    {"id": "product_hunt", "name": "Product Hunt", "url": "https://www.producthunt.com/posts/new",
     "categories": ("saas", "ai", "app", "dev_tool", "general"),
     "note": "Biggest general launch audience; post at 00:01 PT for a full day on the board."},
    {"id": "betalist", "name": "BetaList", "url": "https://betalist.com/submit",
     "categories": ("saas", "ai", "app", "general"),
     "note": "Pre-launch/early-stage audience; free submission queue is slower, paid is same-week."},
    {"id": "devhunt", "name": "DevHunt", "url": "https://devhunt.org/submit",
     "categories": ("dev_tool", "ai", "saas"),
     "note": "Developer-tool-focused Product-Hunt-style board."},
    {"id": "peerlist", "name": "Peerlist (Launchpad)", "url": "https://peerlist.io/launchpad",
     "categories": ("saas", "ai", "dev_tool", "general"),
     "note": "Builder/tech-professional audience; a Peerlist profile post plus a Launchpad entry."},
    {"id": "hacker_news", "name": "Hacker News (Show HN)", "url": "https://news.ycombinator.com/submit",
     "categories": ("dev_tool", "ai", "saas", "oss", "general"),
     "note": "Title must start literally with \"Show HN:\"; founders/developers, not consumers."},
    {"id": "indie_hackers", "name": "Indie Hackers", "url": "https://www.indiehackers.com/post/new",
     "categories": ("saas", "general"),
     "note": "Post the build story and milestones, not a bare pitch; community of small teams/founders."},
    {"id": "launching_next", "name": "Launching Next", "url": "https://launchingnext.com/submit",
     "categories": ("saas", "ai", "app", "general"), "note": "Free pre-launch/launch directory."},
    {"id": "saashub", "name": "SaaSHub", "url": "https://www.saashub.com/submit",
     "categories": ("saas", "ai", "dev_tool"), "note": "Alternative-to style directory; good for SEO backlinks."},
    {"id": "alternativeto", "name": "AlternativeTo", "url": "https://alternativeto.net/account/add-software/",
     "categories": ("saas", "ai", "dev_tool", "oss"),
     "note": "List as an alternative to the tool you displace; strong long-tail search traffic."},
    {"id": "futurepedia", "name": "Futurepedia", "url": "https://www.futurepedia.io/submit-tool",
     "categories": ("ai",), "note": "AI-tool-only directory with category pages that rank."},
    {"id": "there_is_an_ai_for_that", "name": "There's An AI For That",
     "url": "https://theresanaiforthat.com/add/", "categories": ("ai",),
     "note": "High-traffic AI-tool directory; free listing, paid featured slot."},
    {"id": "g2", "name": "G2", "url": "https://www.g2.com/products/new",
     "categories": ("saas", "general"), "note": "Review-site listing; most value once there are real reviews."},
    {"id": "capterra", "name": "Capterra", "url": "https://www.capterra.com/vendors/sign-up",
     "categories": ("saas", "general"), "note": "B2B software directory; buyer-intent traffic."},
    {"id": "fazier", "name": "Fazier", "url": "https://fazier.com/launch",
     "categories": ("saas", "ai", "app", "general"), "note": "Startup launch directory with SEO backlinks."},
    {"id": "uneed", "name": "Uneed", "url": "https://www.uneed.best/submit",
     "categories": ("saas", "ai", "dev_tool", "general"), "note": "Daily/weekly/monthly launch leaderboard."},
    {"id": "tinylaunch", "name": "TinyLaunch", "url": "https://www.tinylaunch.com/launches/new",
     "categories": ("saas", "ai", "general"), "note": "Small-team-friendly weekly launch board."},
    {"id": "reddit_sidebuild", "name": "r/SideProject", "url": "https://www.reddit.com/r/SideProject/submit",
     "categories": ("saas", "ai", "app", "general", "oss"),
     "note": "Share the build, not a bare link; r/SideProject welcomes launches."},
    {"id": "github_awesome", "name": "Awesome lists (GitHub)", "url": "https://github.com/search?q=awesome+topic&type=repositories",
     "categories": ("oss", "dev_tool"), "note": "PR your repo into the matching awesome-* list for its category."},
)
PLATFORM_BY_ID: dict[str, dict[str, Any]] = {p["id"]: p for p in PLATFORMS}

#: The 10-step playbook (owner, 2026-10-13, from gtm/DISTRIBUTION-PLAYBOOK-OWNER-2026-10-13.md).
#: Step 1 ("launch everywhere") is tracked at platform granularity via
#: LaunchPlatformStatus; the checklist marks it done once any platform for the
#: product is submitted or live.
PLAYBOOK_STEPS: tuple[dict[str, str], ...] = (
    {"key": "launch_everywhere", "title": "Launch everywhere",
     "detail": "Product Hunt, DevHunt, BetaList, Peerlist, Show HN and the other listing sites."},
    {"key": "cold_outreach", "title": "Network + cold outreach",
     "detail": "Friends, ex-colleagues, LinkedIn, one-sentence personalized cold email."},
    {"key": "reddit_pain_points", "title": "Reddit pain-point threads",
     "detail": "Find threads where people complain about the problem this product solves; reply with value."},
    {"key": "ugc_creators", "title": "UGC creator outreach",
     "detail": "DM 10-15 creators: $15-30/video plus a performance bonus, ideally from a fresh account."},
    {"key": "icp_communities", "title": "Where the ICP hangs out",
     "detail": "Communities, newsletters, podcasts, creators the ideal customer already follows."},
    {"key": "competitor_backlinks", "title": "Competitor backlinks",
     "detail": "Find where competitors are listed/linked and submit to the same places."},
    {"key": "demo_video", "title": "Demo video",
     "detail": "A short, real screen-recorded demo on X and LinkedIn -- show, don't tell."},
    {"key": "x_trends", "title": "Ride X/Twitter trends",
     "detail": "Hop on a weekly trend and plug the product with a relevant angle."},
    {"key": "build_in_public", "title": "Build in public",
     "detail": "3-4 posts/day showing real progress, not just announcements."},
    {"key": "reply_viral_tweets", "title": "Reply to viral tweets",
     "detail": "Reply with real value to viral tweets in the product's niche."},
)
STEP_BY_KEY: dict[str, dict[str, str]] = {s["key"]: s for s in PLAYBOOK_STEPS}

#: Portfolio product names (mirrors gtm/PORTFOLIO.md, 2026-10-15; "live"/"not_shipped" are the
#: statuses recorded there). Kept short on purpose: this feeds a free-text checklist lookup, not a
#: foreign key, so an unlisted product name still works via :func:`is_known_product` returning False.
PRODUCTS: tuple[str, ...] = (
    "Rally", "Menivor", "Recoder", "CalDesk AI", "Yokharita", "OpenJev", "LawSynth", "Mad Projects", "Cred402",
    "Erebos Lab", "Vertex: Orbit Arcade", "Scribase", "Railyard", "Cipher", "FlowBlast", "Aqua Sort", "Cube Blast",
    "Hexa Stack", "Color Rush", "Screw Out", "Pixel Rush", "Huddle", "Aether Wallet", "Echo", "CalGym",
    "Better Notes", "Rove", "Bump", "Calc+", "Fast Reader", "Al-Sat Marketplace", "GhostOS", "GitGram", "Vizo",
    "Bidstage", "Splits", "Side Quest", "Predikt", "Oxhan Atelier", "VCPeer",
)

_PORTFOLIO_MD_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([a-z_]+)\s*\|\s*([a-z_]+)\s*\|")


def is_known_product(name: str) -> bool:
    return name.strip().lower() in {p.lower() for p in PRODUCTS}


def refresh_products_from_portfolio_md(path: str | None = None) -> tuple[str, ...] | None:
    """Owner-box convenience: re-read ``gtm/PORTFOLIO.md``'s product table when it is reachable
    (``LAUNCH_KIT_PORTFOLIO_MD`` env var or ``path``). Returns ``None`` (never raises) when the
    file is absent -- production always keeps using the embedded :data:`PRODUCTS` fallback."""
    target = path or os.environ.get("LAUNCH_KIT_PORTFOLIO_MD") or ""
    if not target:
        return None
    file = Path(target).expanduser()
    if not file.is_file():
        return None
    names: list[str] = []
    for line in file.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = _PORTFOLIO_MD_ROW.match(line.strip())
        if m and m.group(1) not in ("Product",):
            names.append(m.group(1).strip())
    return tuple(names) or None


def platforms_for_category(category: str | None) -> tuple[dict[str, Any], ...]:
    if not category:
        return PLATFORMS
    cat = category.strip().lower()
    return tuple(p for p in PLATFORMS if cat in p["categories"])


__all__ = [
    "PLATFORMS", "PLATFORM_BY_ID", "PLAYBOOK_STEPS", "STEP_BY_KEY", "PRODUCTS", "is_known_product",
    "platforms_for_category", "refresh_products_from_portfolio_md",
]
