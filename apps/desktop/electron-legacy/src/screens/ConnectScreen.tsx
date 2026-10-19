import type { PublicConfig } from "../../electron/ipc";
import { ConfigForm } from "./ConfigForm";

interface ConnectScreenProps {
  /** Current non-secret config (prefilled into the form). */
  config: PublicConfig;
  /** Called once a key has been stored and the app is ready to use. */
  onConnected: (next: PublicConfig) => void;
}

/**
 * First-run / connect screen. Shown whenever no API key is stored, this is the
 * gate into the app: point the desktop client at the ReelForge backend and paste
 * an API key. The key is handed to main (encrypted at rest) and never held in the
 * renderer — see {@link ConfigForm}.
 */
export function ConnectScreen({ config, onConnected }: ConnectScreenProps) {
  return (
    <div className="connect">
      <div className="connect-card card">
        <div className="connect-head">
          <span className="brand-mark brand-mark--lg" aria-hidden />
          <h1 className="connect-title">Connect ReelForge</h1>
          <p className="connect-sub">
            Record your screen and turn it into a UGC reel. First, point the app at
            your ReelForge backend and add your API key to get started.
          </p>
        </div>

        <ConfigForm
          config={config}
          submitLabel="Connect"
          onSaved={onConnected}
        />

        <p className="connect-note muted">
          Your key is stored securely on this device and is never bundled into the
          app or sent anywhere except your configured backend.
        </p>
      </div>
    </div>
  );
}
