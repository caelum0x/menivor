"use client";

import * as React from "react";
import { Camera, Film, Gamepad2 } from "lucide-react";

import { cn } from "@/lib/utils";

import type { VeryTimeLook } from "../api";
import { LOOKS } from "../model";

const ICONS: Record<VeryTimeLook, React.ComponentType<{ className?: string }>> = {
  console: Gamepad2,
  flash: Camera,
  atelier: Film,
};

/** Step 2: three large cards. One tap picks a look and moves on. */
export function LookStep({
  value,
  onPick,
}: Readonly<{ value: VeryTimeLook | null; onPick: (look: VeryTimeLook) => void }>) {
  return (
    <ul className="grid gap-3 sm:grid-cols-3" aria-label="Looks">
      {LOOKS.map((look) => {
        const Icon = ICONS[look.id];
        const selected = value === look.id;
        return (
          <li key={look.id}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onPick(look.id)}
              className={cn(
                "glass-subtle flex h-full w-full flex-col items-start gap-3 rounded-2xl p-5 text-left transition-colors",
                "hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected && "border-primary/70",
              )}
            >
              <Icon className="size-6 text-primary" aria-hidden />
              <span className="text-base font-semibold">{look.title}</span>
              <span className="text-sm text-muted-foreground">{look.description}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
