import type { Metadata } from "next";
import { UserButton } from "@/components/auth/clerk-safe";
import { Wand2 } from "lucide-react";

import { HookFinder } from "@/components/growth/HookFinder";

export const metadata: Metadata = {
  title: "Winning Hook Finder",
  description:
    "Paste several hook or caption variants for a reel and see them ranked by scroll-stopping strength — winner crowned, with per-hook slop and policy-risk signals plus the recommended angle.",
};

/**
 * Winning Hook Finder — a creator drops in the hook/caption variants they are
 * weighing for a reel and gets them ranked by Jev (via
 * `POST /api/v1/growth/rank-hooks`): the winner is crowned, every variant carries
 * strength / slop / policy-risk badges, and the recommended angle is surfaced so
 * the best opener can go straight into the reel/publishing flow.
 */
export default function HookFinderPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wand2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Winning Hook Finder</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Weighing a few opening lines for your next reel? Paste them below and let Jev rank
        them by scroll-stopping strength — the winner is crowned, and every variant gets
        strength, slop, and policy-risk signals plus its attention angle so you can post the
        one most likely to land.
      </p>
      <HookFinder />
    </main>
  );
}
