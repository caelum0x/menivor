import type { Metadata } from "next";
import { CatalogShell } from "@/components/catalog/CatalogShell";
import { HooksBrowser } from "@/components/catalog/HooksBrowser";

export const metadata: Metadata = {
  title: "Hooks",
  description:
    "Browse native opening-line hooks by language to stop the scroll on your reels.",
};

/** Browse the native hook catalog (GET /catalog/hooks). */
export default function HooksPage() {
  return (
    <CatalogShell
      title="Hooks"
      description="Native opening lines that stop the scroll. Switch language, search, and copy a hook to reuse it."
      backHref="/catalog"
      backLabel="Catalog"
    >
      <HooksBrowser />
    </CatalogShell>
  );
}
