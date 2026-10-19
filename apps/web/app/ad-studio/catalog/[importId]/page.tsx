import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ImportDetail } from "../_components/ImportDetail";

export const metadata: Metadata = { title: "Store import", robots: { index: false, follow: false } };

/** One store import: its products, ready to send to Ad Studio. */
export default async function StoreImportPage({ params }: { params: Promise<{ importId: string }> }) {
  const { importId } = await params;
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        {/^[a-f0-9]{32}$/.test(importId) ? (
          <ImportDetail importId={importId} />
        ) : (
          <p className="text-sm">Import not found.</p>
        )}
      </section>
    </main>
  );
}
