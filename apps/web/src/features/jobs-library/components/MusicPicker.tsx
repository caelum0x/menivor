"use client";

import * as React from "react";
import type { MusicTrack } from "@/lib/types";
import { ApiError, listMusic } from "@/lib/api";
import { Select } from "@/components/ui/select";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/**
 * Jobs-library background-music selector backed by `GET /catalog/music`. Emits the
 * chosen track `id` (sent as `music_id`), or `null` for the "keep original"
 * default. Handles its own loading / error states without throwing.
 */

interface MusicPickerProps {
  /** Selected music id, or null = keep the source job's track. */
  value: string | null;
  onChange: (musicId: string | null) => void;
  disabled?: boolean;
  id?: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tracks: readonly MusicTrack[] };

export function MusicPicker({
  value,
  onChange,
  disabled = false,
  id,
}: Readonly<MusicPickerProps>) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const tracks = await listMusic({ token });
      setState({ status: "ready", tracks });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load music tracks.");
      setState({ status: "error", message });
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "error") {
    return (
      <div className="space-y-1 text-sm">
        <p className="text-destructive">{state.message}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="underline underline-offset-2 hover:text-foreground"
        >
          Retry
        </button>
      </div>
    );
  }

  const loading = state.status === "loading";

  return (
    <Select
      id={id}
      value={value ?? ""}
      disabled={disabled || loading}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">
        {loading ? "Loading music…" : "Keep original"}
      </option>
      {state.status === "ready" &&
        state.tracks.map((track) => (
          <option key={track.id} value={track.id}>
            {track.name}
          </option>
        ))}
    </Select>
  );
}
