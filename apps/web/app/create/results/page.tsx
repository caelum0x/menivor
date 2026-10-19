import type { Metadata } from "next";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { VariantResults, parseJobIds } from "@/src/features/create-compose";

export const metadata: Metadata = {
  title: "Your 3 reels",
  robots: { index: false, follow: false },
};

/**
 * `/create/results?jobs=a,b,c` — live per-variant progress, then the results
 * with pick / edit / publish / download. Job ids are validated here and every
 * job is fetched owner-scoped by the API, so a shared link shows nothing to
 * anyone but the owner.
 */
export default async function CreateResultsPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{ jobs?: string | string[] }>;
}>) {
  const query = await searchParams;
  const jobIds = parseJobIds(query.jobs);
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-6xl py-10">
        <h1 className="sr-only">Your reels</h1>
        <VariantResults jobIds={jobIds} />
      </section>
    </main>
  );
}
