"""Paid ads: launch Ad Studio variants as Meta / TikTok campaigns.

Gated until the Menivor Meta and TikTok business apps pass app review: a
platform is enabled only when its ``MENIVOR_<PLATFORM>_APP_ID`` and
``MENIVOR_<PLATFORM>_APP_SECRET`` env keys are set. With the keys absent every
mutating route answers 503 with an explicit "Ads not enabled" reason and the web
surface shows the same state.

Flow: connect an ad account (OAuth, token encrypted in ``provider_keys`` with
``scope='ads'``) -> launch a campaign from ready Ad Studio variants (one ad set
per creative so budget can be allocated per creative) -> sync advances video
processing into live ads and pulls spend / CTR / CPL from the platform ->
optimize re-splits the daily budget with Thompson sampling over each creative's
posterior CTR (or lead rate).

Campaign state lives under ``AdVariant.spec['paid_ads']`` (same pattern as
Ad Studio's publish test) so this round needs no migration.

The HTTP router is imported from ``app.domains.ads.router`` explicitly.
"""
