import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { TvApprove } from "@/src/features/ott-auth";
import { ottStorefrontLive, ottSurfaceLive } from "@/src/features/ott-player/flags";

type Params = Promise<{ handle: string }>;

export const metadata: Metadata = { title: "Sign in your TV", robots: { index: false } };

/** `/c/[handle]/tv` (MV9): approve the code the Menivor TV app shows. */
export default async function TvSignInPage({ params }: Readonly<{ params: Params }>) {
  if (!ottStorefrontLive() || !ottSurfaceLive("viewers") || !ottSurfaceLive("tv")) notFound();
  const { handle } = await params;
  return (
    <main className="mx-auto max-w-md px-4 py-10">
      <h1 className="mb-4 text-2xl font-semibold">Sign in your TV</h1>
      <TvApprove handle={handle} />
    </main>
  );
}
