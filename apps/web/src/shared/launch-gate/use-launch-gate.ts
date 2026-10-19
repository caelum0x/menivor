"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { apiRequest } from "@/src/shared/api";
import { OPEN_GATE, gateFromStatus, type LaunchGate } from "./gate";

export interface LaunchGateState {
  /** `loading` until the first read settles; `unknown` when the read failed. */
  readonly status: "loading" | "ready" | "unknown";
  readonly gate: LaunchGate;
}

const LOADING_GATE: LaunchGate = {
  phase: "private_beta",
  staffOverride: false,
  publishing: { open: false, reason: "" },
  checkout: { open: false, reason: "" },
};

/**
 * One read of `GET /launch/status` as the caller. With a token the server
 * evaluates the pilot staff allow-list; without one it answers anonymously.
 */
export async function fetchLaunchGate(token?: string, signal?: AbortSignal): Promise<LaunchGate> {
  const raw = await apiRequest<unknown>(
    "/launch/status",
    token ? { options: { token, signal } } : { options: { signal }, anonymous: true },
  );
  return gateFromStatus(raw);
}

/**
 * Read `GET /launch/status` for the signed-in caller before any publish,
 * schedule or checkout control is enabled. The call carries the caller's
 * token so pilot staff see their override. While loading, gated controls stay
 * disabled; if the read fails the controls re-enable (the API still enforces
 * the gate and its refusal is shown as readable copy).
 */
export function useLaunchGate(): LaunchGateState {
  const { getToken } = useAuth();
  const [state, setState] = React.useState<LaunchGateState>({
    status: "loading",
    gate: LOADING_GATE,
  });

  React.useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const gate = await fetchLaunchGate(token, controller.signal);
        if (!controller.signal.aborted) setState({ status: "ready", gate });
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({ status: "unknown", gate: OPEN_GATE });
      }
    })();
    return () => controller.abort();
  }, [getToken]);

  return state;
}
