import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { VoiceManager } from "@/components/voices/VoiceManager";

export const metadata: Metadata = {
  title: "My voices",
  description:
    "Clone your own brand voice from a short sample and manage your cloned voices — then use them as the narrator on any reel.",
};

/** Studio: manage the caller's cloned brand voices (GET/POST/DELETE /voices/mine). */
export default function MyVoicesPage() {
  return (
    <CatalogShell
      title="My voices"
      description="Clone your own voice from a short 30–60 second sample, then pick it as the narrator on any reel. You must confirm you own or are authorized to use the voice before cloning."
      backHref="/catalog/voices"
      backLabel="Voice gallery"
    >
      <VoiceManager />
    </CatalogShell>
  );
}
