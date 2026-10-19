"use client";

import * as React from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import {
  errorMessage,
  previewTone,
  type PlatformPreview,
  type Tone,
} from "@/components/calendar/board-api";

/**
 * Live per-platform preview of a caption in the chosen tone: exactly the text
 * each platform will receive (limits, hashtag caps and shortening applied by
 * the API), refreshed shortly after the creator stops typing.
 */
export function TonePreview({
  caption,
  hashtags,
  tone,
  platforms,
  onToned,
}: Readonly<{
  caption: string;
  hashtags: string[];
  tone: Tone;
  platforms: string[];
  /** Receives the toned caption (what will actually be sent). */
  onToned?: (caption: string) => void;
}>) {
  const getApiToken = useApiToken();
  const [previews, setPreviews] = React.useState<PlatformPreview[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const platformKey = platforms.join(",");
  const tagKey = hashtags.join(",");

  React.useEffect(() => {
    if (platforms.length === 0 || (!caption.trim() && hashtags.length === 0)) {
      setPreviews([]);
      setError("");
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const token = await getApiToken();
        const data = await previewTone(
          { caption, hashtags, tone, platforms },
          { token, signal: controller.signal },
        );
        if (cancelled) return;
        setPreviews(data.previews);
        onToned?.(data.caption);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessage(err, "Couldn't build the preview."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 350);
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
    // platformKey / tagKey stand in for the arrays (stable identity).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caption, tone, platformKey, tagKey, getApiToken]);

  if (platforms.length === 0) {
    return <p className="text-xs text-muted-foreground">Pick at least one channel to see the preview.</p>;
  }
  if (!caption.trim() && hashtags.length === 0) {
    return <p className="text-xs text-muted-foreground">Write a caption to see how each platform receives it.</p>;
  }

  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        Preview per platform
        {loading && <Loader2 className="size-3 animate-spin" aria-hidden />}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="grid gap-2 sm:grid-cols-2">
        {previews.map((p) => {
          const over = p.limit > 0 && p.length > p.limit;
          return (
            <div key={p.platform} className="rounded-md border border-border bg-muted/20 p-3">
              <div className="mb-1.5 flex items-center justify-between text-xs">
                <span className="font-medium">{p.label}</span>
                <span className={cn("tabular-nums", over ? "text-destructive" : "text-muted-foreground")}>
                  {p.length}/{p.limit}
                </span>
              </div>
              <p className="whitespace-pre-wrap break-words text-xs leading-relaxed">
                {p.text || <span className="text-muted-foreground">(no text)</span>}
              </p>
              {p.issues.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {p.issues.map((issue) => (
                    <li
                      key={`${issue.field}-${issue.message}`}
                      className={cn(
                        "flex items-start gap-1 text-[11px]",
                        issue.level === "error" ? "text-destructive" : "text-muted-foreground",
                      )}
                    >
                      <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                      {issue.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
