import { useState } from "react";

import type { ConfigPatch, PublicConfig } from "../../electron/ipc";

interface ConfigFormProps {
  /** Current non-secret config (`{ apiBase, tokenSet }`). */
  config: PublicConfig;
  /** Label for the primary submit button (e.g. "Connect" / "Save"). */
  submitLabel: string;
  /** Called with the updated public config after a successful save. */
  onSaved: (next: PublicConfig) => void;
  /** Optional secondary action (e.g. "Cancel" on the Settings screen). */
  onCancel?: () => void;
}

/**
 * Shared editor for the API base URL and API token, reused by the first-run
 * Connect screen and the Settings screen.
 *
 * SECURITY: the token is write-only from the renderer's perspective — main stores
 * it (encrypted at rest via `safeStorage`) and never returns it, so this form only
 * learns whether one is set and can replace or clear it. The value is passed to
 * main via the validated `saveConfig` bridge and never kept in the renderer bundle.
 */
export function ConfigForm({
  config,
  submitLabel,
  onSaved,
  onCancel,
}: ConfigFormProps) {
  const [apiBase, setApiBase] = useState(config.apiBase);
  const [token, setToken] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const trimmedBase = apiBase.trim();
    if (!trimmedBase) {
      setError("An API base URL is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const patch: ConfigPatch = { apiBase: trimmedBase };
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
    <div className="config-form">
      <label className="field">
        <span className="field-label">API base URL</span>
        <input
          className="input"
          type="url"
          value={apiBase}
          spellCheck={false}
          autoComplete="off"
          placeholder="http://localhost:8080/api/v1"
          onChange={(e) => setApiBase(e.target.value)}
        />
      </label>

      <label className="field">
        <span className="field-label">
          API key{" "}
          {config.tokenSet ? "(a key is set — leave blank to keep it)" : ""}
        </span>
        <input
          className="input"
          type="password"
          value={token}
          spellCheck={false}
          autoComplete="off"
          placeholder={config.tokenSet ? "••••••••" : "Paste your API key"}
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
          <span>Clear the stored key</span>
        </label>
      )}

      {error && <p className="error-text">{error}</p>}

      <div className="panel-actions">
        {onCancel && (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void submit()}
          disabled={busy}
        >
          {busy ? "Saving…" : submitLabel}
        </button>
      </div>
    </div>
  );
}
