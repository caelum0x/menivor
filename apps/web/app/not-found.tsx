import Link from "next/link";

import { Button } from "@/components/ui/button";

/** Branded 404 for any route that does not exist (or a record that was removed). */
export default function NotFound() {
  return (
    <main className="container flex min-h-dvh flex-col items-start justify-center gap-4 py-20">
      <p className="kicker text-muted-foreground">404</p>
      <h1 className="text-3xl font-bold tracking-tight">This page doesn&apos;t exist</h1>
      <p className="max-w-lg text-muted-foreground">
        The link may be out of date, or the reel, project or page was removed.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href="/">Back to Menivor</Link>
        </Button>
        <Button asChild variant="outline">
          <Link href="/reels">My reels</Link>
        </Button>
      </div>
    </main>
  );
}
