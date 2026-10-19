"use client";

import { useState } from "react";
import { parseSource } from "@/src/features/create-compose/one-flow/plan";
import { detectLinkKind } from "@/src/features/create-compose/one-flow/link-kind";

interface HeroLinkInputProps {
  /** Lifted to the parent (e.g. to also drive the free App Store audit preview). Uncontrolled when omitted. */
  readonly value?: string;
  readonly onValueChange?: (value: string) => void;
}

/**
 * The landing box's field. Works before any JavaScript loads (plain GET
 * submit reads the input by `name="q"`); once hydrated it shows one quiet
 * line naming what the pasted link is ("TikTok post detected"). Controlled
 * when a parent passes `value`/`onValueChange` (so the parent can also show
 * the free App Store/Play audit preview for the same pasted link), otherwise
 * manages its own state.
 */
export function HeroLinkInput({ value: controlledValue, onValueChange }: HeroLinkInputProps = {}) {
  const [internalValue, setInternalValue] = useState("");
  const value = controlledValue ?? internalValue;
  const parsed = parseSource(value);
  const label = parsed?.kind === "link" ? detectLinkKind(parsed.value).label : "";
  return (
    <div className="flex w-full min-w-0 flex-col gap-1.5 sm:flex-1">
      <input
        id="hero-create-input"
        name="q"
        type="text"
        required
        maxLength={600}
        autoComplete="off"
        placeholder="Paste an App Store link, any other link, or type a topic"
        aria-describedby="hero-create-kind"
        value={controlledValue !== undefined ? controlledValue : undefined}
        defaultValue={controlledValue === undefined ? "" : undefined}
        onChange={(event) => {
          setInternalValue(event.target.value);
          onValueChange?.(event.target.value);
        }}
        className="neu-inset h-12 w-full min-w-0 rounded-xl px-4 text-base transition-[border-color,box-shadow] placeholder:text-muted-foreground focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <p id="hero-create-kind" aria-live="polite" className="min-h-4 px-1 text-xs text-muted-foreground">
        {label}
      </p>
    </div>
  );
}
