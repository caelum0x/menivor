import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ReviewQueue } from "@/src/features/review-queue";

export const metadata: Metadata = {
  title: "Review",
  description: "Approve, reject or regenerate new creatives, one at a time.",
  robots: { index: false, follow: false },
};

/** Swipe-to-approve review queue for generated creatives (feeds Approvals). */
export default function ReviewPage() {
  return (
    <main className="min-h-dvh" data-testid="review-page">
      <AppTopBar />
      <section className="container max-w-6xl py-6">
        <ReviewQueue />
      </section>
    </main>
  );
}
