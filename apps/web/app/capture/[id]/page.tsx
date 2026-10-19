import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { CaptureDetailView } from "../_components/CaptureDetailView";

export const metadata: Metadata = {
  title: "Capture",
  robots: { index: false, follow: false },
};

/** One capture: status, recorded videos, screenshots and "make ads". */
export default async function CaptureDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">{id ? <CaptureDetailView captureId={id} /> : null}</section>
    </main>
  );
}
