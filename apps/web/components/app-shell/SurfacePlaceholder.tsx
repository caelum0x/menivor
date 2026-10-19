import type { ComponentType } from "react";
import Link from "next/link";

import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export interface SurfacePlaceholderLink {
  readonly href: string;
  readonly label: string;
}

interface SurfacePlaceholderProps {
  readonly icon: ComponentType<{ className?: string }>;
  readonly title: string;
  readonly summary: string;
  /** What the finished surface will do, in plain words (no promises of numbers). */
  readonly planned: readonly string[];
  /** Existing surfaces that already cover part of the job today. */
  readonly related: readonly SurfacePlaceholderLink[];
}

/**
 * Honest placeholder for a navigation entry whose full surface is still being
 * built: it states what is coming and links to what works today, so the nav
 * never lands on a 404.
 */
export function SurfacePlaceholder({ icon: Icon, title, summary, planned, related }: SurfacePlaceholderProps) {
  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container max-w-3xl py-8">
        <div className="mb-2 flex items-center gap-2">
          <Icon className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">{title}</h1>
        </div>
        <p className="mb-6 text-sm text-muted-foreground">{summary}</p>
        <Card>
          <CardContent className="space-y-4 p-6">
            <p className="text-sm font-medium">This page is in progress. When it ships you will be able to:</p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {planned.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {related.length > 0 ? (
              <div className="space-y-2 pt-2">
                <p className="text-sm font-medium">Available today</p>
                <div className="flex flex-wrap gap-2">
                  {related.map((link) => (
                    <Button key={link.href} asChild variant="outline" size="sm">
                      <Link href={link.href}>{link.label}</Link>
                    </Button>
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
