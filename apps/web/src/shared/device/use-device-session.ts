"use client";

import * as React from "react";
import { ensureDeviceSession, type DeviceSession } from "./session";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface DeviceSessionState {
  /** The device API key once provisioned ("" while loading / on error). */
  apiKey: string;
  /** True on the exchange that created a brand-new account (3 free credits). */
  created: boolean;
  status: "loading" | "ready" | "error";
  error: string;
  /** Re-attempt provisioning after an error. */
  retry: () => void;
}

/**
 * Provision (or restore) this browser's device session on mount. Pages that
 * must guarantee a key exists BEFORE firing API calls (e.g. the create flow)
 * use this; everything else relies on the transport-level fallback in
 * `src/shared/api/client.ts`.
 */
export function useDeviceSession(): DeviceSessionState {
  // Always start in "loading" — even when a key is already stored — so the
  // server-rendered HTML and the first client render match (reading
  // localStorage in the initializer would cause a hydration mismatch). The
  // effect below resolves synchronously-fast from storage on mount.
  const [state, setState] = React.useState<Omit<DeviceSessionState, "retry">>({
    apiKey: "",
    created: false,
    status: "loading",
    error: "",
  });
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    let active = true;
    void ensureDeviceSession()
      .then((session: DeviceSession) => {
        if (!active) return;
        setState({
          apiKey: session.api_key,
          created: session.created,
          status: "ready",
          error: "",
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          apiKey: "",
          created: false,
          status: "error",
          error:
            friendlyErrorMessage(error, "Could not start a session."),
        });
      });
    return () => {
      active = false;
    };
  }, [nonce]);

  const retry = React.useCallback(() => setNonce((n) => n + 1), []);

  return { ...state, retry };
}
