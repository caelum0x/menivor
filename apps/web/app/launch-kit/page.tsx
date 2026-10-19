import type { Metadata } from "next";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { LaunchKitView } from "@/src/features/launch-kit";

export const metadata: Metadata = {
  title: "Launch kit",
  description: "First-100-users tooling: launch directories, pain-point threads, competitor backlinks, and the 10-step checklist.",
  robots: { index: false },
};

/** `/launch-kit` — Menivor Growth phase 3: first-100-users / launch-maxxing tooling. */
export default function LaunchKitPage() {
  return (
    <main className="min-h-dvh pb-24 sm:pb-10">
      <AppTopBar />
      <section className="container max-w-3xl py-8">
        <h1 className="mb-6 text-3xl font-bold tracking-tight">Launch kit</h1>
        <LaunchKitView />
      </section>
    </main>
  );
}
