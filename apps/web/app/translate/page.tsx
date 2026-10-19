import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { TranslateWorkspace } from "@/src/features/lipsync-translate/TranslateWorkspace";

export const metadata: Metadata = {
  title: "Lip-sync translate",
  description: "Translate your videos with your AI actors' designed voices, lip-synced and captioned.",
  robots: { index: false, follow: false },
};

export default function TranslatePage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <TranslateWorkspace />
      </section>
    </main>
  );
}
