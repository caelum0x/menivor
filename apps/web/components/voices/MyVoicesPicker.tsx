"use client";

import * as React from "react";
import Link from "next/link";
import { AlertCircle, Check, Mic, Settings2 } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useMyVoices } from "@/components/voices/use-my-voices";
import {
  isVoiceReady,
  stripElevenLabsPrefix,
} from "@/components/voices/voice-utils";

interface MyVoicesPickerProps {
  /** Currently selected bare provider voice id (prefix stripped), or null. */
  value: string | null;
  /** Reports the chosen voice's bare id + display name upward. */
  onSelect: (voiceId: string, label: string) => void;
}

/**
 * "Your voices" section for the wizard voice step: lists the caller's cloned
 * brand voices (GET /voices/mine) as selectable narrators alongside the curated
 * ElevenLabs voices. Selecting a voice reports its bare provider id (the
 * `elevenlabs:` prefix stripped) so the wizard re-adds it consistently when
 * building `voice_name = "elevenlabs:<id>"`.
 */
export function MyVoicesPicker({ value, onSelect }: MyVoicesPickerProps) {
  const { status, voices, errorMessage } = useMyVoices();

  // Hide the whole section only when the user has never created a voice and
  // there was no error — keeps the curated list uncluttered for new users.
  if (status === "ready" && voices.length === 0) return null;

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Your voices
        </h3>
        <Link
          href="/voices"
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          <Settings2 className="size-3.5" aria-hidden /> Manage
        </Link>
      </div>

      {status === "loading" && (
        <div className="space-y-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {status === "error" && (
        <p
          role="alert"
          className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {errorMessage}
        </p>
      )}

      {status === "ready" && voices.length > 0 && (
        <ul className="space-y-2">
          {voices.map((voice) => {
            const bareId = stripElevenLabsPrefix(voice.voice_id);
            const selected = bareId === value;
            const ready = isVoiceReady(voice);
            return (
              <li key={voice.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  disabled={!ready}
                  onClick={() => onSelect(bareId, voice.name)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    selected
                      ? "border-primary ring-1 ring-primary"
                      : "border-border hover:border-primary/50",
                  )}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
                    <Mic className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {voice.name}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {ready ? "Brand voice" : `Brand voice · ${voice.status}`}
                    </span>
                  </span>
                  {selected && (
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Check className="size-4" aria-hidden />
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
