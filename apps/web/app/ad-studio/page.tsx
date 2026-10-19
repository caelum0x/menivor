import type { Metadata } from "next";
import { Megaphone } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AdStudioHome } from "@/src/features/ad-studio/AdStudioHome";
import { parseAdStudioPrefill } from "@/src/features/ad-studio/prefill";

export const metadata: Metadata = {
  title: "Ad Studio",
  description:
    "Paste a product link and get ready-to-post product video ads in 9:16, 1:1 and 16:9.",
};

type SearchParams = Record<string, string | string[] | undefined>;

/**
 * Ad Studio — product URL to ad angles to rendered product video ads.
 * Accepts `?url=&offer=&audience=&source=rally` deep links (Rally bridge) to
 * prefill the form; nothing runs until the user submits.
 */
export default async function AdStudioPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const prefill = parseAdStudioPrefill(await searchParams);
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <Megaphone className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Ad Studio</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Paste a product link. Menivor reads the product page, drafts hooks, pain points, proof, offers
          and calls to action from what it finds, then renders product showcase, before/after and UGC
          avatar ads in every aspect ratio you need.
        </p>
        <AdStudioHome prefill={prefill} />
      </section>
    </main>
  );
}
