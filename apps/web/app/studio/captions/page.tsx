import type { Metadata } from "next";
import Link from "next/link";
import { Type } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { CaptionsBrowser } from "@/src/features/studio-catalog/CaptionsBrowser";

export const metadata: Metadata = {
  title: "Captions",
  description:
    "Per-platform caption safe-zones and links to the hook-score, A/B, and caption-style tools.",
};

/**
 * Studio sub-page: captions.
 *
 * Wired to the real captions domain:
 *   GET /captions/safezones  — per-platform caption placement (font size, margin, Y-fraction)
 *
 * Links out to the caption style registry (/captions), hook lab (/hook-lab),
 * and A/B lab (/ab-lab) for deeper tuning.
 */
export default function StudioCaptionsPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Type className="h-6 w-6 text-primary" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Captions</h1>
            <p className="text-sm text-muted-foreground">
              Per-platform safe-zones and caption tools — from the renderer the
              pipeline uses.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild size="sm" variant="outline">
            <Link href="/captions">Caption styles</Link>
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <CaptionsBrowser />
    </main>
  );
}
