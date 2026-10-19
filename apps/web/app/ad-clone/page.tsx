import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AdCloneWizard } from "@/src/features/ad-clone";

export const metadata: Metadata = {
  title: "Ad Clone",
  description:
    "Paste a winning ad and get your own version for your product: same hook, shot structure and pacing, your characters and new lines.",
};

export default function AdClonePage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-3xl py-10">
        <h1 className="text-3xl font-bold tracking-tight">Ad Clone</h1>
        <p className="mb-8 mt-2 max-w-xl text-muted-foreground">
          Paste a winning ad, pick your product, and get your own versions with the price on every engine before
          anything renders.
        </p>
        <AdCloneWizard />
      </section>
    </main>
  );
}
