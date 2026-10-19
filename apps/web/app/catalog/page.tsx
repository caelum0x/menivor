import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { CatalogIndex } from "@/components/catalog/CatalogIndex";

export const metadata: Metadata = {
  title: "Catalog",
  description:
    "Browse every creative building block — templates, caption styles, layouts, music, hooks, cover styles, avatars and voices — that powers your reels.",
};

/** Catalog hub: links to every browsable creative-asset catalog. */
export default function CatalogPage() {
  return (
    <CatalogShell
      title="Catalog"
      description="Browse the creative building blocks behind every reel — templates, caption styles, layouts, music, hooks, cover styles, avatars and voices."
    >
      <CatalogIndex />
    </CatalogShell>
  );
}
