import type { Metadata } from "next";
import Link from "next/link";
import { ReportForm } from "./ReportForm";

export const metadata: Metadata = {
  title: "Report a video",
  description:
    "Report a video made with Menivor that impersonates someone, uses your work, exposes private information or breaks our rules.",
  alternates: { canonical: "/legal/report" },
};

/**
 * MN5: public content report. No account needed. Every report becomes a
 * ticket, alerts the team right away, and the video can be paused within 24 h.
 */
export default function ReportPage() {
  return (
    <main className="container py-16">
      <div className="mx-auto max-w-xl space-y-6">
        <div>
          <p className="text-sm font-medium text-muted-foreground">Legal</p>
          <h1 className="text-3xl font-bold tracking-tight">Report a video</h1>
          <p className="mt-3 text-muted-foreground">
            Every video made with Menivor is marked as AI-generated in its file
            data. If one impersonates you, uses your work, shows private
            information or breaks our{" "}
            <Link href="/legal/acceptable-use" className="underline">
              acceptable use policy
            </Link>
            , tell us here. We review every report. When we can find the video
            from your link, it is paused within 24 hours while we look.
          </p>
        </div>
        <ReportForm />
      </div>
    </main>
  );
}
