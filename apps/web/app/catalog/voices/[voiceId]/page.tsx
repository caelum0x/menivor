import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { VoiceDetail } from "@/components/catalog/VoiceDetail";

interface PageProps {
  /** Next.js 15 passes dynamic params as a Promise. */
  readonly params: Promise<{ voiceId: string }>;
}

export const metadata: Metadata = {
  title: "Voice",
  description: "Narrator voice details.",
};

/** Detail view for one voice (resolved from GET /voices by id). */
export default async function VoiceDetailPage({ params }: PageProps) {
  const { voiceId } = await params;
  const decoded = decodeURIComponent(voiceId);

  return (
    <CatalogShell
      title="Voice"
      description="Everything about this narrator voice, with a preview and where to use it."
      backHref="/catalog/voices"
      backLabel="Voices"
    >
      <VoiceDetail voiceId={decoded} />
    </CatalogShell>
  );
}
