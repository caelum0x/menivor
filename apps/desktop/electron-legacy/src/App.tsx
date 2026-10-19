import { useCallback, useEffect, useState } from "react";

import type { PublicConfig } from "../electron/ipc";
import {
  ConnectScreen,
  CreateScreen,
  LibraryScreen,
  SettingsScreen,
} from "./screens";
import "./screens/screens.css";

type Tab = "create" | "library" | "settings";

const NAV: ReadonlyArray<{ key: Tab; label: string }> = [
  { key: "create", label: "Create" },
  { key: "library", label: "Library" },
  { key: "settings", label: "Settings" },
];

/**
 * App shell + router.
 *
 * Boot reads the non-secret config from main. Until an API key is stored the app
 * is gated behind the first-run {@link ConnectScreen}; once connected it renders
 * the main shell (top nav + the active screen). The API base + key live ONLY in
 * main (token encrypted at rest) and reach the renderer only as the non-secret
 * `{ apiBase, tokenSet }` — no secret ever enters this bundle.
 */
export function App() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [tab, setTab] = useState<Tab>("create");

  useEffect(() => {
    void (async () => setConfig(await window.reelforge.getConfig()))();
  }, []);

  const handleConnected = useCallback((next: PublicConfig) => {
    setConfig(next);
    setTab("create");
  }, []);

  // Boot: waiting for the first config read.
  if (config === null) {
    return (
      <div className="connect">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  // First-run gate: no API key stored yet.
  if (!config.tokenSet) {
    return <ConnectScreen config={config} onConnected={handleConnected} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden />
          <span className="brand-name">ReelForge</span>
          <span className="brand-tag">Desktop</span>
        </div>

        <nav className="nav" aria-label="Primary">
          {NAV.map((item) => (
            <button
              key={item.key}
              type="button"
              className={
                item.key === tab ? "nav-item nav-item--active" : "nav-item"
              }
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="topbar-right">
          <span className={config.tokenSet ? "pill pill--ok" : "pill pill--warn"}>
            {config.tokenSet ? "Connected" : "No key"}
          </span>
        </div>
      </header>

      <main className="content">
        {tab === "create" && (
          <CreateScreen onViewLibrary={() => setTab("library")} />
        )}
        {tab === "library" && (
          <LibraryScreen onCreate={() => setTab("create")} />
        )}
        {tab === "settings" && (
          <SettingsScreen config={config} onSaved={setConfig} />
        )}
      </main>
    </div>
  );
}
