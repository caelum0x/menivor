"use client";

import * as React from "react";

/**
 * One audible reel at a time. A reel that wants sound claims the focus; every
 * other reel sees the new owner and mutes itself. Module state, so every tile,
 * hero and the expanded player on the page share it.
 */
type Listener = () => void;

let owner: string | null = null;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function claimSound(id: string): void {
  if (owner === id) return;
  owner = id;
  emit();
}

export function releaseSound(id: string): void {
  if (owner !== id) return;
  owner = null;
  emit();
}

export function soundOwner(): string | null {
  return owner;
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The id of the reel that currently has sound (null: every reel is muted). */
export function useSoundOwner(): string | null {
  return React.useSyncExternalStore(subscribe, soundOwner, () => null);
}

/** Test helper: back to "nobody has sound". */
export function resetSoundFocus(): void {
  owner = null;
  emit();
}
