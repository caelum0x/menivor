"use client";

import * as React from "react";
import { AlertCircle, Download, FileArchive, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useDataExport } from "@/lib/use-data-export";

/** Human "expires in N minutes/seconds" for the presigned link's lifetime. */
function formatExpiry(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "a short time";
  if (seconds < 60) return `${seconds} seconds`;
  const minutes = Math.round(seconds / 60);
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

/**
 * "Export my data" (GDPR Art. 15 / 20). Triggers a self-service export of the
 * caller's OWN data and surfaces a SHORT-LIVED download link. The archive is
 * scoped server-side to the resolved caller — this control can never export
 * another user's data. The link expires, so the copy states its lifetime.
 */
export function DataExportCard() {
  const { status, result, errorMessage, run } = useDataExport();
  const busy = status === "building";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileArchive className="size-5 text-primary" aria-hidden />
          Export my data
        </CardTitle>
        <CardDescription>
          Download a copy of everything associated with your account — your
          profile, jobs, asset metadata, credit history, and consent trail. The
          export contains only your own data.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={() => void run().catch(() => undefined)} disabled={busy}>
          {busy ? (
            <>
              <Loader2 className="animate-spin" aria-hidden /> Preparing your
              export…
            </>
          ) : (
            <>
              <Download aria-hidden /> Export my data
            </>
          )}
        </Button>

        {status === "error" && (
          <p
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <AlertCircle className="size-4 shrink-0" aria-hidden />
            {errorMessage}
          </p>
        )}

        {status === "ready" && result && (
          <div className="rounded-lg border border-border bg-secondary/40 p-4">
            <p className="text-sm font-medium">Your export is ready.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              This secure link expires in {formatExpiry(result.expires_in)}. Run
              the export again if it lapses.
            </p>
            <Button
              asChild
              variant="outline"
              size="sm"
              className="mt-3"
            >
              <a
                href={result.download_url}
                target="_blank"
                rel="noopener noreferrer"
                download
              >
                <Download aria-hidden /> Download archive
              </a>
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
