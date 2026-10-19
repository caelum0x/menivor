"use client";

import * as React from "react";
import Link from "next/link";
import { useAuth, UserButton } from "@/components/auth/clerk-safe";
import { AlertTriangle, Link2, Sparkles, Wand2 } from "lucide-react";

import { ApiError, ingestUrl, type UrlIngestResult } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * URL → reel importer: paste a product/article URL, extract its content, and
 * preview a hook-first reel draft the creator can carry into the wizard.
 */
export default function ImportPage() {
  const { getToken } = useAuth();
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState<UrlIngestResult | null>(null);

  const onImport = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const token = (await getToken()) ?? undefined;
      setResult(await ingestUrl(url.trim(), { token }));
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Could not import that URL."),
      );
    } finally {
      setBusy(false);
    }
  }, [getToken, url]);

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Wand2 className="h-6 w-6 text-primary" aria-hidden />
          <h1 className="text-2xl font-semibold">Import from a URL</h1>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>

      <p className="mb-4 text-sm text-muted-foreground">
        Paste a product or article link — we&apos;ll draft a hook-first UGC script and
        b-roll prompts you can take into the reel wizard.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="grid flex-1 gap-1">
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            <Link2 className="h-3.5 w-3.5" aria-hidden /> URL
          </label>
          <Input
            inputMode="url"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <Button onClick={() => void onImport()} disabled={busy || !url.trim()}>
          {busy ? "Importing…" : "Import"}
        </Button>
      </div>

      {error && (
        <p className="mt-3 flex items-center gap-1 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden /> {error}
        </p>
      )}

      {result && (
        <Card className="mt-6">
          <CardContent className="space-y-4 py-6">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Subject</p>
              <p className="font-medium">{result.reel_draft.video_subject}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Script</p>
              <p className="text-sm leading-6">{result.reel_draft.video_script}</p>
            </div>
            {result.reel_draft.broll_prompts.length > 0 && (
              <div>
                <p className="mb-1 flex items-center gap-1 text-xs uppercase tracking-wide text-muted-foreground">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden /> B-roll prompts
                </p>
                <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                  {result.reel_draft.broll_prompts.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
            <Link
              href="/new"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              Continue in the reel wizard →
            </Link>
          </CardContent>
        </Card>
      )}
    </main>
  );
}
