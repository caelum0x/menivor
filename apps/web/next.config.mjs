import path from "node:path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Wave P PM2.5: the OTT player core ships as TypeScript source in packages/ott-player.
  transpilePackages: ["@menivor/ott-player"],
  // Deploys to Cloudflare Workers via @opennextjs/cloudflare, which consumes
  // Next's standalone server output.
  output: "standalone",
  // Trace from the monorepo root so hoisted workspace deps (notably `next`
  // itself, which npm hoists to the root node_modules) are fully copied into
  // the standalone bundle. This nests the output under `apps/web/`, which
  // OpenNext resolves via packagePath once it detects the monorepo root.
  outputFileTracingRoot: path.resolve(process.cwd(), "../.."),
  // Image Optimization API is unsupported on the Workers runtime; serve images
  // unoptimized and allow remote avatar/preview thumbnails from any HTTPS origin.
  images: {
    unoptimized: true,
    remotePatterns: [{ protocol: "https", hostname: "**" }],
  },
  // Surface the API base at build time for the typed client in lib/api.ts.
  env: {
    NEXT_PUBLIC_API_BASE:
      process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080/api/v1",
  },
  // Retired marketing URLs. `permanent: true` answers 308 so search engines
  // move the old URL's signal to the new page.
  async redirects() {
    const home = "/";
    return [
      { source: "/wolfcut", destination: "/editor", permanent: true },
      { source: "/wolfcut/:path*", destination: "/editor", permanent: true },
      { source: "/compare", destination: home, permanent: true },
      { source: "/compare/:path*", destination: home, permanent: true },
      { source: "/vs/:path*", destination: home, permanent: true },
      { source: "/alternatives", destination: home, permanent: true },
      { source: "/alternatives/:path*", destination: home, permanent: true },
      { source: "/pricing/compare", destination: "/pricing", permanent: true },
      { source: "/templates", destination: "/create", permanent: true },
      { source: "/templates/:path*", destination: "/create", permanent: true },
      // Guessable / legacy URLs that 404'd: send people to the real page.
      { source: "/videos", destination: "/reels", permanent: true },
      { source: "/videos/:id", destination: "/reels/:id", permanent: true },
      { source: "/results", destination: "/reels", permanent: true },
      { source: "/help", destination: "/contact", permanent: true },
      { source: "/support", destination: "/contact", permanent: true },
      { source: "/legal", destination: "/terms", permanent: true },
      { source: "/legal/terms", destination: "/terms", permanent: true },
      { source: "/legal/privacy", destination: "/privacy", permanent: true },
      { source: "/legal/refunds", destination: "/refunds", permanent: true },
      { source: "/acceptable-use", destination: "/legal/acceptable-use", permanent: true },
      { source: "/aup", destination: "/legal/acceptable-use", permanent: true },
    ];
  },
  async headers() {
    const privatePrefixes = [
      "/account",
      "/admin",
      "/billing",
      "/connections",
      "/dashboard",
      "/insights",
      "/new",
      "/reels",
      "/settings",
      "/studio",
      "/wallet",
      "/workspace",
    ];

    return privatePrefixes.map((source) => ({
      source: `${source}/:path*`,
      headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }],
    }));
  },
};

export default nextConfig;
