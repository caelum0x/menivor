"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import { PAYOFFS, type SoundChoice } from "../model";

/** Step 6: sound effects, room sound and how the last line is spoken. */
export function SoundStep({
  sound,
  onChange,
}: Readonly<{ sound: SoundChoice; onChange: (sound: SoundChoice) => void }>) {
  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={sound.sfx}
            onChange={(event) => onChange({ ...sound, sfx: event.target.checked })}
            className="mt-1 accent-primary"
          />
          <span>Sound effects on each shot (+1 credit)</span>
        </label>
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            checked={sound.roomTone}
            onChange={(event) => onChange({ ...sound, roomTone: event.target.checked })}
            className="mt-1 accent-primary"
          />
          <span>
            Keep the video&apos;s own room sound
            <span className="block text-xs text-muted-foreground">Animated version only.</span>
          </span>
        </label>
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">The last line</legend>
        {PAYOFFS.map((option) => {
          const checked = sound.payoff === option.id;
          return (
            <label
              key={option.id}
              className={cn(
                "glass-subtle flex cursor-pointer items-start gap-3 rounded-xl p-3 focus-within:ring-2 focus-within:ring-ring",
                checked && "border-primary/70",
              )}
            >
              <input
                type="radio"
                name="vt-payoff"
                value={option.id}
                checked={checked}
                onChange={() => onChange({ ...sound, payoff: option.id })}
                className="mt-1 accent-primary"
              />
              <span className="text-sm">
                <span className="font-medium">{option.title}</span>
                <span className="block text-xs text-muted-foreground">{option.note}</span>
              </span>
            </label>
          );
        })}
        <p className="text-xs text-muted-foreground">
          Speaking and mouth matching apply to the animated version; the frames version uses the voice-over.
        </p>
      </fieldset>
    </div>
  );
}
