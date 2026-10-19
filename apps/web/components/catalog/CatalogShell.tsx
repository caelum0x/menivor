import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Plus } from "lucide-react";
import { UserButton } from "@/components/auth/clerk-safe";
import { Button } from "@/components/ui/button";
import { MenivorMark } from "@/components/brand/MenivorMark";

export interface CatalogShellProps {
  title: string;
  description: string;
  /** Optional back link (label + href) shown above the title. */
  backHref?: string;
  backLabel?: string;
  /** Optional actions rendered on the right of the title row. */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

/**
 * Shared page chrome for every catalog/studio route: the ReelForge top bar
 * plus a titled section header. Presentational only — safe to render from a
 * server component.
 */
export function CatalogShell({
  title,
  description,
  backHref,
  backLabel,
  actions,
  children,
}: Readonly<CatalogShellProps>) {
  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild size="sm">
              <Link href="/new">
                <Plus className="size-4" aria-hidden /> New reel
              </Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-10">
        {backHref && (
          <Link
            href={backHref}
            className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {backLabel ?? "Back"}
          </Link>
        )}
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-2xl">
            <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
            <p className="mt-2 text-muted-foreground">{description}</p>
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>

        {children}
      </section>
    </main>
  );
}
