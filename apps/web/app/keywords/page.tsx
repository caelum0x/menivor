import type { Metadata } from "next";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { KeywordTrackerView } from "@/src/features/keyword-tracker";

export const metadata: Metadata = {
  title: "Keyword tracker",
  description: "Daily App Store top-50 rank per keyword, with 7/30-day change and history.",
  robots: { index: false },
};

/** `/keywords` — Menivor Growth phase 2: the daily App Store keyword rank tracker. */
export default function KeywordTrackerPage() {
  return (
    <main className="min-h-dvh pb-24 sm:pb-10">
      <AppTopBar />
      <section className="container max-w-3xl py-8">
        <h1 className="mb-6 text-3xl font-bold tracking-tight">Keyword tracker</h1>
        <KeywordTrackerView />
      </section>
    </main>
  );
}
