import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { AgentWorkspace } from "@/src/features/brand-agent/AgentWorkspace";

export const metadata: Metadata = {
  title: "Agent",
  description: "Set up your brand from your website, then make scripts, hooks, images and videos with an agent.",
  robots: { index: false, follow: false },
};

/** Brand Agent: brand setup from a website, brand memory, and creatives behind approvals. */
export default function AgentPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <AgentWorkspace />
      </section>
    </main>
  );
}
