import { UserButton } from "@/components/auth/clerk-safe";
import { Wand2 } from "lucide-react";

import { MediaGatewayNav } from "@/src/features/media-gateway/MediaGatewayNav";
import { UsageDashboard } from "@/src/features/media-gateway/UsageDashboard";

/** Media gateway credits + usage — spendable balance + spend-by-model. */
export default function MediaUsagePage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wand2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Media gateway</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <MediaGatewayNav />
      <UsageDashboard />
    </main>
  );
}
