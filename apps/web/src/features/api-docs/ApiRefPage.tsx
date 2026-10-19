"use client";

import * as React from "react";
import { BookOpen, ChevronRight, Lock, Globe } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { useTranslations } from "@/lib/i18n/context";
import {
  API_CATALOG,
  CATALOG_GROUPS,
  GROUP_LABELS,
  type EndpointEntry,
  type EndpointParam,
} from "@/lib/api-catalog";

const METHOD_CLASSES: Record<string, string> = {
  GET: "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
  POST: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  DELETE: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
  PATCH: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

function MethodBadge({ method }: Readonly<{ method: string }>) {
  const cls = METHOD_CLASSES[method] ?? "bg-muted text-muted-foreground";
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-xs font-semibold ${cls}`}
    >
      {method}
    </span>
  );
}

function ParamTable({
  params,
}: Readonly<{ params: EndpointParam[] }>) {
  const t = useTranslations();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th className="pb-2 pr-3 font-medium">Name</th>
            <th className="pb-2 pr-3 font-medium">In</th>
            <th className="pb-2 pr-3 font-medium">Type</th>
            <th className="pb-2 pr-3 font-medium">Required</th>
            <th className="pb-2 font-medium">Description</th>
          </tr>
        </thead>
        <tbody>
          {params.map((p) => (
            <tr key={p.name} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-3 font-mono">{p.name}</td>
              <td className="py-2 pr-3 capitalize text-muted-foreground">
                {p.kind}
              </td>
              <td className="py-2 pr-3 font-mono text-muted-foreground">
                {p.type}
              </td>
              <td className="py-2 pr-3">
                {p.required ? (
                  <span className="rounded bg-destructive/10 px-1 py-0.5 text-destructive">
                    {t("apiDocs.required")}
                  </span>
                ) : (
                  <span className="text-muted-foreground">
                    {t("apiDocs.optional")}
                  </span>
                )}
              </td>
              <td className="py-2 text-muted-foreground">
                {p.description}
                {p.example && (
                  <span className="ml-1 font-mono text-foreground">
                    e.g. {p.example}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EndpointCard({
  entry,
  open,
  onToggle,
}: Readonly<{
  entry: EndpointEntry;
  open: boolean;
  onToggle: () => void;
}>) {
  const t = useTranslations();
  return (
    <Card id={entry.id.replace(/\s+/g, "-")}>
      <CardContent className="p-0">
        {/* Summary row */}
        <button
          type="button"
          className="flex w-full items-center gap-3 px-5 py-4 text-left"
          onClick={onToggle}
          aria-expanded={open}
        >
          <MethodBadge method={entry.method} />
          <span className="flex-1 font-mono text-sm">{entry.path}</span>
          <div className="flex items-center gap-2">
            {entry.authenticated ? (
              <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label="Requires auth" />
            ) : (
              <Globe className="h-3.5 w-3.5 text-muted-foreground" aria-label="Public" />
            )}
            <span className="hidden text-sm text-muted-foreground sm:block">
              {entry.summary}
            </span>
            <ChevronRight
              className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
              aria-hidden
            />
          </div>
        </button>

        {open && (
          <div className="space-y-5 border-t border-border px-5 py-5">
            <p className="text-sm text-muted-foreground">{entry.description}</p>

            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {entry.authenticated ? (
                <>
                  <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>{t("apiDocs.authNote")}</span>
                </>
              ) : (
                <>
                  <Globe className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>No authentication required.</span>
                </>
              )}
            </div>

            {entry.params.length > 0 && (
              <section>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t("apiDocs.paramsLabel")}
                </h4>
                <ParamTable params={entry.params} />
              </section>
            )}

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("apiDocs.requestLabel")}
              </h4>
              <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs">
                <code>{entry.exampleCurl}</code>
              </pre>
            </section>

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("apiDocs.responseLabel")}
              </h4>
              <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs">
                <code>{entry.responseShape}</code>
              </pre>
            </section>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * API reference page — rendered from the static `lib/api-catalog.ts` data
 * module. No network calls are made; the catalog is typed data co-located with
 * the real endpoint implementations.
 *
 * Endpoints covered:
 *   - POST /jobs, GET /jobs/{id}, GET /jobs  (reels)
 *   - GET /templates, GET /templates/{slug} (templates)
 *   - GET /trends/recommended              (trends)
 *   - GET /me/analytics                   (analytics)
 */
export function ApiRefPage() {
  const t = useTranslations();
  const [openId, setOpenId] = React.useState<string | null>(
    API_CATALOG[0]?.id ?? null,
  );

  function toggle(id: string) {
    setOpenId((prev) => (prev === id ? null : id));
  }

  return (
    <main className="mx-auto max-w-5xl space-y-10 px-4 py-8">
      {/* Header */}
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">{t("apiDocs.title")}</h1>
        </div>
        <p className="text-sm text-muted-foreground">{t("apiDocs.subtitle")}</p>
      </header>

      {/* Auth note */}
      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="flex items-start gap-3 p-4">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          <p className="text-sm">{t("apiDocs.authNote")}</p>
        </CardContent>
      </Card>

      {/* Groups */}
      {CATALOG_GROUPS.map((group) => {
        const entries = API_CATALOG.filter((e) => e.group === group);
        if (entries.length === 0) return null;
        return (
          <section key={group} className="space-y-3">
            <h2 className="text-lg font-semibold">{GROUP_LABELS[group]}</h2>
            {entries.map((entry) => (
              <EndpointCard
                key={entry.id}
                entry={entry}
                open={openId === entry.id}
                onToggle={() => toggle(entry.id)}
              />
            ))}
          </section>
        );
      })}
    </main>
  );
}
