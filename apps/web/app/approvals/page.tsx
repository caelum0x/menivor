import type { Metadata } from "next";
import { ClipboardCheck } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ApprovalsFeed } from "./_components/ApprovalsFeed";

export const metadata: Metadata = {
  title: "Approvals",
  description: "One queue for replies, posts and budget changes waiting on you.",
  robots: { index: false, follow: false },
};

/** Approvals route: the unified pending-actions queue (Rally reads the same feed). */
export default function ApprovalsPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-4xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <ClipboardCheck className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Approvals</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Anything hard to undo waits here: reply drafts, held posts, ad budget changes and scheduled designs. Nothing is
          published, sent or spent until you approve it, here or from Rally.
        </p>
        <ApprovalsFeed />
      </section>
    </main>
  );
}
