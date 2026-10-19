"use client";

import * as React from "react";
import {
  ApiError,
  getCreatorProfile,
  getMe,
  updateMyProfile,
} from "@/lib/api";
import type {
  CreatorProfile,
  Me,
  ProfileUpdateRequest,
} from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type MyProfileStatus = "loading" | "ready" | "error";

export interface UseMyProfileResult {
  status: MyProfileStatus;
  /** Account facts (email, credit balance, lifetime job count). */
  me: Me | null;
  /** The caller's public creator profile, or `null` if none exists yet. */
  profile: CreatorProfile | null;
  errorMessage: string;
  /** True while a profile save (PATCH /me/profile) is in flight. */
  saving: boolean;
  /** Re-fetch the account + profile. */
  reload: () => void;
  /**
   * Persist handle / display name / bio. Returns the updated profile on
   * success, or `null` on error (the error message is exposed via `saveError`).
   */
  save: (body: ProfileUpdateRequest) => Promise<CreatorProfile | null>;
  saveError: string;
}

function messageFor(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Owns the caller's account facts (GET /me) plus their public creator profile
 * (GET /creators/{userId}). A missing profile (404) is treated as an empty,
 * not-yet-created profile rather than an error, so the edit form still renders.
 * `save` PATCHes /me/profile and replaces local state with the server's echo.
 */
export function useMyProfile(): UseMyProfileResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<MyProfileStatus>("loading");
  const [me, setMe] = React.useState<Me | null>(null);
  const [profile, setProfile] = React.useState<CreatorProfile | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState("");
  const [nonce, setNonce] = React.useState(0);

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      setStatus("loading");
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const account = await getMe({ token });
        if (cancelled) return;
        setMe(account);

        // A creator profile may not exist yet — a 404 is expected, not fatal.
        try {
          const p = await getCreatorProfile(account.user_id, { token });
          if (!cancelled) setProfile(p);
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            if (!cancelled) setProfile(null);
          } else {
            throw err;
          }
        }
        if (!cancelled) setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setErrorMessage(messageFor(err, "Couldn't load your account."));
        setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getApiToken, nonce]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  const save = React.useCallback(
    async (body: ProfileUpdateRequest): Promise<CreatorProfile | null> => {
      setSaving(true);
      setSaveError("");
      try {
        const token = await getApiToken();
        const updated = await updateMyProfile(body, { token });
        if (mountedRef.current) setProfile(updated);
        return updated;
      } catch (err) {
        if (mountedRef.current) {
          setSaveError(messageFor(err, "Couldn't save your profile."));
        }
        return null;
      } finally {
        if (mountedRef.current) setSaving(false);
      }
    },
    [getApiToken],
  );

  return {
    status,
    me,
    profile,
    errorMessage,
    saving,
    reload,
    save,
    saveError,
  };
}
