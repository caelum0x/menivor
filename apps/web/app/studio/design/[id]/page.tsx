import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { DesignEditor } from "@/components/design/DesignEditor";

export const metadata: Metadata = {
  title: "Edit design",
  robots: { index: false, follow: false },
};

export default async function DesignEditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-7xl py-6">
        <DesignEditor id={id} />
      </section>
    </main>
  );
}
