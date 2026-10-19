import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { CaptionStylesBrowser } from "@/components/catalog/CaptionStylesBrowser";

export const metadata: Metadata = {
  title: "Caption styles",
  description:
    "Browse karaoke caption-style presets with primary and highlight colours to use on any reel.",
};

/** Browse the caption-style catalog (GET /catalog/caption-styles). */
export default function CaptionStylesPage() {
  return (
    <CatalogShell
      title="Caption styles"
      description="Karaoke caption presets. Each preview shows the primary and highlight colours applied to a sample line."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <CaptionStylesBrowser />
    </CatalogShell>
  );
}
