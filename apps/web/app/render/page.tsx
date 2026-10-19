import type { Metadata } from "next";
import { Cpu } from "lucide-react";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { RenderJobPanel } from "@/src/features/render/RenderJobPanel";

export const metadata: Metadata = {
  title: "AI video render",
  description: "Start a wallet-metered AI video render and find every past render in one place.",
};

/** Async-GPU render route — start + poll a wallet-metered render (success-only billing). */
export default function RenderPage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-2xl py-8">
        <div className="mb-6 flex items-center gap-2">
          <Cpu className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">AI video render</h1>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">
          Start an async model render. Your wallet is held on submit and charged only when it
          completes. Every render you start is listed below, on any device you sign in from.
        </p>
        <RenderJobPanel />
      </section>
    </main>
  );
}
