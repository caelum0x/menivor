import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AdFatigue } from "@/src/features/ad-fatigue";

export const metadata: Metadata = {
  title: "Ad fatigue",
  description: "See which ads are wearing out and make fresh variations behind approval.",
  robots: { index: false, follow: false },
};

export default function AdFatiguePage() {
  return (
    <main className="min-h-dvh" data-testid="ad-fatigue-page">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <AdFatigue />
      </section>
    </main>
  );
}
