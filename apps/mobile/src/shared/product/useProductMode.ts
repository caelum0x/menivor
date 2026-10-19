/**
 * Product-mode gate.
 *
 * Menivor ships PRODUCT-FIRST: the app presents itself as a finished product,
 * not a waitlist landing. `isWaitlistMode()` is therefore OFF by default and
 * only turns on when the owner explicitly sets EXPO_PUBLIC_WAITLIST_MODE="1"
 * (e.g. a marketing pre-launch build). This flag now only controls the LANDING
 * copy (whether a "Join the waitlist" link appears); whether the Create tab
 * actually offers generation is decided independently by the backend capability
 * check (`generationAllowed`), which honestly degrades to the waitlist home when
 * an account has no generation access — so turning this off can never dead-end a
 * user against a provider-less backend.
 *
 * This is a plain function + trivial hook (no state) so it is cheap to call
 * anywhere and easy to unit test.
 */

/**
 * True when the app should present the pre-launch waitlist landing. Defaults to
 * `false` (product-first); only an explicit "1" opts back into the waitlist copy.
 */
export function isWaitlistMode(): boolean {
  return process.env.EXPO_PUBLIC_WAITLIST_MODE === "1";
}

export interface ProductMode {
  /** Whether the waitlist-era experience is active. */
  readonly waitlistMode: boolean;
}

/** React hook wrapper so screens read product mode consistently. */
export function useProductMode(): ProductMode {
  return { waitlistMode: isWaitlistMode() };
}
