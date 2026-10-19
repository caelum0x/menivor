import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CompetitorTracker } from "@/src/features/competitors";

export const metadata: Metadata = {
  title: "Competitor ads",
  description: "Track competitor ads from the official Meta and TikTok ad libraries and clone what works.",
  robots: { index: false, follow: false },
};

export default function CompetitorsPage() {
  return (
    <main className="min-h-dvh" data-testid="competitors-page">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <CompetitorTracker />
      </section>
    </main>
  );
}
