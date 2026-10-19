"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

import type { AdCloneVariation } from "./api";
import { sortedEstimates, speakerName, usd } from "./model";

/** One clone: the new script, the price on every engine (chosen one marked) and Midjourney prompts. */
export function VariationCard({ variation, index }: Readonly<{ variation: AdCloneVariation; index: number }>) {
  const { plan, engine } = variation;
  return (
    <article aria-label={`Version ${index + 1}`} className="glass-subtle space-y-4 rounded-2xl p-5">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-base font-semibold">Version {String.fromCharCode(65 + index)}</h3>
        <span className="text-sm text-muted-foreground">
          {plan.aspect}, {plan.shots.length} talking shots, {plan.stills.length} stills
        </span>
      </header>
      <ol className="space-y-1 text-sm">
        {plan.lines.map((line) => (
          <li key={line.id}>
            <span className="font-medium">{speakerName(line.speaker)}:</span> {line.text}
          </li>
        ))}
      </ol>
      <table className="w-full text-sm" aria-label="Price per engine">
        <thead>
          <tr className="text-left text-muted-foreground">
            <th className="font-normal">Engine</th>
            <th className="text-right font-normal">Estimate</th>
          </tr>
        </thead>
        <tbody>
          {sortedEstimates(variation.estimates).map((row) => (
            <tr key={row.engine} className={cn(row.engine === engine.engine && "font-semibold")}>
              <td>
                {row.label}
                {row.engine === engine.engine ? " (chosen)" : ""}
                {row.configured ? "" : " (no key)"}
              </td>
              <td className="text-right tabular-nums">
                {usd(row.usd)}
                {row.price_basis === "estimate" ? " (estimate)" : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">{engine.reason}</p>
      {variation.estimates.some((row) => row.price_basis === "estimate") ? (
        <p className="text-xs text-muted-foreground">
          Estimates are not from an official price page yet; the credits held are settled to the real cost after the
          render.
        </p>
      ) : null}
      {plan.clone.writer_note ? <p className="text-xs text-muted-foreground">{plan.clone.writer_note}</p> : null}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">Midjourney prompts ({variation.midjourney.length})</summary>
        <ul className="mt-2 space-y-2">
          {variation.midjourney.map((p) => (
            <li key={p.still}>
              <p className="text-xs text-muted-foreground">Save as {p.save_as}</p>
              <code className="block whitespace-pre-wrap break-words rounded-lg bg-muted p-2 text-xs">{p.prompt_v7}</code>
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}
