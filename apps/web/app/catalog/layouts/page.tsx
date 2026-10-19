import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { LayoutsBrowser } from "@/components/catalog/LayoutsBrowser";

export const metadata: Metadata = {
  title: "Layouts",
  description:
    "Browse composition layouts that arrange your footage, avatar and captions on a reel.",
};

/** Browse the composition-layout catalog (GET /catalog/layouts). */
export default function LayoutsPage() {
  return (
    <CatalogShell
      title="Layouts"
      description="Composition layouts arrange your footage, avatar and captions. Pick one as a reel's layout."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <LayoutsBrowser />
    </CatalogShell>
  );
}
