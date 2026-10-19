"use client";

import * as React from "react";
import { apiRequest } from "@/src/shared/api";
import { parseFormatAvailability, type FormatAvailability } from "./format-lock";

export interface FormatAvailabilityState {
  /** `null` while loading, when the read failed, or on an API without format lists. */
  readonly availability: FormatAvailability | null;
  readonly loading: boolean;
}

/**
 * Reads `available_formats` / `locked_formats` from the public
 * `GET /launch/status`. A failed read leaves every option enabled: the server
 * still rejects a locked format at submit (402 `format_locked`), and the
 * create flows show that error by name.
 */
export function useFormatAvailability(): FormatAvailabilityState {
  const [state, setState] = React.useState<FormatAvailabilityState>({
    availability: null,
    loading: true,
  });

  React.useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const raw = await apiRequest<unknown>("/launch/status", {
          anonymous: true,
          options: { signal: controller.signal },
        });
        if (active) setState({ availability: parseFormatAvailability(raw), loading: false });
      } catch {
        if (active) setState({ availability: null, loading: false });
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  return state;
}
