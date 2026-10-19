/**
 * Route: /clipfarm-console — the unattended channel runner console (read runs +
 * pacing, trigger a render pass, pace pending clips onto the calendar). Accepts
 * an optional `?channel_id=` entry point. Thin wrapper over the feature screen.
 */

export { ClipfarmConsoleScreen as default } from "@/src/features/clipfarm-console";
