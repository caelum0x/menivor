"use client";

// Reel-create presentation component.

import * as React from "react";
import { AlertCircle, Check, Music, Pause, Play, RefreshCw, VolumeX } from "lucide-react";
import type { MusicTrack } from "@/lib/types";
import { ApiError, listMusic } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface MusicLibraryListProps {
  /** Currently-selected track id, or null for "no music". */
  value: string | null;
  onSelect: (musicId: string | null, label: string | null) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tracks: readonly MusicTrack[] };

/**
 * Read an optional preview URL off a track. The base catalog does not ship one,
 * but the field is honoured defensively (via the `MusicTrack` index signature)
 * so audio preview lights up automatically if the backend adds it later.
 */
function previewUrlOf(track: MusicTrack): string | null {
  const raw = track.preview_url ?? track.get_url ?? track.url;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

function formatDuration(seconds: number | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }
  const total = Math.round(seconds);
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * List of curated background-music tracks from GET /catalog/music, with a
 * "No music" option and an inline play/pause preview (enabled only when a track
 * exposes a playable URL). Handles loading, error, and empty states; reports the
 * chosen track id + name upward.
 */
export function MusicLibraryList({ value, onSelect }: MusicLibraryListProps) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  const [playingId, setPlayingId] = React.useState<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const tracks = await listMusic({ token });
      setState({ status: "ready", tracks });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load music. Please try again.");
      setState({ status: "error", message });
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Stop any playing audio on unmount.
  React.useEffect(() => {
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  const togglePreview = React.useCallback(
    (track: MusicTrack) => {
      const url = previewUrlOf(track);
      if (!url) return;

      audioRef.current?.pause();

      if (playingId === track.id) {
        setPlayingId(null);
        return;
      }

      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setPlayingId(null);
      audio.onerror = () => setPlayingId(null);
      void audio.play().catch(() => setPlayingId(null));
      setPlayingId(track.id);
    },
    [playingId],
  );

  if (state.status === "loading") {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-8 text-center">
        <AlertCircle className="size-6 text-destructive" aria-hidden />
        <p className="text-sm text-destructive">{state.message}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw /> Retry
        </Button>
      </div>
    );
  }

  const noMusicSelected = value === null;

  return (
    <ul className="space-y-2">
      {/* "No music" option — background music is optional. */}
      <li>
        <button
          type="button"
          aria-pressed={noMusicSelected}
          onClick={() => onSelect(null, null)}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            noMusicSelected
              ? "border-primary ring-1 ring-primary"
              : "border-border hover:border-primary/50",
          )}
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground">
            <VolumeX className="size-4" aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">No background music</span>
            <span className="block text-xs text-muted-foreground">
              Keep only the narration audio.
            </span>
          </span>
          {noMusicSelected && (
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <Check className="size-4" aria-hidden />
            </span>
          )}
        </button>
      </li>

      {state.tracks.length === 0 && (
        <li className="rounded-lg border border-border bg-secondary/20 p-6 text-center text-sm text-muted-foreground">
          No music tracks are available yet.
        </li>
      )}

      {state.tracks.map((track) => {
        const selected = track.id === value;
        const isPlaying = playingId === track.id;
        const url = previewUrlOf(track);
        const duration = formatDuration(track.duration_s);
        return (
          <li key={track.id}>
            <div
              className={cn(
                "flex items-center gap-3 rounded-lg border p-3 transition-colors",
                selected
                  ? "border-primary ring-1 ring-primary"
                  : "border-border hover:border-primary/50",
              )}
            >
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="size-9 shrink-0 rounded-full"
                disabled={!url}
                aria-label={
                  !url
                    ? `No preview available for ${track.name}`
                    : isPlaying
                      ? `Pause ${track.name} preview`
                      : `Play ${track.name} preview`
                }
                onClick={() => togglePreview(track)}
              >
                {!url ? <Music /> : isPlaying ? <Pause /> : <Play />}
              </Button>

              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(track.id, track.name)}
                className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left focus-visible:outline-none"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {track.name}
                  </span>
                  {duration && (
                    <span className="block text-xs text-muted-foreground">
                      {duration}
                    </span>
                  )}
                </span>
                {selected && (
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Check className="size-4" aria-hidden />
                  </span>
                )}
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
