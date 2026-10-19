"use client";

import * as React from "react";
import { ApiError, listMyConsents, recordConsent } from "@/lib/api";
import type { ConsentKind, ConsentRecord } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ConsentsStatus = "loading" | "ready" | "error";

export interface UseMyConsentsResult {
  status: ConsentsStatus;
  /** The caller's append-only consent trail (oldest first). */
  trail: readonly ConsentRecord[];
  errorMessage: string;
  /**
   * The CURRENT (newest) decision for a `kind`, or `null` when the caller has
   * never recorded one. Withdrawal is represented by the newest record having
   * `granted: false` — not by removing rows.
   */
  current: (kind: ConsentKind) => boolean | null;
  /**
   * Record a consent decision for the CALLER and refresh the trail. Resolves to
   * the appended record. The server always scopes this to the resolved caller.
   */
  set: (kind: ConsentKind, granted: boolean) => Promise<ConsentRecord>;
  reload: () => void;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/** The consent policy version the app records decisions against. */
export const CONSENT_POLICY_VERSION = "1.0";

/**
 * Owns the caller's consent trail (GET/PUT /me/consent, GDPR/SOC2 consent
 * capture). The trail is append-only — a withdrawal appends a `granted: false`
 * record rather than deleting history — so `current(kind)` derives the effective
 * state from the NEWEST matching record. Strictly caller-scoped server-side.
 * State is only ever replaced with the server's authoritative value.
 */
export function useMyConsents(): UseMyConsentsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<ConsentsStatus>("loading");
  const [trail, setTrail] = React.useState<readonly ConsentRecord[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [reloadNonce, setReloadNonce] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const result = await listMyConsents({
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setTrail(result);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setErrorMessage(messageFor(err, "Couldn't load your consent settings."));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, reloadNonce]);

  const current = React.useCallback(
    (kind: ConsentKind): boolean | null => {
      // The trail is oldest-first, so the LAST matching record is the newest.
      let decision: boolean | null = null;
      for (const record of trail) {
        if (record.kind === kind) decision = record.granted;
      }
      return decision;
    },
    [trail],
  );

  const set = React.useCallback(
    async (kind: ConsentKind, granted: boolean): Promise<ConsentRecord> => {
      const token = await getApiToken();
      const record = await recordConsent(
        { kind, granted, version: CONSENT_POLICY_VERSION },
        { token },
      );
      // Append immutably — the trail keeps full history, newest last.
      setTrail((prev) => [...prev, record]);
      setStatus("ready");
      return record;
    },
    [getApiToken],
  );

  const reload = React.useCallback(() => setReloadNonce((n) => n + 1), []);

  return { status, trail, errorMessage, current, set, reload };
}
