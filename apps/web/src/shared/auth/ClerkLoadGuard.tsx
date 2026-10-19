"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { isClerkLoadFailure } from "./clerk-load-guard";

/**
 * Site-wide fallback for Clerk's CDN script failing to load (ad blockers,
 * aggressive DNS/firewall filters, flaky networks — see clerk-load-guard.ts).
 * Without this, a visitor on a page that mounts `<ClerkProvider>` but can't
 * reach clerk.menivor.com gets a silently dead sign-in/sign-up surface: no
 * error, no retry, nothing — confirmed in production via GlitchTip issue
 * #926. Mount only where `<ClerkProvider>` is mounted (app/layout.tsx, gated
 * on `hasRealClerkKey`).
 */
export function ClerkLoadGuard() {
  const [broken, setBroken] = React.useState(false);

  React.useEffect(() => {
    const handle = (message: string | undefined | null) => {
      if (isClerkLoadFailure(message)) setBroken(true);
    };
    const onError = (event: ErrorEvent) => handle(event.error?.message ?? event.message);
    const onRejection = (event: PromiseRejectionEvent) =>
      handle(event.reason instanceof Error ? event.reason.message : String(event.reason));
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  if (!broken) return null;

  return (
    <div
      role="alert"
      className="fixed inset-x-0 bottom-0 z-50 flex flex-wrap items-center justify-center gap-3 border-t border-white/[0.12] bg-background/95 px-4 py-3 text-center text-sm backdrop-blur"
    >
      <span className="text-foreground">
        Sign-in couldn&apos;t load — this is usually a browser extension or network filter blocking it.
      </span>
      <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
        Reload page
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setBroken(false)}>
        Dismiss
      </Button>
    </div>
  );
}
