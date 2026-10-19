import type { Metadata } from "next";
import Link from "next/link";
import { Mic, Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";

import { Button } from "@/components/ui/button";
import { VoicesCatalog } from "@/src/features/studio-catalog/VoicesCatalog";

export const metadata: Metadata = {
  title: "Voices",
  description:
    "TTS narrator voice catalog and lipsync provider availability — pick a voice before you render.",
};

/**
 * Studio sub-page: voices catalog.
 *
 * Wired to real API endpoints:
 *   GET /voices                        — curated TTS narrator voice catalog
 *   GET /generation/speak/providers    — lipsync provider availability + license class
 *
 * Each voice card links directly into the reel creation flow with the voice
 * pre-selected. Lipsync provider rows show live availability so a creator
 * knows which engine will animate the narration before spending credits.
 */
export default function StudioVoicesPage() {
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Mic className="h-6 w-6 text-primary" aria-hidden />
          <div>
            <h1 className="text-2xl font-semibold">Voices</h1>
            <p className="text-sm text-muted-foreground">
              Narrator voices and lipsync providers — select a voice and see
              which engine will render it.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button asChild size="sm" variant="outline">
            <Link href="/voices">
              <Plus className="mr-1 h-4 w-4" aria-hidden /> My voices
            </Link>
          </Button>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      <VoicesCatalog />
    </main>
  );
}
