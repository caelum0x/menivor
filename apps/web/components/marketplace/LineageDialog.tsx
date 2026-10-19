"use client";

import * as React from "react";
import {
  AlertCircle,
  ArrowUp,
  GitFork,
  Loader2,
  Network,
  Users,
  X,
} from "lucide-react";
import type { MarketplaceLineage, MarketplaceTemplate } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatCount } from "@/components/marketplace/format";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface LineageDialogProps {
  open: boolean;
  onClose: () => void;
  /** The listing whose remix tree is being shown (drives the header). */
  template: Readonly<MarketplaceTemplate>;
  /** Fetches the remix-tree lineage for the given listing id. */
  onLoad: (id: string) => Promise<MarketplaceLineage>;
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; lineage: MarketplaceLineage }
  | { status: "error"; message: string };

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * A read-only modal that renders a listing's REMIX TREE: its `ancestors`
 * (immediate parent → root, the lineage this listing was remixed from) and its
 * direct still-published `children` (the remixes made from it). Fetches the
 * lineage lazily each time it opens; every entry is a safe public listing, so no
 * private fields are ever shown. Closes on Escape or a backdrop click.
 */
export function LineageDialog({
  open,
  onClose,
  template,
  onLoad,
}: Readonly<LineageDialogProps>) {
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setState({ status: "loading" });
    void (async () => {
      try {
        const lineage = await onLoad(template.id);
        if (!cancelled) setState({ status: "ready", lineage });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: errorMessage(err, "Couldn't load the remix tree."),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, onLoad, template.id]);

  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-background/80 p-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="lineage-dialog-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-lg rounded-lg border border-border bg-card shadow-lg">
        <div className="flex items-start justify-between gap-3 border-b border-border p-5">
          <div className="min-w-0">
            <h2
              id="lineage-dialog-title"
              className="flex items-center gap-2 text-lg font-semibold leading-none tracking-tight"
            >
              <Network className="size-5 shrink-0 text-primary" aria-hidden />
              Remix tree
            </h2>
            <p className="mt-1.5 truncate text-sm text-muted-foreground">
              {template.title || "Untitled template"}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="max-h-[70dvh] space-y-6 overflow-y-auto p-5">
          {state.status === "loading" && (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Loading remix tree…
            </div>
          )}

          {state.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-1.5 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {state.message}
            </p>
          )}

          {state.status === "ready" && (
            <>
              <LineageSection
                icon={
                  <ArrowUp className="size-4 text-muted-foreground" aria-hidden />
                }
                title="Remixed from"
                emptyLabel="This is an original template — the root of its remix tree."
                entries={state.lineage.ancestors}
              />
              <LineageSection
                icon={
                  <GitFork
                    className="size-4 text-muted-foreground"
                    aria-hidden
                  />
                }
                title="Remixes"
                emptyLabel="No remixes yet. Be the first to remix this template."
                entries={state.lineage.children}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface LineageSectionProps {
  icon: React.ReactNode;
  title: string;
  emptyLabel: string;
  entries: readonly MarketplaceTemplate[];
}

function LineageSection({
  icon,
  title,
  emptyLabel,
  entries,
}: Readonly<LineageSectionProps>) {
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold">
        {icon}
        {title}
        <span className="text-muted-foreground">({entries.length})</span>
      </h3>
      {entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry) => (
            <LineageRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </section>
  );
}

function LineageRow({ entry }: Readonly<{ entry: Readonly<MarketplaceTemplate> }>) {
  const remixCount =
    typeof entry.remix_count === "number" ? entry.remix_count : 0;
  return (
    <li className="rounded-md border border-border p-3">
      <p className="truncate text-sm font-medium">
        {entry.title || "Untitled template"}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Badge variant="outline">
          <GitFork className="size-3" aria-hidden />
          {formatCount(remixCount)} remix{remixCount === 1 ? "" : "es"}
        </Badge>
        <Badge variant="outline">
          <Users className="size-3" aria-hidden />
          {formatCount(entry.clone_count)} clone
          {entry.clone_count === 1 ? "" : "s"}
        </Badge>
      </div>
    </li>
  );
}
