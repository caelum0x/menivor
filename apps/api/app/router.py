"""Application configuration - root APIRouter.

Defines all FastAPI application endpoints. M3.3 (Wave D): production mounts
only the routes the web, mobile and desktop clients (and named third parties)
call; see ``app/core/api_surface.py`` and ``docs/api/ROUTE-AUDIT.md``.

Resources:
    1. https://fastapi.tiangolo.com/tutorial/bigger-applications

"""

from fastapi import APIRouter

from app.core.capabilities import router as pilot
from app.core.launch import router as launch_router
from app.domains.beta.router import router as beta_router
from app.domains.adstudio.router import router as adstudio_router
from app.domains.ads.router import router as ads_router
from app.domains.integrations.router import router as integrations_router
from app.domains.brand.router import router as brand_router
from app.domains.brand_agent.router import router as brand_agent_router
from app.domains.creative_review.router import router as creative_review_router
from app.domains.competitors.router import router as competitors_router
from app.domains.ad_fatigue.router import router as ad_fatigue_router
from app.domains.actors.router import router as actors_router
from app.domains.studio_render.router import router as studio_render_router
from app.domains.lipsync_translate.router import router as lipsync_translate_router
from app.domains.workflows.router import router as workflows_router
from app.domains.mcp_hosted.router import router as mcp_hosted_router
from app.domains.broll import router as broll_studio
from app.domains.billing import router as billing_router
from app.domains.byok import router as byok_router
from app.domains.canon import router as canon_router
from app.domains.captions import router as captions_router
from app.domains.characters import router as characters_router
from app.domains.clipmarket import router as clipmarket_router
from app.domains.catalog import router as catalog_router
from app.domains.community import router as community_router
from app.domains.compliance import router as compliance_router
from app.domains.compliance.takedown_router import router as takedown_router
from app.domains.funnel_readout.router import router as funnel_readout_router
from app.domains.gallery.router import router as gallery_router
from app.domains.presets_hub.router import router as presets_hub_router
from app.domains.characters.hub import router as characters_hub_router
from app.domains.characters.turnaround import router as characters_turnaround_router
from app.domains.film.story8 import router as story8_router
from app.domains.film.very_time import router as very_time_router
from app.domains.adclone.router import router as adclone_router
from app.domains.film.very_time_voice import router as very_time_voice_router
from app.services.enhance.router import router as enhance_router
from app.domains.apps_shelf.router import router as apps_shelf_router
from app.domains.ott.router import router as ott_router
from app.services.ott_transcode.router import router as ott_transcode_router
from app.domains.ott.feeds import router as ott_feeds_router
from app.domains.ott_access.router import router as ott_access_router
from app.services.loops.preset_drop import router as preset_drop_router
from app.domains.ott_viewers.router import router as ott_viewers_router
from app.services.billing.ott_plans import router as ott_plans_router
from app.domains.ott_commerce.router import router as ott_commerce_router
from app.domains.ott_ads.router import router as ott_ads_router
from app.domains.ott_live.router import router as ott_live_router
from app.domains.ott_linear.router import router as ott_linear_router
from app.domains.ott_analytics.router import router as ott_analytics_router
from app.domains.ott_ai.router import router as ott_ai_router
from app.domains.ott_discovery.router import router as ott_discovery_router
from app.domains.partners.launch_video import router as partner_launch_video_router
from app.domains.content import router as content_router
from app.domains.creator import router as creator_router
from app.domains.developer import router as developer_router
from app.domains.editor import router as editor_router
from app.domains.identity import router as identity_router
from app.domains.ingest import router as ingest_router
from app.domains.stories import router as stories_router
from app.domains.styles import router as styles_router
from app.domains.insights import router as insights_router
from app.domains.insights.usage_router import router as usage_insights_router
from app.domains.legacy import router as legacy_router
from app.domains.media import router as media_router
from app.domains.motion import router as motion_router
from app.domains.observability import router as observability_router
from app.domains.publishing import router as publishing_router
from app.domains.reels import router as reels_router
from app.domains.render import router as render_router
from app.domains.series import router as series_router
from app.domains.repurpose import router as repurpose_router
from app.domains.clipping import router as clipping_router
from app.domains.film import router as film_router
from app.domains.gateway.router import router as gateway_router
from app.domains.gateway.media_router import router as media_gateway_router
from app.domains.growth import router as growth_router
from app.domains.speak import router as speak_router
from app.domains.dub import router as dub_router
from app.domains.spend import router as spend_router
from app.domains.templates import router as templates_router
from app.domains.trends import router as trends_router
from app.domains.wallet import router as wallet_router
from app.domains.workspaces import router as workspaces_router
from app.domains.store_connect import router as store_connect_router


def build_full_router() -> APIRouter:
    """Every route the API can serve (M3.3 filters it in :func:`build_root_router`)."""
    router = APIRouter()
    # Isolated legacy v1 compatibility surface. New product routes are domain-owned.
    router.include_router(legacy_router)
    # ReelForge job pipeline routes (INTEGRATION_CONTRACT.md §5)
    router.include_router(reels_router)
    # Read-only, authenticated capability contract used by web, mobile and desktop
    # to hide generation controls that are unavailable during the internal pilot.
    router.include_router(pilot.router)
    # Non-sensitive launch gate document. Credentials never imply public checkout
    # or direct publishing; first-party clients render only explicitly enabled paths.
    router.include_router(launch_router)
    # Private-beta waitlist (public request) + operator approval (admin token).
    router.include_router(beta_router)
    # Caller-owned uploads and presigned object-storage handshakes.
    router.include_router(media_router)
    # Non-destructive editor commands; export execution is dispatched to render workers.
    router.include_router(editor_router)
    # AI B-roll Studio — async text/image -> motion clip generation
    router.include_router(broll_studio.router)
    # Speak Studio — async image + narration audio -> talking video (open lipsync)
    router.include_router(speak_router.router)
    # Dub Studio — dub any owned video (pyvideotrans container, never imported)
    router.include_router(dub_router.router)
    # The B-roll router declares canonical `/api/v1/generation/broll/*` routes and
    # legacy `/api/v1/broll/*` aliases on the same handlers. Do not include it a
    # second time with an outer prefix: APIRouter prefixes prepend before `/api/v1`
    # and would incorrectly create `/generation/api/v1/broll/*` paths.
    # Domains own route composition. Their controller imports are intentionally
    # compatibility adapters during incremental service migration; application root
    # no longer couples product routing to individual controller modules.
    router.include_router(content_router)
    router.include_router(identity_router)
    router.include_router(creator_router)
    router.include_router(publishing_router)
    # Phase 3 "Connect your store": App Store Connect / Google Play credential
    # storage + apps/versions/ratings, feeding the App Store Audit tool.
    router.include_router(store_connect_router)
    # Menivor Growth phase 2: daily top-50 App Store keyword rank tracker.
    from app.domains.keyword_tracker.router import router as keyword_tracker_router

    router.include_router(keyword_tracker_router)
    # Menivor Growth phase 3: first-100-users tooling (launch directories, Reddit
    # pain-point threads, competitor backlinks, the 10-step playbook checklist).
    from app.domains.launch_kit.router import router as launch_kit_router

    router.include_router(launch_kit_router)
    # Menivor Growth: a workspace's own OpenSEO account -> site audit, keyword
    # research and rank tracking for a handful of target keywords.
    from app.domains.seo.router import router as seo_router

    router.include_router(seo_router)
    router.include_router(workspaces_router)
    router.include_router(billing_router)
    router.include_router(developer_router)
    router.include_router(insights_router)
    router.include_router(community_router)
    router.include_router(compliance_router)
    # MN5: public content reports (/legal/reports) and staff takedown actions.
    router.include_router(takedown_router)
    # Wave E M-4 (MR1): staff funnel read-out + first-touch attribution.
    router.include_router(funnel_readout_router)
    # Wave E M-6 (MR8): launch video for Scribase and Rally users (partner token).
    router.include_router(partner_launch_video_router)
    # Wave P PM1.2 (MH2): public preset shelf; tile -> Create with the preset loaded.
    router.include_router(presets_hub_router)
    # Wave P PM1.3 (MH3): opt-in gallery of finished outputs and Recreate.
    router.include_router(gallery_router)
    # Wave P PM1.4 (MH4): My characters and brands (facade over domains/characters).
    router.include_router(characters_hub_router)
    # Wave P PM2.1 (MH5): story in 8 frames, frames-only or animated, priced first.
    router.include_router(story8_router)
    # "Very ___ Time" one-click template: a story8 preset with a guard-rail, looks and static captions.
    router.include_router(very_time_router)
    # Ad Clone: winning ad link -> clone brief -> priced episode plans (ADCLONE_ENABLED, default off)
    router.include_router(adclone_router)
    router.include_router(very_time_voice_router)
    # Wave P PM2.1 (MH7): CPU image upscale, API video upscale, GPU-lane interpolation.
    router.include_router(enhance_router)
    # Wave P PM2.2 (MH8, MH6): apps shelf and talking scenes (scenes behind PRESENTER_LIVE).
    router.include_router(apps_shelf_router)
    # Wave P PM2.3-PM2.5 (MV1-MV5): OTT; every route 404s until OTT_ENABLED and its surface flag.
    router.include_router(ott_router)
    router.include_router(ott_transcode_router)
    router.include_router(ott_feeds_router)
    router.include_router(ott_access_router)
    # Wave P PM3.0 (MH9): the weekly preset drop (public read of released drops).
    router.include_router(preset_drop_router)
    # Wave P PM3.1-PM3.5 (MV6-MV16, MV19): every route 404s until OTT_ENABLED and its surface flag.
    router.include_router(ott_viewers_router)
    router.include_router(ott_plans_router)
    router.include_router(ott_commerce_router)
    router.include_router(ott_ads_router)
    router.include_router(ott_live_router)
    router.include_router(ott_linear_router)
    router.include_router(ott_analytics_router)
    router.include_router(ott_ai_router)
    router.include_router(ott_discovery_router)
    # Pay-as-you-go marketplace: reviewed model/profile browse + generation quotes.
    router.include_router(catalog_router)
    # USD wallet: balance/activity/purchase-quote (open); checkout/webhook launch-gated.
    router.include_router(wallet_router)
    # BYOK: customer-owned provider credentials (encrypted at rest; secrets never returned).
    router.include_router(byok_router)
    # Repurposing engine: long video -> transcript -> ranked highlight clips.
    router.include_router(repurpose_router)
    # Auto-clipping: long recording -> vertical caption-burned short clips.
    router.include_router(clipping_router)
    # URL -> reel: product/article URL -> extracted content -> reel draft.
    router.include_router(ingest_router)
    # Ad Studio: product URL -> ad angles -> rendered product ad variants (batch export).
    router.include_router(adstudio_router)
    # Paid ads: launch Ad Studio variants on Meta / TikTok (gated on app review env keys).
    router.include_router(ads_router)
    # Settings > Integrations: ad accounts, Ads agent + Slack, social accounts, product sources.
    router.include_router(integrations_router)
    # Brand-kit import: website URL or Rally share -> the caller's brand kit (UserPreset).
    router.include_router(brand_router)
    router.include_router(brand_agent_router)
    # Wave 2 (2026-10-06): review queue, competitor tracker, ad fatigue, AI actors, studio renders,
    # lip-sync translation, workflow canvas and the hosted MCP connector. Spending only via approvals.
    router.include_router(creative_review_router)
    router.include_router(competitors_router)
    router.include_router(ad_fatigue_router)
    router.include_router(actors_router)
    router.include_router(studio_render_router)
    router.include_router(lipsync_translate_router)
    router.include_router(workflows_router)
    router.include_router(mcp_hosted_router)
    # Reddit thread -> story reel: fetch + narrate -> minecraft-reddit-split draft.
    router.include_router(stories_router)
    # One-click reel styles: GET /styles catalog + POST /styles/hooks (meme/POV hook writer).
    router.include_router(styles_router)
    # Genre shot-template engine: viral formats -> compiled render-spec + reel draft.
    router.include_router(templates_router)
    # Motion/camera engine: >=50 camera-move presets -> compiled MotionPlan (filter/model/hybrid).
    router.include_router(motion_router)
    # Captions facade: hook-score (70% gate) + Hormozi grouping + per-platform safe-zones.
    router.include_router(captions_router)
    # Trends: score + rank trending sounds/hashtags by opportunity (build before peak).
    router.include_router(trends_router)
    # Growth: Jev-powered Winning Hook Ranker — score + rank reel hook/caption variants
    # (one batched Jev call per variant; composite combined in code; DB-free).
    router.include_router(growth_router)
    # AI-film: plan a character-consistent multi-shot film (shot list + DAG preview).
    router.include_router(film_router)
    # Async-GPU render: start/status/advance a wallet-metered render job (success-only billing).
    router.include_router(render_router)
    # Prometheus metrics exposition (/metrics) for the observability plane.
    router.include_router(observability_router)
    # Clipping marketplace: brand campaigns + clipper submissions + fraud-gated CPM payout.
    router.include_router(clipmarket_router)
    # Reusable identity-locked characters (P9 consistency moat): save/list/reuse.
    router.include_router(characters_router)
    # Very ___ Time: front/side/back turnaround sheet as the character's identity reference.
    router.include_router(characters_turnaround_router)
    # Canon: hash-lock brand/character values into immutable, versioned locks so
    # every video/image/ad is generated consistently and provenance-verifiable.
    router.include_router(canon_router.router)
    # API-resale gateway: provisioning keys (daily cap + markup) + quote preview.
    router.include_router(gateway_router)
    # Unified media gateway (OpenRouter-style): one key -> /images (sync) + /videos (async poll).
    router.include_router(media_gateway_router)
    # Spend controls: monthly budget cap (enforced at reserve) + BYOK consent.
    router.include_router(spend_router)
    # Marketplace usage analytics: cost attribution by model/provider/stage/day.
    router.include_router(usage_insights_router)
    # Clipfarm: read run history / pacing + trigger a render or publish-pacing pass
    # over the otherwise worker-only unattended channel runner.
    router.include_router(series_router)
    # Social inbox: comments/DMs on Menivor-published posts, reply suggestions, replies.
    from app.controllers.v1 import social_inbox as social_inbox_controller

    router.include_router(social_inbox_controller.router)
    # Results: automatic post performance (connected accounts + pasted links).
    from app.domains.performance.router import router as performance_results_router

    router.include_router(performance_results_router)
    # Capture: website / web game / store listing -> promo video -> reel ads.
    from app.domains.capture.router import router as capture_router

    router.include_router(capture_router)
    # Menivor Growth phase 1: free, public App Store / Play audit (no sign-in).
    from app.domains.appaudit.router import router as appaudit_router

    router.include_router(appaudit_router)
    # Design Studio: on-brand static posts, stories, banners and store screenshots.
    from app.domains.design.router import router as design_router

    router.include_router(design_router)
    # Content Month: website -> ~30 viral-format post ideas -> swipe -> carousels + reels.
    from app.domains.content_month.router import router as content_month_router

    router.include_router(content_month_router)
    # Approvals feed: social reply drafts, held posts, budget proposals (Rally reads it).
    from app.domains.approvals.router import router as approvals_router

    router.include_router(approvals_router)
    # Audiobook export (opt-in): chapter text -> MP3 via the Kokoro sidecar (KOKORO_URL).
    from app.domains.audiobook.router import router as audiobook_router

    router.include_router(audiobook_router)
    return router


def build_root_router() -> APIRouter:
    """The mounted router: the full surface, or the client allowlist in production.

    ``MENIVOR_API_SURFACE`` (``allowlist`` | ``full``) picks it; see
    :mod:`app.core.api_surface`. Routers left out of the allowlist stay in the
    tree and stay reachable for staff.
    """
    from app.core.api_surface import apply_surface

    return apply_surface(build_full_router())


root_api_router = build_root_router()
