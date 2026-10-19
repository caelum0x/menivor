import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { VeryTimeWizard } from "@/src/features/very-time";

export const metadata: Metadata = {
  title: "Very ___ Time",
  description:
    "Type one place word and one everyday ritual and get a short vertical video that ends on \"You met me at a very ___ time in my life.\"",
};

export default function VeryTimePage() {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-3xl py-10">
        <h1 className="text-3xl font-bold tracking-tight">Very ___ Time</h1>
        <p className="mb-8 mt-2 max-w-xl text-muted-foreground">
          One word, one everyday ritual, one look. You see the five beats and the price before anything starts.
        </p>
        <VeryTimeWizard />
      </section>
    </main>
  );
}
