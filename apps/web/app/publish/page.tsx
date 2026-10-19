import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { Share2, Wand2 } from "lucide-react";

import { NativePublish } from "@/src/features/publishing/NativePublish";

/** Native publishing route — post a rendered job to a social platform. */
export default async function PublishPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{ job?: string | string[] }>;
}>) {
  const query = await searchParams;
  const rawJob = Array.isArray(query.job) ? query.job[0] : query.job;
  return (
    <main className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Share2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Native publish</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>
      <p className="mb-2 text-sm text-muted-foreground">
        Post a finished render straight to a connected platform — pick a reel, choose where it goes, and ship it.
      </p>
      <p className="mb-6 text-sm">
        <Link
          href="/hook-finder"
          className="inline-flex items-center gap-1.5 font-medium text-primary underline-offset-4 hover:underline"
        >
          <Wand2 className="h-4 w-4" aria-hidden />
          Not sure which caption to lead with? Rank your hooks first
        </Link>
      </p>
      <NativePublish initialJobId={(rawJob || "").trim()} />
    </main>
  );
}
