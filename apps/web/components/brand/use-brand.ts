"use client";

import * as React from "react";
import type { Brand, BrandUpdateRequest } from "@/lib/types";
import { ApiError, getBrand, updateBrand } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type BrandStatus = "loading" | "ready" | "error";

export interface UseBrandResult {
  status: BrandStatus;
  brand: Brand | null;
  errorMessage: string;
  /** True while a save (PUT /me/brand) is in flight. */
  saving: boolean;
  /** Re-fetch the caller's brand settings. */
  reload: () => void;
  /**
   * Persist a partial update. Resolves with the updated brand on success or
   * `null` on failure (the thrown message is surfaced via `errorMessage`).
   */
  save: (patch: BrandUpdateRequest) => Promise<Brand | null>;
}

function messageFor(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Owns the caller's brand watermark: loads GET /me/brand and exposes a `save`
 * that PUTs a partial update, keeping the local `brand` in sync with the server
 * response. State is updated immutably (never mutated in place).
 */
export function useBrand(): UseBrandResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<BrandStatus>("loading");
  const [brand, setBrand] = React.useState<Brand | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  const reload = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await getBrand({ token });
      setBrand(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(
        messageFor(err, "Could not load your brand settings. Please try again."),
      );
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void reload();
  }, [reload]);

  const save = React.useCallback(
    async (patch: BrandUpdateRequest): Promise<Brand | null> => {
      setSaving(true);
      setErrorMessage("");
      try {
        const token = await getApiToken();
        const updated = await updateBrand(patch, { token });
        setBrand(updated);
        setStatus("ready");
        return updated;
      } catch (err) {
        setErrorMessage(
          messageFor(err, "Could not save your brand settings. Please try again."),
        );
        return null;
      } finally {
        setSaving(false);
      }
    },
    [getApiToken],
  );

  return {
    status,
    brand,
    errorMessage,
    saving,
    reload: () => void reload(),
    save,
  };
}
