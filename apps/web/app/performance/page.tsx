import type { Metadata } from "next";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { ResultsView } from "@/src/features/results";

export const metadata: Metadata = {
  title: "Results",
  description: "Which hooks and styles win, from the real numbers of every reel you post.",
  robots: { index: false },
};

/** `/performance` — the Results destination: winners first, numbers read automatically. */
export default function ResultsPage() {
  return (
    <main className="min-h-dvh pb-24 sm:pb-10">
      <AppTopBar />
      <section className="container max-w-3xl py-8">
        <h1 className="mb-6 text-3xl font-bold tracking-tight">Results</h1>
        <ResultsView />
      </section>
    </main>
  );
}
