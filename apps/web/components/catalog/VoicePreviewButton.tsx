"use client";

import * as React from "react";
import { Loader2, Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VoicePreviewButtonProps {
  /** Preview audio URL; when absent the control renders as disabled. */
  url?: string;
  /** Accessible name for the voice being previewed. */
  label: string;
}

/**
 * Play/pause control for a voice preview clip. Owns its own `<audio>` element so
 * multiple cards don't fight over one player; cleans up on unmount.
 */
export function VoicePreviewButton({ url, label }: VoicePreviewButtonProps) {
  const audioRef = React.useRef<HTMLAudioElement | null>(null);
  const [state, setState] = React.useState<"idle" | "loading" | "playing">(
    "idle",
  );

  React.useEffect(() => {
    return () => {
      audioRef.current?.pause();
      audioRef.current = null;
    };
  }, []);

  const toggle = React.useCallback(() => {
    if (!url) return;

    if (!audioRef.current) {
      const audio = new Audio(url);
      audio.addEventListener("playing", () => setState("playing"));
      audio.addEventListener("waiting", () => setState("loading"));
      audio.addEventListener("ended", () => setState("idle"));
      audio.addEventListener("pause", () => setState("idle"));
      audio.addEventListener("error", () => setState("idle"));
      audioRef.current = audio;
    }

    const audio = audioRef.current;
    if (state === "playing") {
      audio.pause();
      return;
    }
    setState("loading");
    void audio.play().catch(() => setState("idle"));
  }, [url, state]);

  if (!url) {
    return (
      <Button variant="outline" size="sm" disabled>
        <Play className="size-4" aria-hidden /> No preview
      </Button>
    );
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={toggle}
      aria-label={
        state === "playing" ? `Pause ${label}` : `Preview ${label}`
      }
    >
      {state === "loading" ? (
        <Loader2 className="size-4 animate-spin" aria-hidden />
      ) : state === "playing" ? (
        <Pause className="size-4" aria-hidden />
      ) : (
        <Play className="size-4" aria-hidden />
      )}
      {state === "playing" ? "Pause" : "Preview"}
    </Button>
  );
}
