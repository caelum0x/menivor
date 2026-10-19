import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { PlanView } from "@/components/month/PlanView";

export const metadata: Metadata = {
  title: "Your month of posts",
  robots: { index: false, follow: false },
};

export default async function MonthPlanPage({ params }: Readonly<{ params: Promise<{ id: string }> }>) {
  const { id } = await params;
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-3xl py-8">
        <PlanView planId={id} />
      </section>
    </main>
  );
}
