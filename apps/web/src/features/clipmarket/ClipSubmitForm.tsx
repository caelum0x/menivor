"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Loader2, Upload } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { submitClip, usd, type Submission } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface ClipSubmitFormProps {
  campaignId: string;
}

/** Real clip submission: a clipper posts a clip URL to a campaign for payout. */
export function ClipSubmitForm({ campaignId }: ClipSubmitFormProps) {
  const { getToken } = useAuth();
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState<Submission | null>(null);

  const onSubmit = React.useCallback(async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const token = (await getToken()) ?? undefined;
      const res = await submitClip(campaignId, url.trim(), {
        token,
        idempotencyKey: crypto.randomUUID(),
      });
      setResult(res);
      setUrl("");
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to submit clip."),
      );
    } finally {
      setBusy(false);
    }
  }, [getToken, campaignId, url]);

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          aria-label="Clip URL"
          placeholder="https://…/clip"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void onSubmit()}
          disabled={busy || url.trim() === ""}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Upload className="h-4 w-4" aria-hidden />
          )}
          <span className="ml-1">Submit</span>
        </Button>
      </div>
      {result && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary">{result.status}</Badge>
          {result.verified_views.toLocaleString()} views ·{" "}
          {usd(result.payable_micros)} payable
        </p>
      )}
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
