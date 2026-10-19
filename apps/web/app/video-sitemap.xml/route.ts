import { loadFeed, videoSitemapXml } from "@/lib/seo/megaphone/feed";

export const dynamic = "force-dynamic";

/** Google video sitemap for the Made with Menivor gallery (listed in robots.txt). */
export async function GET(): Promise<Response> {
  const videos = await loadFeed();
  return new Response(videoSitemapXml(videos), {
    headers: {
      "content-type": "application/xml; charset=utf-8",
      "cache-control": "public, max-age=3600, stale-while-revalidate=86400",
    },
  });
}
