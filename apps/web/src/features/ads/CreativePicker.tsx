"use client";

import { CheckCircle2, Film } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AdVariant } from "@/src/features/ad-studio/api";

export const MAX_CREATIVES = 10;

/** Pick finished Ad Studio variants to run as ads (one ad set each). */
export function CreativePicker({
  variants,
  selected,
  onToggle,
}: {
  variants: AdVariant[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const ready = variants.filter((v) => v.status === "done" && v.video_url);
  if (ready.length === 0) {
    return <p className="text-sm text-muted-foreground">This project has no finished ads yet. Render some in Ad Studio first.</p>;
  }
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {ready.map((v) => {
        const on = selected.includes(v.id);
        const full = !on && selected.length >= MAX_CREATIVES;
        return (
          <button
            key={v.id}
            type="button"
            aria-pressed={on}
            disabled={full}
            onClick={() => onToggle(v.id)}
            className={cn(
              "relative overflow-hidden rounded-lg border text-left transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
              on ? "border-primary ring-1 ring-primary" : "border-border hover:bg-secondary/40",
            )}
          >
            {v.poster_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- presigned media URL
              <img src={v.poster_url} alt="" className="aspect-[9/16] w-full object-cover" />
            ) : (
              <div className="flex aspect-[9/16] w-full items-center justify-center bg-secondary/40">
                <Film className="h-6 w-6 text-muted-foreground" aria-hidden />
              </div>
            )}
            {on ? (
              <CheckCircle2 className="absolute right-2 top-2 h-5 w-5 rounded-full bg-background text-primary" aria-hidden />
            ) : null}
            <div className="space-y-0.5 p-2">
              <p className="line-clamp-2 text-xs font-medium">{v.hook || v.angle_label}</p>
              <p className="text-xs text-muted-foreground">
                {v.format_label} · {v.aspect}
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
}
