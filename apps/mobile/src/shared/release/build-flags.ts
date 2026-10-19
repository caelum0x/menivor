/**
 * Build flags for what a shipped (store) build may expose.
 *
 * Release builds (`__DEV__ === false`) only ever show the finished creator
 * product. Internal tools (labs, admin, developer keys, token transfers) and the
 * screenshot demo mode exist only in Metro dev sessions.
 */

declare const __DEV__: boolean | undefined;

/** True only in a Metro development session, never in a store build. */
export function isDevBuild(): boolean {
  return typeof __DEV__ !== "undefined" && __DEV__ === true;
}

/** Env flag that asks for the seeded demo workspace (dev sessions only). */
export const DEMO_ENV_FLAG = "EXPO_PUBLIC_MENIVOR_DEMO";

/**
 * Demo mode: seeded, real-looking projects and renders for screenshots and
 * walkthroughs, answered locally instead of by the API.
 *
 * It needs BOTH a dev build and `EXPO_PUBLIC_MENIVOR_DEMO=1`. A store build can
 * never enable it, even if the env flag leaks into a release profile.
 */
export function isDemoMode(
  dev: boolean = isDevBuild(),
  flag: string | undefined = process.env.EXPO_PUBLIC_MENIVOR_DEMO,
): boolean {
  return dev === true && flag?.trim() === "1";
}

/** Env flag that opens the internal lab screens (dev sessions only). */
export const LAB_ENV_FLAG = "EXPO_PUBLIC_ENABLE_LAB";

/**
 * Lab mode: the internal screens (labs, admin consoles, developer/API keys,
 * Mint token transfers, marketplaces, team admin) become reachable.
 *
 * Off by default. It needs BOTH a dev build and `EXPO_PUBLIC_ENABLE_LAB=1`, so
 * a store build can never reach those routes, even if the flag leaks into a
 * release profile.
 */
export function isLabEnabled(
  dev: boolean = isDevBuild(),
  flag: string | undefined = process.env.EXPO_PUBLIC_ENABLE_LAB,
): boolean {
  return dev === true && flag?.trim() === "1";
}
