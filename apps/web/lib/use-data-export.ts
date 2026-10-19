"use client";

import * as React from "react";
import { ApiError, exportMyData } from "@/lib/api";
import type { DataExport } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type DataExportStatus = "idle" | "building" | "ready" | "error";

export interface UseDataExportResult {
  status: DataExportStatus;
  /** The most recent export (short-lived download link), or `null`. */
  result: DataExport | null;
  errorMessage: string;
  /** Trigger a fresh export of the caller's OWN data. Resolves to the export. */
  run: () => Promise<DataExport>;
  /** Clear the current result/error back to idle. */
  reset: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the caller's self-service data export (POST /me/data-export, GDPR Art.
 * 15/20). The export is STRICTLY the caller's own data — the server scopes it by
 * the resolved caller, never a client-supplied id. Resolves to a short-lived
 * presigned download link. State is only ever replaced with the server's
 * authoritative value, never mutated in place.
 */
export function useDataExport(): UseDataExportResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<DataExportStatus>("idle");
  const [result, setResult] = React.useState<DataExport | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = React.useCallback(async (): Promise<DataExport> => {
    setStatus("building");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const data = await exportMyData({ token });
      if (mountedRef.current) {
        setResult(data);
        setStatus("ready");
      }
      return data;
    } catch (err) {
      if (mountedRef.current) {
        setErrorMessage(
          messageFor(err, "Couldn't build your data export. Please try again."),
        );
        setStatus("error");
      }
      throw err;
    }
  }, [getApiToken]);

  const reset = React.useCallback(() => {
    setStatus("idle");
    setResult(null);
    setErrorMessage("");
  }, []);

  return { status, result, errorMessage, run, reset };
}
