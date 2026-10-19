"use client";

import * as React from "react";
import Link from "next/link";
import { ImageOff, Megaphone } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { listAdProjects, type ProjectSummary } from "./api";
import { LoadError, useRequestOptions } from "./shared";

/** The caller's saved Ad Studio projects, newest first. */
export function ProjectList() {
  const requestOptions = useRequestOptions();
  const [projects, setProjects] = React.useState<ProjectSummary[] | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [attempt, setAttempt] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listAdProjects(await requestOptions());
        if (!cancelled) {
          setProjects(data.projects);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestOptions, attempt]);

  const retry = () => {
    setError(null);
    setProjects(null);
    setAttempt((n) => n + 1);
  };

  return (
    <section aria-labelledby="ad-projects-heading" className="space-y-3">
      <h2 id="ad-projects-heading" className="text-lg font-semibold">
        Your ad projects
      </h2>
      {error ? (
        <LoadError error={error} onRetry={retry} fallback="We couldn't load your ad projects. Please try again." />
      ) : null}
      {projects === null && !error ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      ) : null}
      {projects && projects.length === 0 ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Megaphone className="h-4 w-4" aria-hidden />
          No ad projects yet. Paste a product link above to start one.
        </p>
      ) : null}
      {projects && projects.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link key={p.id} href={`/ad-studio/${p.id}`} className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Card className="h-full transition-colors hover:bg-secondary/40">
                <CardContent className="flex gap-3 p-3">
                  {p.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- presigned media URL
                    <img src={p.thumbnail_url} alt="" className="h-20 w-20 shrink-0 rounded-md border border-border object-contain" />
                  ) : (
                    <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-md border border-border">
                      <ImageOff className="h-5 w-5 text-muted-foreground" aria-hidden />
                    </div>
                  )}
                  <div className="min-w-0">
                    <p className="line-clamp-2 font-medium">{p.title}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {p.done_count} of {p.variant_count} ads ready
                      {p.created_at ? ` · ${new Date(p.created_at).toLocaleDateString()}` : ""}
                    </p>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}
