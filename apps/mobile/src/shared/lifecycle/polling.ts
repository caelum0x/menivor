import { makeAbortError } from "@/src/shared/api";

export interface PollUntilTerminalOptions<T> {
  fetchSnapshot: (signal?: AbortSignal) => Promise<T>;
  isTerminal: (snapshot: T) => boolean;
  onSnapshot: (snapshot: T) => void;
  signal?: AbortSignal;
  intervalMs?: number;
  maxAttempts?: number;
  timeoutMessage?: string;
  timeoutError?: () => Error;
}

/** Cancellable polling primitive shared by mobile generation resources. */
export async function pollUntilTerminal<T>({
  fetchSnapshot,
  isTerminal,
  onSnapshot,
  signal,
  intervalMs = 3000,
  maxAttempts = 400,
  timeoutMessage = "Polling timed out.",
  timeoutError,
}: PollUntilTerminalOptions<T>): Promise<T> {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (signal?.aborted) throw makeAbortError("Polling aborted");
    const snapshot = await fetchSnapshot(signal);
    // The consumer may have aborted while the fetch was in flight; don't push a
    // stale snapshot (setState) into a caller that has already torn down.
    if (signal?.aborted) throw makeAbortError("Polling aborted");
    onSnapshot(snapshot);
    if (isTerminal(snapshot)) return snapshot;
    await abortableDelay(intervalMs, signal);
  }
  throw timeoutError?.() ?? new Error(timeoutMessage);
}

export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(makeAbortError());
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(makeAbortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
