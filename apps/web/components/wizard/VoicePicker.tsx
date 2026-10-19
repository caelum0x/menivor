"use client";

import * as React from "react";
import { AlertCircle, Check, Pause, Play, RefreshCw } from "lucide-react";
import type { Voice } from "@/lib/types";
import { ApiError, listVoices } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { MyVoicesPicker } from "@/components/voices/MyVoicesPicker";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface VoicePickerProps {
  value: string | null;
  onSelect: (voiceId: string, label: string) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; voices: readonly Voice[] };

type Group = "tr" | "en" | "other";

const GROUP_LABELS: Record<Group, string> = {
  tr: "Türkçe",
  en: "English",
  other: "Other languages",
};

const GROUP_ORDER: readonly Group[] = ["tr", "en", "other"];

function voiceName(voice: Voice): string {
  return voice.name || voice.voice_id;
}

/** Classify a voice into a TR / EN / other group from its labels + name. */
function classify(voice: Voice): Group {
  const hay = [
    voice.labels?.language,
    voice.labels?.accent,
    voice.labels?.description,
    voice.name,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  if (hay.includes("turkish") || /\btr\b|türk/.test(hay)) return "tr";
  if (hay.includes("english") || /\ben\b/.test(hay)) return "en";
  return "other";
}

function groupVoices(
  voices: readonly Voice[],
): ReadonlyArray<readonly [Group, readonly Voice[]]> {
  const buckets: Record<Group, Voice[]> = { tr: [], en: [], other: [] };
  for (const voice of voices) {
    buckets[classify(voice)].push(voice);
  }
  return GROUP_ORDER.map(
    (group) => [group, buckets[group]] as const,
  ).filter(([, list]) => list.length > 0);
}

/**
 * List of ElevenLabs voices from `GET /voices`, grouped into Turkish / English
 * / other, each with an inline audio preview. Reports the chosen voice id and
 * display name upward.
 */
export function VoicePicker({ value, onSelect }: VoicePickerProps) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });
  const [playingId, setPlayingId] = React.useState<string | null>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const voices = await listVoices({ token });
      setState({ status: "ready", voices });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load voices. Please try again.");
      setState({ status: "error", message });
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Stop any playing audio when unmounting.
  React.useEffect(() => {
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  const togglePreview = React.useCallback(
    (voice: Voice) => {
      if (!voice.preview_url) return;

      // Pause whatever is currently playing.
      audioRef.current?.pause();

      if (playingId === voice.voice_id) {
        setPlayingId(null);
        return;
      }

      const audio = new Audio(voice.preview_url);
      audioRef.current = audio;
      audio.onended = () => setPlayingId(null);
      audio.onerror = () => setPlayingId(null);
      void audio.play().catch(() => setPlayingId(null));
      setPlayingId(voice.voice_id);
    },
    [playingId],
  );

  const grouped = state.status === "ready" ? groupVoices(state.voices) : [];

  return (
    <div className="space-y-6">
      {/* Cloned "brand voices" the caller owns, selectable as narrators. */}
      <MyVoicesPicker value={value} onSelect={onSelect} />

      {state.status === "loading" && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {state.status === "error" && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-8 text-center">
          <AlertCircle className="size-6 text-destructive" aria-hidden />
          <p className="text-sm text-destructive">{state.message}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void load()}
          >
            <RefreshCw /> Retry
          </Button>
        </div>
      )}

      {state.status === "ready" && grouped.length === 0 && (
        <div className="rounded-lg border border-border bg-secondary/20 p-8 text-center text-sm text-muted-foreground">
          No curated voices are available yet. Please check back soon.
        </div>
      )}

      {grouped.map(([group, voices]) => (
        <section key={group} className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {GROUP_LABELS[group]}
          </h3>
          <ul className="space-y-2">
            {voices.map((voice) => {
              const selected = voice.voice_id === value;
              const isPlaying = playingId === voice.voice_id;
              const name = voiceName(voice);
              return (
                <li key={voice.voice_id}>
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
                      disabled={!voice.preview_url}
                      aria-label={
                        isPlaying ? `Pause ${name} preview` : `Play ${name} preview`
                      }
                      onClick={() => togglePreview(voice)}
                    >
                      {isPlaying ? <Pause /> : <Play />}
                    </Button>

                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(voice.voice_id, name)}
                      className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left focus-visible:outline-none"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium">
                          {name}
                        </span>
                        {voice.category && (
                          <span className="block truncate text-xs text-muted-foreground">
                            {voice.category}
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
        </section>
      ))}
    </div>
  );
}
