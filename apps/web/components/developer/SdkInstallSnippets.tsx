"use client";

import * as React from "react";
import { Package, Terminal } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { CopyBox } from "@/components/apikeys/CopyBox";

/** The npm package name for the TypeScript SDK. */
const NPM_PACKAGE = "@menivor/sdk";
/** The PyPI distribution (and import) name for the Python SDK. */
const PYPI_PACKAGE = "menivor";
const DEFAULT_ORIGIN = "https://api.menivor.com";

/**
 * The SDKs take the API *origin* and append `/api/v1` themselves, while the
 * developer portal reports the full versioned base. Strip the version suffix so
 * the snippet never produces `/api/v1/api/v1/...` requests.
 */
export function sdkOrigin(apiBaseUrl: string): string {
  const trimmed = (apiBaseUrl || "").trim().replace(/\/+$/, "");
  if (!trimmed) return DEFAULT_ORIGIN;
  return trimmed.replace(/\/api\/v1$/, "") || DEFAULT_ORIGIN;
}

interface SdkInstallSnippetsProps {
  /** The API base URL the SDK should target (from the developer portal). */
  apiBaseUrl: string;
}

/**
 * Install snippets for the Menivor SDKs (TypeScript + Python) plus a
 * minimal auth-config example. No real key is shown — a `YOUR_API_KEY`
 * placeholder stands in for the caller's secret. The SDKs are generated from the
 * OpenAPI spec; both target the same stable operationIds
 * (`createWebhookSubscription`, `listWebhookDeliveries`, …).
 */
export function SdkInstallSnippets({ apiBaseUrl }: SdkInstallSnippetsProps) {
  const base = sdkOrigin(apiBaseUrl);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Package className="size-5 text-primary" aria-hidden />
          Install an SDK
        </CardTitle>
        <CardDescription>
          Generated from the OpenAPI spec — the same typed client covers jobs,
          publishing, webhooks, and usage. Authenticate with an API key from the
          section above (sent as the{" "}
          <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
            x-api-key
          </code>{" "}
          header).
        </CardDescription>
        <p className="text-xs text-muted-foreground">
          The packages are coming to npm and PyPI; they are not published yet.
          Until then, install them from the Menivor repository
          (<code className="font-mono">packages/sdk-typescript</code> and{" "}
          <code className="font-mono">packages/sdk-python</code>) or call the REST API
          directly.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Terminal className="size-4 text-muted-foreground" aria-hidden />
            TypeScript / JavaScript
          </p>
          <CopyBox value={`npm install ${NPM_PACKAGE}`} label="Copy npm install command" />
          <CopyBox
            mono
            value={[
              `import { MenivorClient } from "${NPM_PACKAGE}";`,
              "",
              "const client = new MenivorClient({",
              `  baseUrl: "${base}",`,
              '  apiKey: process.env.MENIVOR_API_KEY, // never hardcode',
              "});",
            ].join("\n")}
            label="Copy TypeScript setup snippet"
          />
        </div>

        <div className="space-y-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Terminal className="size-4 text-muted-foreground" aria-hidden />
            Python
          </p>
          <CopyBox value={`pip install ${PYPI_PACKAGE}`} label="Copy pip install command" />
          <CopyBox
            mono
            value={[
              "import os",
              `from ${PYPI_PACKAGE} import MenivorClient`,
              "",
              "client = MenivorClient(",
              `    base_url="${base}",`,
              '    api_key=os.environ["MENIVOR_API_KEY"],  # never hardcode',
              ")",
            ].join("\n")}
            label="Copy Python setup snippet"
          />
        </div>
      </CardContent>
    </Card>
  );
}
