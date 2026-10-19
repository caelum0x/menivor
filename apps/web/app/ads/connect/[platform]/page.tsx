import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ConnectCallback } from "@/src/features/ads/ConnectCallback";

export const metadata: Metadata = { title: "Connecting ad account", robots: { index: false } };

type SearchParams = Record<string, string | string[] | undefined>;

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : "");

/** OAuth redirect target for Meta (`?code&state`) and TikTok (`?auth_code&state`). */
export default async function ConnectReturnPage({
  params,
  searchParams,
}: {
  params: Promise<{ platform: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { platform } = await params;
  const q = await searchParams;
  const valid = platform === "meta" || platform === "tiktok";
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-xl py-8">
        <h1 className="mb-4 text-xl font-semibold">Connecting ad account</h1>
        {valid ? (
          <ConnectCallback
            platform={platform}
            code={one(q.code) || one(q.auth_code)}
            state={one(q.state)}
            denied={one(q.error) || one(q.error_reason)}
          />
        ) : (
          <p className="text-sm">Unknown ad platform.</p>
        )}
      </section>
    </main>
  );
}
