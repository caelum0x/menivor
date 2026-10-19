/** Bounded polling for async generation jobs. */

export interface PollResult<T> {
  value: T;
  /** True when the deadline elapsed before the job reached a terminal state. */
  timedOut: boolean;
}

/** Default ceiling for a single generation poll — long renders surface as a
 * "still processing" state rather than hanging the UI forever. */
export const MAX_POLL_MS = 5 * 60 * 1000;

/**
 * Poll `fetchOnce` every `intervalMs` until `isTerminal(value)` or the `maxMs`
 * deadline elapses. Fixes the previously-unbounded `while (!terminal)` loop: a
 * stuck job now returns `timedOut: true` with the last observed value instead of
 * spinning indefinitely. A failed fetch mid-poll propagates (the caller's
 * try/catch surfaces it) rather than being silently swallowed.
 */
export async function pollUntilTerminal<T>(
  fetchOnce: () => Promise<T>,
  isTerminal: (value: T) => boolean,
  opts: { intervalMs: number; maxMs?: number; onTick?: (value: T) => void },
): Promise<PollResult<T>> {
  const maxMs = opts.maxMs ?? MAX_POLL_MS;
  const deadline = Date.now() + maxMs;
  let value = await fetchOnce();
  opts.onTick?.(value);
  while (!isTerminal(value)) {
    if (Date.now() >= deadline) return { value, timedOut: true };
    await new Promise((r) => setTimeout(r, opts.intervalMs));
    value = await fetchOnce();
    opts.onTick?.(value);
  }
  return { value, timedOut: false };
}
