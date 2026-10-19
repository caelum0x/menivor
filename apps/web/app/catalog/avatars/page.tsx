import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { AvatarsGallery } from "@/components/catalog/AvatarsGallery";

export const metadata: Metadata = {
  title: "Avatars",
  description:
    "Browse presenter avatars — curated talking heads and your own photo→avatars — for your reels.",
};

/** Browse the avatar gallery (GET /avatars). */
export default function AvatarsGalleryPage() {
  return (
    <CatalogShell
      title="Avatars"
      description="Presenter avatars for your reels — curated talking heads plus any photo→avatars you've created. Select one to see its details."
      backHref="/catalog"
      backLabel="Catalog"
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/avatars">Create avatar</Link>
        </Button>
      }
    >
      <AvatarsGallery />
    </CatalogShell>
  );
}
