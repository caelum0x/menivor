"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { useApiToken } from "@/lib/use-api-token";
import { setSessionTokenGetter } from "./session-token";

/**
 * Registers the signed-in Clerk token as the default API credential (nothing
 * while signed out, so public pages never wait on Clerk). Layout effects run
 * before any page's data-loading effects, so the first request already
 * carries the account token.
 */
export function ApiSessionBridge() {
  const { isSignedIn } = useAuth();
  const getToken = useApiToken();
  React.useLayoutEffect(() => {
    // While Clerk is still loading `isSignedIn` is undefined. Pages fire their
    // first request immediately, so keep the token getter registered then:
    // getToken() waits for Clerk (bounded by useApiToken's timeout) instead of
    // the request going out with no credential and failing with a 401.
    setSessionTokenGetter(isSignedIn === false ? null : getToken);
    return () => setSessionTokenGetter(null);
  }, [getToken, isSignedIn]);
  return null;
}
