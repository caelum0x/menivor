/**
 * Canonical IPC channel names + payload contracts shared by the main process,
 * the preload bridge, and (as types only) the renderer. Keeping every channel
 * string in one place prevents typo-drift between `ipcMain.handle` and
 * `ipcRenderer.invoke`.
 *
 * SECURITY: these are the ONLY messages the renderer can send to main. Every
 * handler in `main.ts` re-validates its input — the types here are a convenience,
 * not a trust boundary.
 */

export const IpcChannel = {
  ConfigGet: "config:get",
  ConfigSave: "config:save",
  ApiRequest: "api:request",
  ScreenSources: "screen:getSources",
} as const;

export type IpcChannelName = (typeof IpcChannel)[keyof typeof IpcChannel];

/** HTTP methods the renderer is allowed to ask main to perform. */
export const ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
export type HttpMethod = (typeof ALLOWED_METHODS)[number];

/**
 * Public (non-secret) view of the app config returned to the renderer. The raw
 * API token NEVER crosses the bridge — the renderer only learns whether one is
 * configured, and main attaches it to outgoing requests itself.
 */
export interface PublicConfig {
  /** API base URL, e.g. `http://localhost:8080/api/v1` (no trailing slash). */
  apiBase: string;
  /** True when an API token is stored in main (its value is never exposed). */
  tokenSet: boolean;
}

/** Patch accepted by `config:save`. Every field is optional + validated in main. */
export interface ConfigPatch {
  apiBase?: string;
  /** Pass `""` to clear the stored token; omit to leave it untouched. */
  token?: string;
}

/** Envelope for an authenticated API call proxied through main. */
export interface ApiRequestInput {
  method?: HttpMethod;
  /** Path beginning with `/`, appended to the configured API base. */
  path: string;
  /** JSON-serialisable request body (for POST/PUT/PATCH). */
  body?: unknown;
}

/** A selectable screen / window capture source for the recorder. */
export interface ScreenSource {
  id: string;
  name: string;
  /** `data:` URL of the source's thumbnail, for the picker grid. */
  thumbnailDataUrl: string;
  /** `"screen"` for a whole display, `"window"` for an app window. */
  kind: "screen" | "window";
}

/**
 * The typed surface exposed on `window.reelforge` by the preload contextBridge.
 * This is the SINGLE source of truth for the bridge shape: the preload asserts
 * its implementation `satisfies` this, and the renderer's global augmentation
 * references it, so the two can never drift.
 */
export interface ReelforgeBridge {
  /** Read the current (non-secret) config. */
  getConfig(): Promise<PublicConfig>;
  /** Persist a validated config patch; returns the updated public config. */
  saveConfig(patch: ConfigPatch): Promise<PublicConfig>;
  /**
   * Perform an authenticated API call against the configured base. Main attaches
   * the stored token, unwraps the `{ status, data, message }` envelope, and
   * throws a plain `Error` (with the backend message) on any non-2xx response.
   */
  request<T>(input: ApiRequestInput): Promise<T>;
  /** Enumerate capturable screens/windows for the recorder picker. */
  getScreenSources(): Promise<ScreenSource[]>;
}
