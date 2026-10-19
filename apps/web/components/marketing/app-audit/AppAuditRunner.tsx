"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorNote, ToolPanel } from "@/components/marketing/free-tools/shared";
import { isStoreLink, runAudit, type AuditResult } from "@/src/features/app-audit/api";
import { FullAuditView, SearchVisibilityView } from "./AuditResultView";

interface AppAuditRunnerProps {
  /** Pre-filled URL (e.g. from the hero's paste box, or a `?url=` query param). */
  readonly initialUrl?: string;
  /** Hero preview passes `false`: it reuses the hero's own paste box as the source of the URL. */
  readonly showInput?: boolean;
  /** `/tools/aso-keyword-checker` only renders the search-visibility section. */
  readonly variant?: "full" | "visibility-only";
  readonly cta?: string;
}

/**
 * Runs the free, public App Store / Play audit (`POST /audit`, no sign-in)
 * and renders the result. One component powers the hero's inline preview,
 * `/tools/app-store-audit` and `/tools/aso-keyword-checker` — only the
 * `showInput`/`variant` props differ.
 */
export function AppAuditRunner({ initialUrl = "", showInput = true, variant = "full", cta }: AppAuditRunnerProps) {
  const [url, setUrl] = useState(initialUrl);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AuditResult | null>(null);

  const effectiveUrl = showInput ? url : initialUrl;
  const canRun = isStoreLink(effectiveUrl) && !loading;

  async function run(targetUrl: string) {
    if (!isStoreLink(targetUrl)) {
      setError("Paste an App Store (apps.apple.com) or Google Play (play.google.com) app link.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const audit = await runAudit(targetUrl);
      setResult(audit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The audit failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <ToolPanel>
      {showInput ? (
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-start"
          onSubmit={(event) => {
            event.preventDefault();
            void run(url);
          }}
        >
          <label htmlFor="app-audit-url" className="sr-only">App Store or Google Play link</label>
          <input
            id="app-audit-url"
            type="url"
            required
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://apps.apple.com/us/app/.../id123456789"
            className="neu-inset h-12 w-full min-w-0 flex-1 rounded-xl px-4 text-base placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <Button type="submit" size="lg" disabled={!canRun}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
            {loading ? "Scoring..." : "Run free audit"}
          </Button>
        </form>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            {isStoreLink(initialUrl)
              ? "That looks like an app store link. Score its listing for free."
              : "Paste an App Store or Google Play app link above to also score its listing — free, no signup."}
          </p>
          <Button type="button" size="md" disabled={!canRun} onClick={() => void run(initialUrl)}>
            {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
            {loading ? "Scoring..." : "Run free audit"}
          </Button>
        </div>
      )}

      {error ? <ErrorNote message={error} /> : null}

      {result ? (
        <div className="mt-6 border-t border-border pt-6">
          {variant === "visibility-only" ? <SearchVisibilityView result={result} /> : <FullAuditView result={result} />}
        </div>
      ) : null}

      {cta && result ? (
        <p className="mt-5 rounded-md border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-muted-foreground">{cta}</p>
      ) : null}
    </ToolPanel>
  );
}
