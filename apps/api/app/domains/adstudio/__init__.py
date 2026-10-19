"""Ad Studio: product URL -> ad angles -> rendered product ad variants.

Paste a Shopify / Trendyol / Amazon / generic product URL (or enter the product
manually), extract title, price, images, bullets and reviews behind an SSRF
guard, draft 3-5 ad angles (hook, pain, proof, offer, CTA) with the configured
LLM or a deterministic template, then render product-showcase and before/after
ads locally with FFmpeg and hand UGC-avatar ads to the reel pipeline, in
9:16 / 1:1 / 16:9, with a batch export manifest.

The HTTP router is imported explicitly from ``app.domains.adstudio.router``
(not re-exported here) so the controller can import this package's services
without an import cycle.
"""
