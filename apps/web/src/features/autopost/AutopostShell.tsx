import * as React from "react";
import Link from "next/link";

import { AppHeader } from "@/components/account/AppHeader";

/** Page frame for every Autopost screen: one heading, one short line, one job. */
export function AutopostShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="min-h-dvh">
      <AppHeader />
      <section className="container py-10">
        <div className="mx-auto max-w-3xl">
          <nav aria-label="Autopost" className="mb-4 flex gap-4 text-sm text-muted-foreground">
            <Link href="/autopost" className="hover:text-foreground">Queue</Link>
            <Link href="/autopost/accounts" className="hover:text-foreground">Accounts</Link>
          </nav>
          <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
          <p className="mb-8 mt-2 max-w-xl text-muted-foreground">{subtitle}</p>
          {children}
        </div>
      </section>
    </main>
  );
}
