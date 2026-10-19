"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import { useApiToken } from "@/lib/use-api-token";
import { accessErrorMessage, accessStatusFor, getCardCheckStatus, type CardCheckStatus } from "./api";

/** How long to wait for Clerk before telling the visitor what to do. */
const CLERK_LOAD_TIMEOUT_MS = 10_000;

export type WebAccessState =
  | { readonly status: "loading" }
  | { readonly status: "signed-out" }
  | { readonly status: "locked"; readonly card: CardCheckStatus }
  | { readonly status: "ready"; readonly card: CardCheckStatus }
  | { readonly status: "error"; readonly message: string };

export interface WebAccess {
  readonly state: WebAccessState;
  readonly getToken: () => Promise<string | undefined>;
  readonly refresh: () => void;
}

/**
 * Who may create on the web: a signed-in account whose free reels are
 * unlocked by the $1 card check (or that has paid before), or a new account
 * still holding its free first reel (MENIVOR_FREE_FIRST_REEL). Signed-out
 * visitors and locked accounts are sent to sign-up / the unlock step by the
 * caller.
 */
export function useWebAccess(): WebAccess {
  const { isLoaded, isSignedIn } = useAuth();
  const getToken = useApiToken();
  const [state, setState] = React.useState<WebAccessState>({ status: "loading" });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (isLoaded) return;
    const timer = setTimeout(() => {
      setState({
        status: "error",
        message: "Sign-in did not load. Refresh the page, or try another browser if it keeps happening.",
      });
    }, CLERK_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [isLoaded]);

  React.useEffect(() => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      setState({ status: "signed-out" });
      return;
    }
    let active = true;
    setState({ status: "loading" });
    void (async () => {
      try {
        const token = await getToken();
        if (!token) throw new Error("Your session is still starting. Refresh the page in a moment.");
        const card = await getCardCheckStatus({ token });
        if (active) setState({ status: accessStatusFor(card), card });
      } catch (err) {
        if (active) setState({ status: "error", message: accessErrorMessage(err) });
      }
    })();
    return () => {
      active = false;
    };
  }, [isLoaded, isSignedIn, getToken, nonce]);

  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);
  return { state, getToken, refresh };
}

/** `/sign-up` that returns to `path` once the account exists. */
export function signUpHref(path: string): string {
  return `/sign-up?redirect_url=${encodeURIComponent(path)}`;
}

/** The unlock step, continuing to `path` after paying. */
export function unlockHref(path: string): string {
  return `/onboarding?next=${encodeURIComponent(path)}`;
}

/**
 * `useWebAccess` for create surfaces, plus the redirect: signed-out visitors
 * go to sign-up and locked accounts to the unlock step, both returning to
 * `back` afterwards. Exposes the same shape the old device-session hook had.
 */
export function useCreateAccess(back: string): {
  readonly status: "loading" | "ready" | "error";
  readonly error: string;
  readonly retry: () => void;
  readonly getToken: () => Promise<string | undefined>;
} {
  const access = useWebAccess();
  const router = useRouter();
  const status = access.state.status;
  React.useEffect(() => {
    if (status === "signed-out") router.replace(signUpHref(back));
    if (status === "locked") router.replace(unlockHref(back));
  }, [back, router, status]);
  return {
    status: status === "ready" ? "ready" : status === "error" ? "error" : "loading",
    error: access.state.status === "error" ? access.state.message : "",
    retry: access.refresh,
    getToken: access.getToken,
  };
}
