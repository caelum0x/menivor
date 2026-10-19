# ReelForge Desktop

A native desktop client for [ReelForge](../web) — a screen-recording UGC reel
generator. Desktop is the ideal primary client because screen capture is native.

The app **does not reimplement the pipeline**. It records the screen, uploads the
clip to R2 via the backend's presign endpoint, creates a job (`POST /jobs`), polls
it, and shows the result. All heavy lifting (script → TTS → avatar → captions →
compose) runs on the existing ReelForge FastAPI backend.

## Stack

- **Electron** (main process, native screen capture, secure config storage)
- **Vite** + **React 19** + **TypeScript** (renderer)
- All dependencies are permissive-licensed (MIT / Apache-2.0)

## Security model

This app follows Electron's hardening rules by default:

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`
- The renderer talks to main **only** through a typed preload `contextBridge`
  (`window.reelforge`). No raw `ipcRenderer` or Node APIs are exposed.
- Only local/trusted content is loaded (the Vite dev server in dev, the bundled
  `dist/index.html` in production). External navigation and `window.open` are
  denied and routed to the OS browser.
- **No secrets in the renderer bundle.** The API base URL and API token live in
  the main process (`electron/config-store.ts`), with the token encrypted at rest
  via Electron `safeStorage`. Authenticated requests are proxied through main
  (`electron/api-proxy.ts`), which attaches the token — the renderer never sees it.
- Every IPC input is re-validated in the main process.

### Preload contextBridge API (`window.reelforge`)

| Method | Signature | Purpose |
| --- | --- | --- |
| `getConfig` | `() => Promise<PublicConfig>` | Read the non-secret config (`apiBase`, `tokenSet`). |
| `saveConfig` | `(patch: ConfigPatch) => Promise<PublicConfig>` | Persist a validated `{ apiBase?, token? }` patch. |
| `request` | `<T>(input: ApiRequestInput) => Promise<T>` | Authenticated API call, proxied + unwrapped by main. |
| `getScreenSources` | `() => Promise<ScreenSource[]>` | Enumerate capturable screens/windows for the recorder. |

The token is **write-only** across the bridge: `saveConfig` accepts it, but no
method ever returns it.

## Project layout

```
desktop/
├── electron/                 # Main process (Node) — never bundled into the renderer
│   ├── main.ts               #   BrowserWindow + IPC handlers + hardening
│   ├── preload.ts            #   contextBridge — the ONLY renderer↔main surface
│   ├── ipc.ts                #   Shared channel names + payload/bridge types
│   ├── config-store.ts       #   Secure config (apiBase + encrypted token)
│   └── api-proxy.ts          #   Authenticated fetch + envelope unwrap
├── src/                      # Renderer (React)
│   ├── main.tsx              #   React entry
│   ├── App.tsx               #   Shell + view routing + settings
│   ├── global.d.ts           #   window.reelforge typing
│   ├── styles.css            #   Theme (mirrors web/app/globals.css)
│   ├── lib/                  #   api.ts, types.ts, recorder.ts
│   └── views/                #   Record / Generate / Library / Settings
├── index.html
├── vite.config.ts
├── tsconfig.json             # Renderer + shared typecheck (tsc --noEmit)
├── tsconfig.electron.json    # Compiles electron/ → dist-electron/ (CommonJS)
└── electron-builder.yml
```

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Runs the Vite dev server and Electron together (via `concurrently`). |
| `npm run typecheck` | `tsc --noEmit` over the whole project. |
| `npm run build` | Typecheck, build the renderer, compile main, then package with `electron-builder`. |
| `npm start` | Launch the packaged/compiled app (`electron .`). |

## Getting started

```bash
npm install
npm run typecheck    # must pass
npm run dev          # launches the app against the dev server
```

Open **Settings** and set your API base (default
`http://localhost:8080/api/v1`) and API token before generating.

> A full native packaged build (`electron-builder`) is a follow-up; this is the
> scaffold + core (record → upload → create job → poll → result).
