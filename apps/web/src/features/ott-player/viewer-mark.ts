/**
 * The moving viewer code on paid titles (Wave Q QM1.5, U17).
 *
 * The API returns a short code derived from the salted viewer hash; the
 * player shows it small and faint over the picture and moves it to another
 * spot every 30 seconds, so a screen recording carries it wherever it is
 * cropped. The spot is chosen from the code and the 30-second slot, so it
 * changes on a fixed beat without randomness in render.
 */

export const MOVE_EVERY_MS = 30_000;

/** Where to draw the code: left and top in percent of the picture, kept clear of the edges. */
export function markSpot(mark: string, nowMs: number): { left: number; top: number } {
  const slot = Math.floor(nowMs / MOVE_EVERY_MS);
  let h = 2166136261;
  for (const ch of `${mark}:${slot}`) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return { left: 8 + (h % 70), top: 8 + ((h >>> 8) % 76) };
}

/** Milliseconds until the next move. */
export function untilNextMove(nowMs: number): number {
  return MOVE_EVERY_MS - (nowMs % MOVE_EVERY_MS);
}
