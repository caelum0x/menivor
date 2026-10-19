"use client";

import * as React from "react";

import { ErrorText, useRequestOptions } from "@/src/features/ad-studio/shared";
import { readableApiError } from "@/src/shared/launch-gate";
import { getApprovalSettings, updateApprovalSettings, type ApprovalFeedSettings, type AutoSource } from "./api";

const HELP: Record<AutoSource, string> = {
  capture_publish: "Each finished capture becomes a pending reel-ad suggestion. Approving it spends credits.",
  catalog_import: "Each newly imported store product becomes a pending Ad Studio suggestion.",
};

/**
 * Opt-in sources for the approvals feed. Off by default: captures and store
 * imports only add suggestions here when the owner turns them on.
 */
export function AutoSourcesSettings({ onChanged }: { onChanged: () => void }) {
  const requestOptions = useRequestOptions();
  const [settings, setSettings] = React.useState<ApprovalFeedSettings | null>(null);
  const [saving, setSaving] = React.useState<AutoSource | "">("");
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const next = await getApprovalSettings(await requestOptions());
        if (!cancelled) setSettings(next);
      } catch (err) {
        if (!cancelled) setError(readableApiError(err, "Couldn't update this setting. Try again."));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [requestOptions]);

  const toggle = async (source: AutoSource, on: boolean) => {
    setSaving(source);
    setError("");
    try {
      setSettings(await updateApprovalSettings({ [source]: on }, await requestOptions()));
      onChanged();
    } catch (err) {
      setError(readableApiError(err, "Couldn't update this setting. Try again."));
    } finally {
      setSaving("");
    }
  };

  if (!settings && !error) return null;

  return (
    <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer font-medium">Automatic suggestions</summary>
      <p className="mt-2 text-xs text-muted-foreground">
        Off unless you turn them on. Turning one off removes its pending suggestions; nothing already approved changes.
      </p>
      {settings ? (
        <ul className="mt-2 space-y-2">
          {(Object.keys(settings.auto_sources) as AutoSource[]).map((source) => (
            <li key={source}>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={settings.auto_sources[source]}
                  disabled={saving !== ""}
                  onChange={(event) => void toggle(source, event.target.checked)}
                />
                <span>
                  <span className="block">{settings.labels[source] ?? source}</span>
                  <span className="block text-xs text-muted-foreground">{HELP[source]}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <ErrorText message={error} /> : null}
    </details>
  );
}
