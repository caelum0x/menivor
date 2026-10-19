import { BROLL_SOURCES, type BrollSource } from "@/lib/types";

/**
 * Jobs-library display metadata for stock-footage providers.
 * The backend (MPT's vendored `app/services/material.py`) is the source of
 * truth for which providers actually have keys configured; these labels are
 * purely for the source toggle chips.
 */
export interface BrollSourceOption {
  id: BrollSource;
  name: string;
}

/** Human-readable labels for each stock source, in {@link BROLL_SOURCES} order. */
const SOURCE_LABELS: Readonly<Record<BrollSource, string>> = {
  pexels: "Pexels",
  pixabay: "Pixabay",
};

/** The selectable source options for the B-roll source toggle. */
export const BROLL_SOURCE_OPTIONS: readonly BrollSourceOption[] =
  BROLL_SOURCES.map((id) => ({ id, name: SOURCE_LABELS[id] }));

/** A friendly label for a (possibly forward-compat) source value. */
export function sourceLabel(source: string): string {
  return (SOURCE_LABELS as Record<string, string>)[source] ?? source;
}
