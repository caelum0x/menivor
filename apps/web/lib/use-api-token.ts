"use client";

import { useAuth } from "@/components/auth/clerk-safe";
import { useCallback } from "react";

/**
 * Clerk's `getToken()` does not settle until clerk-js has loaded. When the
 * Clerk script CDN is slow or down (observed live: HTTP 524 on
 * clerk.browser.js), an un-raced `await getToken()` stalls every anonymous
 * surface that only needed the device-session fallback. 2.5s is generous for
 * a warm clerk-js and short enough that visitors never notice the fallback.
 */
const CLERK_TOKEN_TIMEOUT_MS = 2500;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T | undefined> {
  return new Promise<T | undefined>((resolve) => {
    const timer = setTimeout(() => resolve(undefined), ms);
    promise
      .then((value) => {
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(undefined);
      });
  });
}

/**
 * Returns a stable getter that resolves the current Clerk session JWT to send
 * as the `x-api-key` header on API calls. Falls back to `undefined` when the
 * user is signed out, token minting fails, or Clerk does not load within
 * {@link CLERK_TOKEN_TIMEOUT_MS} — in which case `lib/api` degrades to the
 * browser's device-session key / public `NEXT_PUBLIC_APP_API_KEY`. No secrets
 * are handled here.
 */
export function useApiToken(): () => Promise<string | undefined> {
  const { getToken } = useAuth();

  return useCallback(async (): Promise<string | undefined> => {
    try {
      const token = await withTimeout(getToken(), CLERK_TOKEN_TIMEOUT_MS);
      return token ?? undefined;
    } catch {
      return undefined;
    }
  }, [getToken]);
}
