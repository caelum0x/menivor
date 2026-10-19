import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CampaignView } from "@/src/features/ads/CampaignView";

export const metadata: Metadata = { title: "Paid campaign" };

/** One paid campaign: report, winner loop and controls. */
export default async function CampaignPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        {/^[a-f0-9]{16}$/.test(key) ? <CampaignView campaignKey={key} /> : <p className="text-sm">Campaign not found.</p>}
      </section>
    </main>
  );
}
