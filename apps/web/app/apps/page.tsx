import type { Metadata } from "next";
import { AppsShelf, ScenePanel } from "@/src/features/apps-shelf";

export const metadata: Metadata = {
  title: "Apps",
  description: "Single-purpose tools: one input, the price first, one tap to make it.",
};

export default function AppsPage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="mb-2 text-2xl font-semibold">Apps</h1>
      <p className="mb-6 text-sm text-muted-foreground">One input, the price first, one tap to make it.</p>
      <AppsShelf />
      <div className="mt-10">
        <ScenePanel />
      </div>
    </main>
  );
}
