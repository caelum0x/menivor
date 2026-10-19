import type { Metadata } from "next";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { LaunchForm } from "@/src/features/ads/LaunchForm";

export const metadata: Metadata = { title: "New paid campaign" };

type SearchParams = Record<string, string | string[] | undefined>;

/** Launch a campaign; `?project=<id>` preselects an Ad Studio project. */
export default async function NewCampaignPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const raw = params.project;
  const projectId = typeof raw === "string" && /^[A-Za-z0-9]{1,32}$/.test(raw) ? raw : "";
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-8">
        <h1 className="mb-6 text-2xl font-semibold">New paid campaign</h1>
        <LaunchForm initialProjectId={projectId} />
      </section>
    </main>
  );
}
