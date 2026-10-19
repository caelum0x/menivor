"use client";

// Reel-create presentation component.

import * as React from "react";
import { AlertCircle, Check, LayoutTemplate, RefreshCw, Sparkles } from "lucide-react";
import type { Template } from "@/lib/types";
import { ApiError, listTemplates } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface TemplateGalleryProps {
  /** Currently-applied template id, or null when starting from scratch. */
  value: string | null;
  /** Called with the chosen template so the wizard can pre-fill its fields. */
  onApply: (template: Template) => void;
  /** Called when the user opts to start from a blank wizard. */
  onClear: () => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; templates: readonly Template[] };

/**
 * Gallery of curated job templates from GET /catalog/templates. Choosing one
 * pre-fills the wizard (subject, prompt scaffold, layout, caption style,
 * language, duration) via `onApply`; "Start from scratch" clears it. Handles
 * loading, error, and empty states.
 */
export function TemplateGallery({ value, onApply, onClear }: TemplateGalleryProps) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const templates = await listTemplates({ token });
      setState({ status: "ready", templates });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load templates. Please try again.");
      setState({ status: "error", message });
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "loading") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-8 text-center">
        <AlertCircle className="size-6 text-destructive" aria-hidden />
        <p className="text-sm text-destructive">{state.message}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <button
        type="button"
        aria-pressed={value === null}
        onClick={onClear}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          value === null
            ? "border-primary ring-1 ring-primary"
            : "border-border hover:border-primary/50",
        )}
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
          <Sparkles className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">Start from scratch</span>
          <span className="block text-xs text-muted-foreground">
            Configure every step yourself.
          </span>
        </span>
        {value === null && (
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Check className="size-4" aria-hidden />
          </span>
        )}
      </button>

      {state.templates.length === 0 ? (
        <div className="rounded-lg border border-border bg-secondary/20 p-6 text-center text-sm text-muted-foreground">
          No templates are available yet — start from scratch above.
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {state.templates.map((template) => {
            const selected = template.id === value;
            return (
              <li key={template.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onApply(template)}
                  className={cn(
                    "relative flex h-full w-full flex-col gap-2 rounded-lg border p-4 text-left transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                    selected
                      ? "border-primary ring-2 ring-primary"
                      : "border-border hover:border-primary/60",
                  )}
                >
                  {selected && (
                    <span className="absolute right-2 top-2 flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Check className="size-4" aria-hidden />
                    </span>
                  )}
                  <span className="flex items-center gap-2 text-sm font-medium">
                    <LayoutTemplate className="size-4 text-primary" aria-hidden />
                    {template.name}
                  </span>
                  {template.description && (
                    <span className="block text-xs text-muted-foreground">
                      {template.description}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
