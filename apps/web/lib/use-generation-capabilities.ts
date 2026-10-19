"use client";

import * as React from "react";
import { getPilotCapabilities } from "@/lib/api";
import { hasRealClerkKey } from "@/lib/clerk";
import type { PilotCapabilities } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface GenerationCapabilitiesState {
  capabilities: PilotCapabilities | null;
  loading: boolean;
  error: string;
}

/** Load the server-owned feature gate once for the authenticated session. */
export function useGenerationCapabilities(): GenerationCapabilitiesState {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<GenerationCapabilitiesState>({
    capabilities: null,
    loading: true,
    error: "",
  });

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const token = await getApiToken();
        // Signed-out visitors are redirected to sign-up; the capability gate
        // needs a session, so skip the call instead of logging a 401. Without
        // Clerk (local dev) the app-key fallback still applies.
        if (!token && hasRealClerkKey) {
          if (active) {
            setState({
              capabilities: null,
              loading: false,
              error: "Sign in to check generation availability.",
            });
          }
          return;
        }
        const capabilities = await getPilotCapabilities({
          token,
          signal: controller.signal,
        });
        if (active) setState({ capabilities, loading: false, error: "" });
      } catch (error) {
        if (!active || controller.signal.aborted) return;
        setState({
          capabilities: null,
          loading: false,
          error:
            friendlyErrorMessage(error, "Could not check generation availability."),
        });
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [getApiToken]);

  return state;
}
