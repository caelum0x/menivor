import { app, BrowserWindow, desktopCapturer, ipcMain, shell } from "electron";
import { join, resolve, sep } from "node:path";

import { apiRequest } from "./api-proxy";
import { ConfigStore } from "./config-store";
import { IpcChannel } from "./ipc";
import type { ConfigPatch, ScreenSource } from "./ipc";

/**
 * ReelForge Desktop — Electron main process.
 *
 * Security posture (hard rules):
 *  - `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`
 *  - the renderer reaches main ONLY through the typed preload contextBridge
 *  - only local content is loaded (the Vite dev server in dev, the bundled
 *    `dist/index.html` in production); external navigation + new windows are
 *    denied and pushed to the OS browser instead
 *  - the API token lives only here (see {@link ConfigStore}); it is attached to
 *    outgoing requests in {@link apiRequest} and never handed to the renderer.
 */

const DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL ?? "http://localhost:5173";

const store = new ConfigStore();

/**
 * Decide whether an in-app navigation is permitted. Uses exact origin equality
 * (not a prefix match) so a host that merely starts with the dev URL — e.g.
 * `http://localhost:5173.evil.com` — is rejected. In packaged builds only
 * `file://` targets that resolve to inside the bundled `dist` dir are allowed.
 */
function isAllowedNavigation(target: string): boolean {
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    return false;
  }

  if (app.isPackaged) {
    if (url.protocol !== "file:") return false;
    const distDir = resolve(join(__dirname, "..", "dist"));
    const targetPath = resolve(decodeURIComponent(url.pathname));
    return targetPath === distDir || targetPath.startsWith(distDir + sep);
  }

  try {
    return url.origin === new URL(DEV_SERVER_URL).origin;
  } catch {
    return false;
  }
}

function registerIpcHandlers(): void {
  ipcMain.handle(IpcChannel.ConfigGet, () => store.getPublic());

  ipcMain.handle(IpcChannel.ConfigSave, (_event, patch: ConfigPatch) => {
    // Defensive: coerce/validate before touching the store.
    const safe: ConfigPatch = {};
    if (patch && typeof patch === "object") {
      if (typeof patch.apiBase === "string") safe.apiBase = patch.apiBase;
      if (typeof patch.token === "string") safe.token = patch.token;
    }
    return store.save(safe);
  });

  ipcMain.handle(IpcChannel.ApiRequest, (_event, input: unknown) =>
    apiRequest<unknown>(store, input),
  );

  ipcMain.handle(IpcChannel.ScreenSources, async (): Promise<ScreenSource[]> => {
    const sources = await desktopCapturer.getSources({
      types: ["screen", "window"],
      thumbnailSize: { width: 320, height: 180 },
    });
    return sources.map((s) => ({
      id: s.id,
      name: s.name,
      thumbnailDataUrl: s.thumbnail.toDataURL(),
      kind: s.id.startsWith("screen:") ? "screen" : "window",
    }));
  });
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 940,
    minHeight: 640,
    backgroundColor: "#0a0a0f",
    show: false,
    title: "ReelForge Desktop",
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  win.once("ready-to-show", () => win.show());

  // Harden navigation: keep the window pinned to our own content and route any
  // outbound link to the OS browser instead of loading it in-app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (!isAllowedNavigation(url)) event.preventDefault();
  });

  if (app.isPackaged) {
    void win.loadFile(join(__dirname, "..", "dist", "index.html"));
  } else {
    void win.loadURL(DEV_SERVER_URL);
    // Retry once if the dev server was not yet listening when Electron launched.
    win.webContents.on("did-fail-load", () => {
      setTimeout(() => void win.loadURL(DEV_SERVER_URL), 800);
    });
  }
}

app.whenReady().then(() => {
  registerIpcHandlers();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
