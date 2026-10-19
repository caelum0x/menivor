"use client";

import * as React from "react";
import { KeyRound } from "lucide-react";
import { AccountNav } from "@/components/account/AccountNav";
import { AppHeader } from "@/components/account/AppHeader";
import { ApiKeysManager } from "@/components/apikeys/ApiKeysManager";

/**
 * Account → API keys. Mint and revoke personal keys for the ReelForge REST API.
 * The heavy lifting (list / create / reveal-once / revoke, with its own
 * loading / empty / error states) lives in {@link ApiKeysManager}, which reads
 * and mutates `GET/POST/DELETE /me/api-keys`. This route just frames it with the
 * shared account chrome so a signed-in user can navigate between account
 * surfaces.
 */
export default function AccountApiKeysPage() {
  return (
    <main className="min-h-dvh">
      <AppHeader />

      <section className="container py-10">
        <div className="mx-auto max-w-5xl">
          <div className="mb-6">
            <p className="text-sm font-medium text-muted-foreground">Account</p>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <KeyRound className="size-7 text-primary" aria-hidden />
              API keys
            </h1>
            <p className="mt-2 max-w-2xl text-muted-foreground">
              Create personal keys for programmatic access to the REST API. Send
              a key as the{" "}
              <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs">
                x-api-key
              </code>{" "}
              header. A key&apos;s secret is shown once at creation — store it
              somewhere safe, and revoke any key you no longer use.
            </p>
          </div>

          <AccountNav />

          <ApiKeysManager />
        </div>
      </section>
    </main>
  );
}
