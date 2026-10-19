"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { VeryTimeEngine, VeryTimeTakes } from "../api";
import { DELIVERIES, REPLY_MAX, type VoiceChoice } from "../model";

const ENGINES: readonly { id: VeryTimeEngine; title: string; note: string }[] = [
  { id: "free", title: "Free voice", note: "Clear and quick. No extra cost." },
  { id: "eleven_v3", title: "Premium voice", note: "Expressive studio voice, +1 credit." },
];

/** Step 5: who says the line and how. Making takes is optional; the server picks when none is chosen. */
export function VoiceStep({
  voice,
  takes,
  makingTakes,
  takesProblem,
  onChange,
  onPickTake,
  onMakeTakes,
}: Readonly<{
  voice: VoiceChoice;
  takes: VeryTimeTakes | null;
  makingTakes: boolean;
  takesProblem: string;
  onChange: (change: Partial<Omit<VoiceChoice, "takeKey">>) => void;
  onPickTake: (key: string) => void;
  onMakeTakes: () => void;
}>) {
  return (
    <div className="space-y-5">
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="sr-only">Voice</legend>
        {ENGINES.map((engine) => {
          const checked = voice.engine === engine.id;
          return (
            <label
              key={engine.id}
              className={cn(
                "glass-subtle flex cursor-pointer flex-col gap-1 rounded-2xl p-4 focus-within:ring-2 focus-within:ring-ring",
                checked && "border-primary/70",
              )}
            >
              <span className="flex items-center gap-2">
                <input
                  type="radio"
                  name="vt-engine"
                  value={engine.id}
                  checked={checked}
                  onChange={() => onChange({ engine: engine.id })}
                  className="accent-primary"
                />
                <span className="font-semibold">{engine.title}</span>
              </span>
              <span className="text-xs text-muted-foreground">{engine.note}</span>
            </label>
          );
        })}
      </fieldset>

      <div className="space-y-2">
        <p className="text-sm font-medium" id="vt-delivery-label">Delivery</p>
        <div className="flex flex-wrap gap-2" role="group" aria-labelledby="vt-delivery-label">
          {DELIVERIES.map((delivery) => (
            <Button
              key={delivery.id}
              type="button"
              size="sm"
              variant={voice.delivery === delivery.id ? "default" : "outline"}
              aria-pressed={voice.delivery === delivery.id}
              onClick={() => onChange({ delivery: delivery.id })}
            >
              {delivery.title}
            </Button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="vt-reply">Second voice answers</Label>
        <Input
          id="vt-reply"
          value={voice.reply}
          maxLength={REPLY_MAX}
          autoComplete="off"
          placeholder="Optional"
          onChange={(event) => onChange({ reply: event.target.value })}
        />
      </div>

      <div className="space-y-3">
        <Button type="button" variant="outline" onClick={onMakeTakes} disabled={makingTakes}>
          {makingTakes ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Make takes
        </Button>
        {takesProblem ? <p role="alert" className="text-sm text-destructive">{takesProblem}</p> : null}
        {takes && takes.takes.length > 0 ? (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Pick a take</legend>
            {takes.takes.map((take, index) => (
              <label key={take.key} className="glass-subtle flex flex-wrap items-center gap-3 rounded-xl p-3">
                <input
                  type="radio"
                  name="vt-take"
                  value={take.key}
                  checked={voice.takeKey === take.key}
                  onChange={() => onPickTake(take.key)}
                  className="accent-primary"
                />
                <span className="text-sm font-medium">
                  Take {index + 1}
                  {take.key === takes.recommended ? <span className="ml-2 text-xs text-primary">Flattest</span> : null}
                </span>
                <span className="text-xs tabular-nums text-muted-foreground">{take.seconds.toFixed(1)} s</span>
                <audio controls preload="none" src={take.url} className="h-8 max-w-full" aria-label={`Take ${index + 1}`} />
              </label>
            ))}
          </fieldset>
        ) : (
          <p className="text-xs text-muted-foreground">Optional. Without takes, the flattest one is picked for you.</p>
        )}
      </div>
    </div>
  );
}
