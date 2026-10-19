import * as React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { MenivorMark } from "@/components/brand/MenivorMark";

export const metadata: Metadata = {
  title: "Inbox",
  robots: { index: false, follow: false },
};

/** Social inbox shell: shared Menivor header around the inbox page. */
export default function InboxLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/insights/winners">Winner loop</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/connections">Connections</Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>
      <section className="container py-8">{children}</section>
    </main>
  );
}
