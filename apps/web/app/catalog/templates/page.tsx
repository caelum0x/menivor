import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { TemplatesBrowser } from "@/components/catalog/TemplatesBrowser";

export const metadata: Metadata = {
  title: "Templates",
  description:
    "Browse curated viral formats that pre-fill the hook, pacing, captions and audio for a new reel.",
};

/** Browse the curated template catalog (GET /catalog/templates). */
export default function CatalogTemplatesPage() {
  return (
    <CatalogShell
      title="Templates"
      description="Proven viral formats. Each template pre-fills a reel's subject, layout, caption style, language and target length."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <TemplatesBrowser />
    </CatalogShell>
  );
}
