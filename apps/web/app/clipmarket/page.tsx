import { UserButton } from "@/components/auth/clerk-safe";
import { Megaphone } from "lucide-react";

import { ClipmarketDashboard } from "@/src/features/clipmarket/ClipmarketDashboard";

/** Clipping marketplace route — brands post CPM campaigns; clippers earn on views. */
export default function ClipmarketPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Megaphone className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Clip marketplace</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-6 text-sm text-muted-foreground">
        Post a CPM campaign and let clippers earn on verified views — fraud-gated payouts, budget-capped.
      </p>
      <ClipmarketDashboard />
    </main>
  );
}
