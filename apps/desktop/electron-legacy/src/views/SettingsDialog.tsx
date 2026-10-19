import { useState } from "react";

import type { ConfigPatch, PublicConfig } from "../../electron/ipc";

interface SettingsDialogProps {
  config: PublicConfig;
  onClose: () => void;
  onSaved: (next: PublicConfig) => void;
}

/**
 * Settings dialog for the API base URL and the API token. The token is
 * write-only from the renderer's perspective: main stores it (encrypted at rest)
 * and never returns it, so this form only reports whether one is set and lets the
 * user replace or clear it.
 */
export function SettingsDialog({ config, onClose, onSaved }: SettingsDialogProps) {
  const [apiBase, setApiBase] = useState(config.apiBase);
  const [token, setToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const patch: ConfigPatch = { apiBase };
      if (clearToken) patch.token = "";
      else if (token.trim()) patch.token = token.trim();
      const next = await window.reelforge.saveConfig(patch);
      onSaved(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Settings">
      <div className="modal card">
        <h2 className="modal-title">Settings</h2>

        <label className="field">
          <span className="field-label">API base URL</span>
          <input
            className="input"
            type="url"
            value={apiBase}
            spellCheck={false}
            placeholder="http://localhost:8080/api/v1"
            onChange={(e) => setApiBase(e.target.value)}
          />
        </label>

        <label className="field">
          <span className="field-label">
            API token {config.tokenSet ? "(a token is set — leave blank to keep it)" : ""}
          </span>
          <input
            className="input"
            type="password"
            value={token}
            spellCheck={false}
            autoComplete="off"
            placeholder={config.tokenSet ? "••••••••" : "Paste your token"}
            disabled={clearToken}
            onChange={(e) => setToken(e.target.value)}
          />
        </label>

        {config.tokenSet && (
          <label className="checkbox">
            <input
              type="checkbox"
              checked={clearToken}
              onChange={(e) => setClearToken(e.target.checked)}
            />
            <span>Clear the stored token</span>
          </label>
        )}

        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn--primary" onClick={submit} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
