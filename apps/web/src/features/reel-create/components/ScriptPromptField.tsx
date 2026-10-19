"use client";

// Reel-create presentation component.

import type { Language } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  LANGUAGE_OPTIONS,
  MAX_DURATION_S,
  MIN_DURATION_S,
  DURATION_STEP_S,
} from "@/components/wizard/types";

const MAX_SUBJECT_LENGTH = 500;

export interface ScriptPromptValue {
  videoSubject: string;
  prompt: string;
  language: Language;
  targetDurationS: number;
}

interface ScriptPromptFieldProps {
  value: ScriptPromptValue;
  onChange: (patch: Partial<ScriptPromptValue>) => void;
}

/**
 * Captures the creative brief: the required video subject, an optional custom
 * script/prompt, the narration language, and the target duration. Emits
 * immutable patches to the parent wizard.
 */
export function ScriptPromptField({ value, onChange }: ScriptPromptFieldProps) {
  const subjectLeft = MAX_SUBJECT_LENGTH - value.videoSubject.length;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="video-subject">
            What is your reel about?{" "}
            <span className="text-destructive">*</span>
          </Label>
          <span
            className={subjectLeft < 0 ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
          >
            {value.videoSubject.length}/{MAX_SUBJECT_LENGTH}
          </span>
        </div>
        <Input
          id="video-subject"
          value={value.videoSubject}
          maxLength={MAX_SUBJECT_LENGTH}
          placeholder="e.g. A 30-second demo of our new AI note-taking app"
          onChange={(e) => onChange({ videoSubject: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">
          A short subject is enough — we write the UGC script for you.
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="video-prompt">Custom script or extra direction (optional)</Label>
        <Textarea
          id="video-prompt"
          value={value.prompt}
          rows={4}
          placeholder="Paste your own script, or add tone/talking points (e.g. 'casual, mention the free trial, end with a CTA to sign up')."
          onChange={(e) => onChange({ prompt: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">
          Leave blank to let the AI generate the script from your subject.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="video-language">Language</Label>
          <Select
            id="video-language"
            value={value.language}
            onChange={(e) =>
              onChange({ language: e.target.value as Language })
            }
          >
            {LANGUAGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="video-duration">Target duration</Label>
            <span className="text-sm font-medium tabular-nums text-foreground">
              {value.targetDurationS}s
            </span>
          </div>
          <input
            id="video-duration"
            type="range"
            min={MIN_DURATION_S}
            max={MAX_DURATION_S}
            step={DURATION_STEP_S}
            value={value.targetDurationS}
            onChange={(e) =>
              onChange({ targetDurationS: Number(e.target.value) })
            }
            aria-valuetext={`${value.targetDurationS} seconds`}
            className="h-2 w-full cursor-pointer appearance-none rounded-full bg-secondary accent-primary"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{MIN_DURATION_S}s</span>
            <span>{MAX_DURATION_S}s</span>
          </div>
        </div>
      </div>
    </div>
  );
}
