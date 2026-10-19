import { defineCloudflareConfig } from "@opennextjs/cloudflare";

// Menivor deliberately uses the adapter's in-memory/dummy incremental cache.
// The marketing surface is statically rendered and the authenticated app is
// personalized + API-backed, so an R2 incremental cache would add cost and
// invalidation complexity without improving correctness. Add an R2-backed
// `incrementalCache` here later if ISR/data-cache persistence is needed.
// Docs: https://opennext.js.org/cloudflare/caching
export default defineCloudflareConfig({
  routePreloadingBehavior: "none",
});
