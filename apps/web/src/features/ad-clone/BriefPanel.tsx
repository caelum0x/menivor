"use client";

import * as React from "react";

import type { AdCloneBrief } from "./api";
import { beatLabel, briefSummary, seconds } from "./model";

/** "Clone brief": what we keep from the winning ad (hook, shot structure, pacing) and what we swap. */
export function BriefPanel({ brief, productName, count }: Readonly<{ brief: AdCloneBrief; productName: string; count: number }>) {
  const summary = briefSummary(brief);
  return (
    <section aria-label="Clone brief" className="glass-subtle space-y-3 rounded-2xl p-5">
      <h3 className="text-base font-semibold">Clone brief</h3>
      <ul className="space-y-1 text-sm">
        <li>Keeps the hook: {summary.hook}</li>
        <li>Keeps the shot structure: {summary.beats}</li>
        <li>Keeps the pacing: {summary.pacing}</li>
        <li>Swaps in: {productName}, with our own characters, voices and new lines</li>
        <li>
          Makes {count} {count === 1 ? "video" : "videos"}
        </li>
      </ul>
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Beat list ({brief.beats.length})</summary>
        <ol className="mt-2 space-y-1">
          {brief.beats.map((beat) => (
            <li key={beat.index} className="flex justify-between gap-3">
              <span>{beatLabel(beat)}</span>
              <span className="tabular-nums text-muted-foreground">{seconds(beat.end_s - beat.start_s)}</span>
            </li>
          ))}
        </ol>
      </details>
      <p className="text-xs text-muted-foreground">
        Only the structure is copied. The ad&apos;s characters, footage, music, voice and words are never reused.
      </p>
    </section>
  );
}
