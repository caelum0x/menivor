import type { Metadata } from "next";
import { Workflow } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { WorkflowCanvas } from "@/src/features/workflow-canvas";

export const metadata: Metadata = {
  title: "Workflows",
  description: "Chain brief, script, images, video, captions, approve and publish, then run it on a schedule.",
  robots: { index: false, follow: false },
};

/** Workflow canvas: a saved chain of steps; spending and publishing always wait for approval. */
export default function WorkflowsPage() {
  return (
    <main className="min-h-dvh" data-testid="workflows-page">
      <AppTopBar />
      <section className="container max-w-7xl py-6">
        <div className="mb-1 flex items-center gap-2">
          <Workflow className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Workflows</h1>
        </div>
        <p className="mb-5 max-w-3xl text-sm text-muted-foreground">
          Connect the steps once, then run them now or every week. Images, videos and posts wait for your approval.
        </p>
        <WorkflowCanvas />
      </section>
    </main>
  );
}
