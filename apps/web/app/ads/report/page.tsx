import type { Metadata } from "next";
import { BarChart3 } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { NetworkReport } from "./_components/NetworkReport";

export const metadata: Metadata = {
  title: "Which network pays off",
  description: "Cost per result for each ad network, with a daily budget split you approve before anything changes.",
  robots: { index: false, follow: false },
};

/** Cross-network report: cost per result per network and the daily budget-split proposal. */
export default function AdsReportPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Which network pays off</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Compare what a result costs on Meta, TikTok and anything you run by hand, then approve a daily budget split
          that leans toward the cheaper network. Small samples are flagged so one lucky day does not move your money.
        </p>
        <NetworkReport />
      </section>
    </main>
  );
}
