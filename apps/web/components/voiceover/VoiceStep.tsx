"use client";

import * as React from "react";
import { Info, Mic, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { VoicePicker } from "@/components/wizard/VoicePicker";
import {
  VoiceoverPicker,
  type UploadedVoiceover,
} from "@/components/voiceover/VoiceoverPicker";

interface VoiceStepProps {
  /** Selected TTS / cloned voice id (default path). */
  voiceId: string | null;
  onSelectVoice: (voiceId: string, label: string) => void;

  /** Whether the "use my own voiceover" (BYOV) mode is active. */
  useOwnVoiceover: boolean;
  onModeChange: (useOwnVoiceover: boolean) => void;

  /** The uploaded voiceover, or null before one is provided. */
  voiceover: UploadedVoiceover | null;
  onVoiceoverUploaded: (voiceover: UploadedVoiceover) => void;
  onVoiceoverClear: () => void;
}

interface ModeCardProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  description: string;
}

function ModeCard({ active, onClick, icon, title, description }: ModeCardProps) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "flex flex-1 items-start gap-3 rounded-lg border p-4 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        active
          ? "border-primary ring-1 ring-primary"
          : "border-border hover:border-primary/50",
      )}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full",
          active
            ? "bg-primary text-primary-foreground"
            : "bg-secondary text-muted-foreground",
        )}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium">{title}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  );
}

/**
 * Voice step of the reel wizard. Lets the creator EITHER pick a TTS / cloned
 * brand voice (the default {@link VoicePicker} path) OR bring their own recorded
 * / uploaded narration audio (BYOV). Choosing BYOV hides the TTS + brand-voice
 * pickers and notes that captions are auto-generated from the uploaded audio.
 */
export function VoiceStep({
  voiceId,
  onSelectVoice,
  useOwnVoiceover,
  onModeChange,
  voiceover,
  onVoiceoverUploaded,
  onVoiceoverClear,
}: VoiceStepProps) {
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row">
        <ModeCard
          active={!useOwnVoiceover}
          onClick={() => onModeChange(false)}
          icon={<Sparkles className="size-4" aria-hidden />}
          title="Menivor voice"
          description="Narrate with a curated TTS voice or your cloned brand voice."
        />
        <ModeCard
          active={useOwnVoiceover}
          onClick={() => onModeChange(true)}
          icon={<Mic className="size-4" aria-hidden />}
          title="Use my own voiceover"
          description="Record or upload your own narration audio instead of TTS."
        />
      </div>

      {useOwnVoiceover ? (
        <div className="space-y-4">
          <p className="flex items-start gap-2 rounded-lg border border-border bg-secondary/20 p-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Your audio becomes the reel&apos;s narration and drives the avatar
              lip-sync. Captions are auto-generated from your audio — no separate
              voice needed.
            </span>
          </p>
          <VoiceoverPicker
            value={voiceover}
            onUploaded={onVoiceoverUploaded}
            onClear={onVoiceoverClear}
          />
        </div>
      ) : (
        <VoicePicker value={voiceId} onSelect={onSelectVoice} />
      )}
    </div>
  );
}
