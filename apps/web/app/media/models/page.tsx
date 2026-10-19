import { UserButton } from "@/components/auth/clerk-safe";
import { Wand2 } from "lucide-react";

import { MediaGatewayNav } from "@/src/features/media-gateway/MediaGatewayNav";
import { ModelsBrowser } from "@/src/features/media-gateway/ModelsBrowser";

/** Media gateway model catalog — every image + video model, one key + balance. */
export default function MediaModelsPage() {
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
      <ModelsBrowser />
    </main>
  );
}
