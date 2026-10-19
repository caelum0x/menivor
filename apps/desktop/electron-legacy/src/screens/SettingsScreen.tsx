import type { PublicConfig } from "../../electron/ipc";
import { ConfigForm } from "./ConfigForm";

interface SettingsScreenProps {
  /** Current non-secret config. */
  config: PublicConfig;
  /** Called with the updated public config after a successful save. */
  onSaved: (next: PublicConfig) => void;
}

/**
 * Settings screen: change the API base URL and API key after first-run. Mirrors
 * the Connect screen's form but lives inside the main app shell. The token stays
 * write-only (stored in main, never returned) — see {@link ConfigForm}.
 */
export function SettingsScreen({ config, onSaved }: SettingsScreenProps) {
  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Settings</h1>
        <p className="view-sub">
          Connection details for your ReelForge backend.
        </p>
      </div>

      <div className="card panel">
        <div className="settings-status">
          <span className="field-label">Status</span>
          <span className={config.tokenSet ? "pill pill--ok" : "pill pill--warn"}>
            {config.tokenSet ? "Connected" : "No API key set"}
          </span>
        </div>

        <ConfigForm config={config} submitLabel="Save" onSaved={onSaved} />
      </div>
    </section>
  );
}
