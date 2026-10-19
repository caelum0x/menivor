import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { LinearWatch, onNow } from "@/src/features/ott-linear";
import { ottSurfaceLive } from "@/src/features/ott-player/flags";

type Params = Promise<{ slug: string }>;

export async function generateMetadata({ params }: Readonly<{ params: Params }>): Promise<Metadata> {
  if (!ottSurfaceLive("fast")) return {};
  const { slug } = await params;
  const view = await onNow(slug);
  return view ? { title: view.name } : {};
}

/** `/linear/[slug]` (MV15): a creator's Always-on channel. */
export default async function LinearPage({ params }: Readonly<{ params: Params }>) {
  if (!ottSurfaceLive("fast")) notFound();
  const { slug } = await params;
  const view = await onNow(slug);
  if (!view) notFound();
  return (
    <main className="mx-auto max-w-4xl px-4 py-6">
      <h1 className="mb-3 text-2xl font-semibold">{view.name}</h1>
      <LinearWatch view={view} />
    </main>
  );
}
