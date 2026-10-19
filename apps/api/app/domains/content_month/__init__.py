"""Content Month: a website URL -> ~30 post ideas in proven viral formats -> swipe -> render.

:mod:`.service` reads the site (``brand_agent.site_analysis``) into a
:class:`.brief.SiteBrief`, writes one idea per slot of a format rotation
(:mod:`.formats`) with the shared LLM route (Relay on Anthropic credits) and a
deterministic floor (:mod:`.rules`). Kept carousels render server-side into
branded slides (PNG pages, a PDF and a slideshow MP4; :mod:`.slides`,
:mod:`.raster`) and open in Design Studio; kept reels go to the reel pipeline
with the request built in :mod:`.reel`. Tables: migration ``c3e5a7b9d1f2``.
"""
