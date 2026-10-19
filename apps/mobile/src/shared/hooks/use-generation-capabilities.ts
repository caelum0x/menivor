import { useEffect, useState } from "react";

import { getPilotCapabilities, isAbortError } from "@/lib/api";
import type { PilotCapabilities } from "@/lib/types";

export interface GenerationCapabilitiesState {
  capabilities: PilotCapabilities | null;
  loading: boolean;
  error: string;
}

/** Shared loader for the authenticated server-owned generation gate. */
export function useGenerationCapabilities(
  token: string | undefined,
): GenerationCapabilitiesState {
  const [state, setState] = useState<GenerationCapabilitiesState>({
    capabilities: null,
    loading: true,
    error: "",
  });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ capabilities: null, loading: true, error: "" });
    void getPilotCapabilities({ token, signal: controller.signal })
      .then((capabilities) => {
        if (active) setState({ capabilities, loading: false, error: "" });
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return;
        setState({
          capabilities: null,
          loading: false,
          error:
            error instanceof Error
              ? error.message
              : "Could not check generation availability.",
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [token]);

  return state;
}
