import type { Metadata } from "next";
import { ScanLine } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CaptureHome } from "./_components/CaptureHome";

export const metadata: Metadata = {
  title: "Capture",
  description: "Turn a website, web game or app store listing into a promo video, then into ads.",
  robots: { index: false, follow: false },
};

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * Capture: paste a website, web game, App Store or Google Play link and get a
 * recorded promo video in 9:16 and 16:9, then turn it into reels and ads.
 * `?url=` prefills the link; nothing runs until the user submits.
 */
export default async function CapturePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const raw = Array.isArray(params.url) ? params.url[0] : params.url;
  const initialUrl = typeof raw === "string" && /^https?:\/\//i.test(raw) ? raw.slice(0, 2048) : "";
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <ScanLine className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Capture</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Paste a link to a website, a playable web game, an App Store app or a Google Play app. Menivor records a
          smooth scroll-through or real gameplay, or builds a slideshow from the store listing, in the formats you
          pick. Then turn the recording into captioned, narrated or avatar ads that run through the normal reel
          pipeline.
        </p>
        <CaptureHome initialUrl={initialUrl} />
      </section>
    </main>
  );
}
