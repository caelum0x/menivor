import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ActorsWorkspace } from "@/src/features/ai-actors/ActorsWorkspace";

export const metadata: Metadata = {
  title: "AI actors",
  description: "Original synthetic actors with designed voices and product-holding shots.",
  robots: { index: false, follow: false },
};

/** AI actors library: synthetic people only, faces generated and voices designed, spending behind approvals. */
export default function ActorsPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <ActorsWorkspace />
      </section>
    </main>
  );
}
