import type { Metadata } from "next";
import { Store } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CatalogHome } from "./_components/CatalogHome";

export const metadata: Metadata = {
  title: "Import a store catalog",
  description: "Pull products from your online store into Ad Studio.",
  robots: { index: false, follow: false },
};

/** Store catalog import: Shopify / WooCommerce public feed -> Ad Studio projects. */
export default function CatalogImportPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <Store className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Import a store catalog</h1>
        </div>
        <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
          Paste your store address. Menivor reads the store&apos;s public product list with titles,
          prices and images. Pick the products you want to advertise and each one becomes an Ad Studio project with
          drafted ad angles.
        </p>
        <CatalogHome />
      </section>
    </main>
  );
}
