import type { Metadata } from "next";
import Link from "next/link";
import { Scissors, Sparkles } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { ClipsCatalog } from "@/src/features/studio-catalog/ClipsCatalog";

export const metadata: Metadata = {
  title: "Clips",
  description:
    "Long-to-short clipping jobs and produced clips. Browse completed jobs, view individual clips, and promote any clip into a reel draft in one click.",
};

/**
 * Studio sub-page: clipping jobs library.
 *
 * Wired to the real clipping domain:
 *   GET  /clipping/jobs                        — caller's jobs (newest first)
 *   GET  /clipping/jobs/{id}/clips             — clips produced by a job
 *   POST /clipping/clips/{clip_id}/promote     — promote a clip → reel draft
 *
 * Completed jobs can be expanded to browse their individual clips. A "Promote
 * to reel" button calls the promote endpoint and surfaces the ready-to-submit
 * draft with a link into the creation flow.
 */
export default function StudioClipsPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Scissors className="h-6 w-6 text-primary" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Clips</h1>
            <p className="text-sm text-muted-foreground">
              Long-to-short clipping jobs — view produced clips and promote any
              clip into a reel draft.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild size="sm">
            <Link href="/new">
              <Sparkles className="mr-1 h-4 w-4" aria-hidden /> New reel
            </Link>
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <ClipsCatalog />
    </main>
  );
}
