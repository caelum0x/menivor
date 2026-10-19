"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

import type { VeryTimeMode, VeryTimePlan } from "../api";
import { endCardLabel, extrasLabel, priceLabel } from "../model";

const MODES: readonly { id: VeryTimeMode; title: string; note: string }[] = [
  { id: "frames", title: "Frames", note: "Still frames with gentle camera moves." },
  { id: "animated", title: "Animated", note: "Every beat moves as real video." },
];

function prettyBeat(beat: string): string {
  const text = beat.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Step 7: the beats and the two prices. The wizard owns the Make button. */
export function PriceStep({
  plan,
  mode,
  onMode,
}: Readonly<{ plan: VeryTimePlan | null; mode: VeryTimeMode; onMode: (mode: VeryTimeMode) => void }>) {
  if (!plan) {
    return (
      <p className="flex min-h-40 items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Writing the five beats and pricing them
      </p>
    );
  }
  const last = plan.beats.length - 1;
  const extras = extrasLabel(plan);
  const endCard = endCardLabel(plan);
  return (
    <div className="space-y-5">
      <ol aria-label="Beats" className="divide-y divide-white/5 rounded-xl border border-white/10 text-sm">
        {plan.beats.map((beat, index) => (
          <li key={beat.index} className="flex items-start justify-between gap-3 px-3 py-2">
            <span>
              <span className="font-medium">{prettyBeat(beat.beat)}</span>
              {index === last ? <span className="mt-1 block text-muted-foreground">{beat.line}</span> : null}
            </span>
            <span className="shrink-0 tabular-nums text-muted-foreground">{beat.seconds.toFixed(1)} s</span>
          </li>
        ))}
      </ol>
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="sr-only">Version</legend>
        {MODES.map((option) => {
          const checked = option.id === mode;
          return (
            <label
              key={option.id}
              className={cn(
                "glass-subtle flex cursor-pointer flex-col gap-1 rounded-2xl p-4 focus-within:ring-2 focus-within:ring-ring",
                checked && "border-primary/70",
              )}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="vt-mode"
                  value={option.id}
                  checked={checked}
                  onChange={() => onMode(option.id)}
                  className="accent-primary"
                />
                <span className="font-semibold">{option.title}</span>
              </span>
              <span className="text-xs text-muted-foreground">{option.note}</span>
              <span className="text-sm tabular-nums" data-testid={`vt-price-${option.id}`}>
                {priceLabel(plan.quote[option.id])}
              </span>
            </label>
          );
        })}
      </fieldset>
      {endCard ? (
        <p className="text-sm" data-testid="vt-end-card">
          {endCard}
        </p>
      ) : null}
      {extras ? (
        <p className="text-xs text-muted-foreground" data-testid="vt-price-extras">
          {extras}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        About {Math.round(plan.duration_s ?? plan.quote.seconds)} seconds, 9:16. If anything fails, the credits come back.
      </p>
    </div>
  );
}
