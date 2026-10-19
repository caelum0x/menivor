"use client";

import { Terminal } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { CopyBox } from "@/components/apikeys/CopyBox";
import { API_BASE } from "@/lib/api";

/**
 * A short "how to use it" snippet: send the key as the `x-api-key` header. Shows
 * a ready-to-copy curl example against the live API base. No real key is shown —
 * a `YOUR_API_KEY` placeholder stands in for the caller's secret.
 */
export function ApiKeyUsageSnippet() {
  const snippet = `curl ${API_BASE}/me \\\n  -H "x-api-key: YOUR_API_KEY"`;

  return (
    <Card>
      <CardContent className="space-y-3 p-6">
        <div className="flex items-start gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
            <Terminal className="size-4" aria-hidden />
          </span>
          <div>
            <p className="font-medium">Using your key</p>
            <p className="text-sm text-muted-foreground">
              Send it as the{" "}
              <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
                x-api-key
              </code>{" "}
              header on any request to the REST API.
            </p>
          </div>
        </div>

        <CopyBox value={snippet} label="Copy example request" />
      </CardContent>
    </Card>
  );
}
