import type { Metadata } from "next";
import { EnhancePanel } from "@/src/features/enhance";

export const metadata: Metadata = {
  title: "Sharper and smoother",
  description: "Make a finished reel's cover four times sharper, or upscale and smooth the video, priced first.",
};

export default function EnhancePage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-semibold">Sharper and smoother</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        A sharper cover is free a few times a day. Video work shows its price in AI-video credits before it starts.
      </p>
      <EnhancePanel />
    </main>
  );
}
