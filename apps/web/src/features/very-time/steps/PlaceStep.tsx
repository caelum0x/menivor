"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import {
  PLACE_MAX,
  RITUAL_MAX,
  RITUAL_PLACEHOLDER,
  placeProblem,
  previewLine,
  splitByTerms,
  termsIn,
  type VeryTimeForm,
} from "../model";

function Marked({ text, terms }: Readonly<{ text: string; terms: readonly string[] }>) {
  return (
    <>
      {splitByTerms(text, terms).map((part, index) =>
        part.blocked ? (
          <mark key={index} className="rounded bg-destructive/20 px-0.5 text-foreground">
            {part.text}
          </mark>
        ) : (
          <React.Fragment key={index}>{part.text}</React.Fragment>
        ),
      )}
    </>
  );
}

/** Step 1: the place word with a live line preview, and one everyday ritual. */
export function PlaceStep({
  form,
  blocked,
  onChange,
}: Readonly<{
  form: VeryTimeForm;
  blocked: readonly string[];
  onChange: (change: Partial<VeryTimeForm>) => void;
}>) {
  const problem = placeProblem(form.place);
  const placeBlocked = termsIn(form.place, blocked);
  const ritualBlocked = termsIn(form.ritual, blocked);
  const line = previewLine(form.place);

  return (
    <div className="space-y-5">
      {blocked.length > 0 ? (
        <div role="alert" className="space-y-2 rounded-xl border border-destructive/40 p-3 text-sm">
          <p>A few words cannot be used. Change these and try again. Nothing was charged.</p>
          <ul aria-label="Words to change" className="flex flex-wrap gap-2">
            {blocked.map((term) => (
              <li key={term}>
                <mark className="rounded bg-destructive/20 px-1.5 py-0.5 text-foreground">{term}</mark>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="vt-place">Your place</Label>
        <Input
          id="vt-place"
          value={form.place}
          maxLength={PLACE_MAX + 8}
          autoComplete="off"
          placeholder="Turkish"
          aria-invalid={problem !== "" || placeBlocked.length > 0}
          aria-describedby="vt-place-help vt-line-preview"
          onChange={(event) => onChange({ place: event.target.value })}
        />
        <p id="vt-place-help" className="min-h-5 text-xs text-muted-foreground">
          {problem || "One word or two: a country, a city, a family, a job."}
        </p>
      </div>

      <figure className="glass-subtle rounded-2xl p-4">
        <figcaption className="mb-1 text-xs text-muted-foreground">The line</figcaption>
        <p id="vt-line-preview" data-testid="vt-line-preview" aria-live="polite" className="text-lg font-medium">
          <Marked text={line} terms={placeBlocked} />
        </p>
      </figure>

      <div className="space-y-2">
        <Label htmlFor="vt-ritual">An everyday ritual from that place</Label>
        <Input
          id="vt-ritual"
          value={form.ritual}
          maxLength={RITUAL_MAX}
          autoComplete="off"
          placeholder={RITUAL_PLACEHOLDER}
          aria-invalid={ritualBlocked.length > 0}
          aria-describedby="vt-ritual-help"
          onChange={(event) => onChange({ ritual: event.target.value })}
        />
        <p id="vt-ritual-help" className="min-h-5 text-xs text-muted-foreground">
          {ritualBlocked.length > 0 ? (
            <Marked text={form.ritual} terms={ritualBlocked} />
          ) : (
            "Small and true beats famous. Think of a cup, a pet, a late-night shop."
          )}
        </p>
      </div>
    </div>
  );
}
