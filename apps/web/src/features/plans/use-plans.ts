"use client";

import * as React from "react";
import { useSignedInState } from "@/lib/auth-state";
import { useApiToken } from "@/lib/use-api-token";
import {
  FALLBACK_CATALOG,
  getMonthlyCatalog,
  getMyPlan,
  type MonthlyCatalog,
  type MyPlan,
} from "./api";

export interface PlansState {
  readonly catalog: MonthlyCatalog;
  /** `undefined` while loading or signed out; `null` when the API has no plans yet. */
  readonly mine: MyPlan | null | undefined;
  readonly signedIn: boolean;
  readonly getToken: () => Promise<string | undefined>;
  readonly refresh: () => void;
  readonly setMine: (next: MyPlan) => void;
}

/**
 * Live catalog (public) + the signed-in user's plan. Failures keep the defaults.
 * `initialCatalog` is the catalog the server already read (pricing page), so
 * the first render matches the API instead of the display fallback.
 */
export function usePlans(initialCatalog?: MonthlyCatalog | null): PlansState {
  const { isLoaded, isSignedIn } = useSignedInState();
  const getToken = useApiToken();
  const [catalog, setCatalog] = React.useState<MonthlyCatalog>(
    initialCatalog ?? FALLBACK_CATALOG,
  );
  const [mine, setMine] = React.useState<MyPlan | null | undefined>(undefined);
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    void getMonthlyCatalog()
      .then((next) => {
        if (active) setCatalog(next);
      })
      .catch(() => {
        // Keep the display defaults; checkout still validates server-side.
      });
    return () => {
      active = false;
    };
  }, []);

  React.useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const next = await getMyPlan({ token });
        if (active) setMine(next);
      } catch {
        if (active) setMine(null);
      }
    })();
    return () => {
      active = false;
    };
  }, [isLoaded, isSignedIn, getToken, nonce]);

  const refresh = React.useCallback(() => setNonce((n) => n + 1), []);
  return {
    catalog,
    mine,
    signedIn: Boolean(isLoaded && isSignedIn),
    getToken,
    refresh,
    setMine,
  };
}
