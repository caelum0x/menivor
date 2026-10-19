import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { CoverStylesBrowser } from "@/components/catalog/CoverStylesBrowser";

export const metadata: Metadata = {
  title: "Cover styles",
  description:
    "Browse cover / thumbnail style presets for the still frame that sells the click.",
};

/** Browse the cover / thumbnail style catalog (GET /catalog/cover-styles). */
export default function CoverStylesPage() {
  return (
    <CatalogShell
      title="Cover styles"
      description="Thumbnail presets for the still frame that sells the click. Each preview shows the accent and background colours."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <CoverStylesBrowser />
    </CatalogShell>
  );
}
