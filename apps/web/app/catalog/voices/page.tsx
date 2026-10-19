import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { VoicesGallery } from "@/components/catalog/VoicesGallery";

export const metadata: Metadata = {
  title: "Voices",
  description:
    "Browse narrator voices with previews and language / accent labels for your reels.",
};

/** Browse the narrator voice gallery (GET /voices). */
export default function VoicesGalleryPage() {
  return (
    <CatalogShell
      title="Voices"
      description="Narrator voices for your reels. Preview a voice, then select it as the narrator. Clone your own under My voices."
      backHref="/catalog"
      backLabel="Catalog"
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/studio/my-voices">My voices</Link>
        </Button>
      }
    >
      <VoicesGallery />
    </CatalogShell>
  );
}
