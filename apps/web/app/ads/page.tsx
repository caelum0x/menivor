import type { Metadata } from "next";
import { BadgeDollarSign } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AdsHome } from "@/src/features/ads/AdsHome";

export const metadata: Metadata = {
  title: "Paid ads",
  description: "Run your Ad Studio videos as Meta and TikTok ads with a daily budget that follows the winning creative.",
};

/** Paid ads: connect ad accounts, launch campaigns from Ad Studio, read spend, CTR and cost per lead. */
export default function AdsPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <BadgeDollarSign className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Paid ads</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Launch finished Ad Studio videos as Meta or TikTok ads. Each video gets its own ad set, and the daily budget
          shifts toward the ads with the best click-through or lead rate as results come in.
        </p>
        <AdsHome />
      </section>
    </main>
  );
}
