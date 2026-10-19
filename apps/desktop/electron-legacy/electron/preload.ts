import { contextBridge, ipcRenderer } from "electron";

import { IpcChannel } from "./ipc";
import type {
  ApiRequestInput,
  ConfigPatch,
  PublicConfig,
  ReelforgeBridge,
  ScreenSource,
} from "./ipc";

/**
 * Preload: the ONLY channel between the sandboxed renderer and the main process.
 *
 * A single, minimal, typed object is exposed on `window.reelforge` via the
 * contextBridge. No `ipcRenderer`, no Node built-ins, and no secrets are exposed
 * — every method is a thin, argument-shaped wrapper over a named IPC channel,
 * and main re-validates all input. The implementation is asserted to
 * `satisfies ReelforgeBridge` so it can never drift from the shared contract.
 */

const bridge = {
  getConfig(): Promise<PublicConfig> {
    return ipcRenderer.invoke(IpcChannel.ConfigGet);
  },

  saveConfig(patch: ConfigPatch): Promise<PublicConfig> {
    // Only forward the two known fields — never leak arbitrary renderer objects.
    const safe: ConfigPatch = {};
    if (typeof patch?.apiBase === "string") safe.apiBase = patch.apiBase;
    if (typeof patch?.token === "string") safe.token = patch.token;
    return ipcRenderer.invoke(IpcChannel.ConfigSave, safe);
  },

  request<T>(input: ApiRequestInput): Promise<T> {
    const safe: ApiRequestInput = {
      method: input?.method,
      path: input?.path,
      body: input?.body,
    };
    return ipcRenderer.invoke(IpcChannel.ApiRequest, safe) as Promise<T>;
  },

  getScreenSources(): Promise<ScreenSource[]> {
    return ipcRenderer.invoke(IpcChannel.ScreenSources);
  },
} satisfies ReelforgeBridge;

contextBridge.exposeInMainWorld("reelforge", bridge);
