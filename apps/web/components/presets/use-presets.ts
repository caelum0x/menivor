"use client";

import * as React from "react";
import { ApiError, createPreset, deletePreset, listPresets } from "@/lib/api";
import type { Preset } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import {
  toConfigRecord,
  type PresetConfig,
} from "@/components/presets/preset-config";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type PresetsStatus = "loading" | "ready" | "error";

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

export interface UsePresetsResult {
  status: PresetsStatus;
  presets: readonly Preset[];
  errorMessage: string;
  /** Refetch the caller's presets. */
  reload: () => void;
  /**
   * Create a preset; returns the created row (also prepended to the list).
   * Pass `workspaceId` to SHARE the kit to that workspace so every member sees
   * it; omit (or pass null) to keep it private to the caller.
   */
  create: (
    name: string,
    config: Readonly<PresetConfig>,
    workspaceId?: string | null,
  ) => Promise<Preset>;
  /** Delete a preset by id, removing it from the list on success. */
  remove: (id: string) => Promise<void>;
}

/**
 * Owns the caller's saved presets: loads them (newest first), and exposes
 * immutable create/delete mutators that keep the local list in sync. All state
 * transitions replace the list with a fresh array — nothing is mutated in place.
 */
export function usePresets(): UsePresetsResult {
  const getApiToken = useApiToken();
  const [status, setStatus] = React.useState<PresetsStatus>("loading");
  const [presets, setPresets] = React.useState<readonly Preset[]>([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  const load = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listPresets({ token });
      setPresets(result);
      setStatus("ready");
    } catch (err) {
      setErrorMessage(errorMessageOf(err, "Couldn't load your presets."));
      setStatus("error");
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const create = React.useCallback(
    async (
      name: string,
      config: Readonly<PresetConfig>,
      workspaceId?: string | null,
    ): Promise<Preset> => {
      const token = await getApiToken();
      const shareTo = workspaceId?.trim();
      const created = await createPreset(
        {
          name: name.trim(),
          config: toConfigRecord(config),
          ...(shareTo ? { workspace_id: shareTo } : {}),
        },
        { token },
      );
      setPresets((prev) => [created, ...prev]);
      return created;
    },
    [getApiToken],
  );

  const remove = React.useCallback(
    async (id: string): Promise<void> => {
      const token = await getApiToken();
      await deletePreset(id, { token });
      setPresets((prev) => prev.filter((p) => p.id !== id));
    },
    [getApiToken],
  );

  return {
    status,
    presets,
    errorMessage,
    reload: () => void load(),
    create,
    remove,
  };
}
