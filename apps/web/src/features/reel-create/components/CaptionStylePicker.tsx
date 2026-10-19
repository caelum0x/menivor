"use client";

import * as React from "react";
import { AlertCircle, Check, RefreshCw } from "lucide-react";
import type { CaptionStyle } from "@/lib/types";
import { ApiError, listCaptionStyles } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { assColorToCss } from "./caption-colors";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface CaptionStylePickerProps {
  value: string;
  onSelect: (captionStyle: string, label: string) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; styles: readonly CaptionStyle[] };

/**
 * Mini karaoke caption preview coloured with the style's primary (spoken) and
 * secondary (upcoming) ASS colours converted to CSS.
 */
function CaptionPreview({ style }: { style: CaptionStyle }) {
  const spoken = assColorToCss(style.primary);
  const upcoming = assColorToCss(style.secondary, spoken);
  const words: readonly [string, string, string] = ["This", "is", "how"];
  return (
    <span className="flex flex-wrap items-center justify-center gap-1 rounded-md bg-black/70 px-3 py-2">
      {words.map((word, i) => (
        <span
          key={word}
          className="text-sm font-extrabold [text-shadow:0_1px_2px_rgba(0,0,0,0.85)]"
          style={{ color: i === 0 ? spoken : upcoming }}
        >
          {word}
        </span>
      ))}
    </span>
  );
}

/** Small primary/secondary colour swatch pair. */
function ColorSwatches({ style }: { style: CaptionStyle }) {
  return (
    <span className="flex items-center gap-1.5" aria-hidden>
      <span
        className="size-4 rounded-full border border-border"
        style={{ backgroundColor: assColorToCss(style.primary) }}
      />
      <span
        className="size-4 rounded-full border border-border"
        style={{
          backgroundColor: assColorToCss(
            style.secondary,
            assColorToCss(style.primary),
          ),
        }}
      />
    </span>
  );
}

/**
 * Visual cards for the burned-in karaoke caption style, driven by
 * GET /catalog/caption-styles. Each card shows a live caption preview plus the
 * primary/secondary colour swatches. Emits the backend caption-style id and its
 * display name upward. Handles loading, error, and empty states.
 */
export function CaptionStylePicker({ value, onSelect }: CaptionStylePickerProps) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const styles = await listCaptionStyles({ token });
      setState({ status: "ready", styles });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load caption styles. Please try again.");
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
          <Skeleton key={i} className="h-32 w-full rounded-lg" />
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

  if (state.styles.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-secondary/20 p-8 text-center text-sm text-muted-foreground">
        No caption styles are available yet. Please check back soon.
      </div>
    );
  }

  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {state.styles.map((style) => {
        const selected = style.id === value;
        return (
          <li key={style.id}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(style.id, style.name)}
              className={cn(
                "relative flex h-full w-full flex-col gap-3 rounded-lg border p-4 text-left transition-colors",
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
              <CaptionPreview style={style} />
              <span>
                <span className="flex items-center gap-2">
                  <span className="text-sm font-medium">{style.name}</span>
                  <ColorSwatches style={style} />
                </span>
                {style.description && (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {style.description}
                  </span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
