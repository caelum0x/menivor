"use client";

// Reel-create presentation component.

import * as React from "react";
import { Sparkles } from "lucide-react";
import type { MusicGenerator } from "@/lib/types";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

interface MusicGenerateFormProps {
  /** Enabled AI-BGM providers (non-empty; the parent only renders this then). */
  generators: readonly MusicGenerator[];
  /** Current brief, or null when empty. */
  prompt: string | null;
  /** Chosen provider id, or null to auto-select the first enabled provider. */
  provider: string | null;
  /**
   * Emits the next brief (empty string -> null) and provider (null = auto). The
   * parent is responsible for clearing any library `music_id` selection.
   */
  onChange: (prompt: string | null, provider: string | null) => void;
}

/**
 * Resolve the provider whose prompt cap applies: the explicitly chosen one, or
 * (when auto) the first enabled provider the backend would pick.
 */
function effectiveGenerator(
  generators: readonly MusicGenerator[],
  provider: string | null,
): MusicGenerator | undefined {
  if (provider) {
    const match = generators.find((g) => g.id === provider);
    if (match) return match;
  }
  return generators[0];
}

/**
 * "Generate with AI" background-music form: a text brief the chosen enabled
 * provider (ElevenLabs / Sonilo, via the vendored MPT integrations) turns into a
 * custom royalty-free track. Enforces the active provider's `max_prompt_length`
 * and, when more than one provider is enabled, lets the user pick which one (or
 * leave it on auto).
 */
export function MusicGenerateForm({
  generators,
  prompt,
  provider,
  onChange,
}: MusicGenerateFormProps) {
  const active = effectiveGenerator(generators, provider);
  const maxLength = active?.max_prompt_length ?? 0;
  const text = prompt ?? "";
  const remaining = maxLength > 0 ? maxLength - text.length : null;

  const handlePromptChange = (next: string) => {
    onChange(next.length > 0 ? next : null, provider);
  };

  const handleProviderChange = (next: string) => {
    // "" is the auto-select sentinel -> null. Keep the current brief.
    onChange(prompt, next ? next : null);
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <p className="text-xs text-muted-foreground">
          Describe the vibe and we generate an original, royalty-free track
          matched to your reel. It is ducked under the narration automatically.
        </p>
      </div>

      {generators.length > 1 && (
        <div className="space-y-2">
          <Label htmlFor="bgm-provider">Generator</Label>
          <Select
            id="bgm-provider"
            value={provider ?? ""}
            onChange={(e) => handleProviderChange(e.target.value)}
          >
            <option value="">Auto (recommended)</option>
            {generators.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </Select>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="bgm-prompt">Describe the music</Label>
          {remaining !== null && (
            <span
              className={
                remaining < 0
                  ? "text-xs text-destructive"
                  : "text-xs text-muted-foreground"
              }
            >
              {text.length}/{maxLength}
            </span>
          )}
        </div>
        <Textarea
          id="bgm-prompt"
          value={text}
          rows={4}
          maxLength={maxLength > 0 ? maxLength : undefined}
          placeholder="e.g. upbeat lo-fi hip-hop with a warm bassline, relaxed and modern, no vocals"
          onChange={(e) => handlePromptChange(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          {generators.length === 1 && active
            ? `Generated with ${active.name}. Leave blank to skip background music.`
            : "Leave blank to skip background music."}
        </p>
      </div>
    </div>
  );
}
