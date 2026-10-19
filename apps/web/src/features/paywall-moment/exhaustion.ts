/**
 * The exhaustion event (MR2): a run finished, at least one reel is ready, and
 * the account has no credits left and no monthly plan. Each event is keyed by
 * the run's job ids, so the paywall moment shows once per event: reloading the
 * page or coming back later does not show it again, and the next run that
 * empties the balance is a new event.
 */

import type { MyPlan } from "@/src/features/plans/api";

export const SHOWN_KEY_PREFIX = "menivor.paywall-moment.shown:";

export function isExhausted(mine: MyPlan | null | undefined): boolean {
  if (!mine) return false;
  return mine.plan === null && Number(mine.credits) <= 0;
}

export function eventKey(jobIds: readonly string[]): string {
  return `${SHOWN_KEY_PREFIX}${[...jobIds].sort().join(",")}`;
}

export function hasShown(key: string, storage: Pick<Storage, "getItem"> | null = safeStorage()): boolean {
  try {
    return storage?.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function markShown(key: string, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(key, "1");
  } catch {
    // Storage blocked: the in-memory guard in the hook still holds for this view.
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}
