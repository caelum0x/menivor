import type { ReelforgeBridge } from "../electron/ipc";

/**
 * Ambient augmentation: the preload contextBridge installs a single typed object
 * on `window.reelforge`. Referencing the shared {@link ReelforgeBridge} keeps the
 * renderer's view of the bridge identical to what preload actually exposes.
 */
declare global {
  interface Window {
    readonly reelforge: ReelforgeBridge;
  }
}

export {};
