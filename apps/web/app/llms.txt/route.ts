import { buildLlmsText, llmsFlagsFromEnv } from "@/lib/seo/llms";

/**
 * `menivor.com/llms.txt` (MA2). Generated from plan config and feature flags
 * (see lib/seo/llms.ts): nothing behind an off flag is described.
 */
export function GET() {
  return new Response(buildLlmsText({ flags: llmsFlagsFromEnv() }), {
    headers: {
      "cache-control": "public, max-age=3600, stale-while-revalidate=86400",
      "content-type": "text/plain; charset=utf-8",
    },
  });
}
