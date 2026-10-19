import { UserButton } from "@/components/auth/clerk-safe";
import { TrendingUp } from "lucide-react";

import { TrendsExplorer } from "@/src/features/trends/TrendsExplorer";
import { TrendsFeed } from "@/src/features/trends/TrendsFeed";

/** Trends explorer route — live ranked feed + manual opportunity ranker. */
export default function TrendsPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Trends explorer</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Watch the live ranked feed, or paste raw trend counts to rank them by velocity,
        saturation, and opportunity — with a recommend signal for what to make next.
      </p>
      <div className="space-y-6">
        <TrendsFeed />
        <TrendsExplorer />
      </div>
    </main>
  );
}
