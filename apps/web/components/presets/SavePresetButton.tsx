"use client";

import * as React from "react";
import { AlertCircle, Check, Loader2, Save, X } from "lucide-react";
import { ApiError, createPreset } from "@/lib/api";
import type { Preset } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApiToken } from "@/lib/use-api-token";
import {
  isConfigEmpty,
  toConfigRecord,
  type PresetConfig,
} from "@/components/presets/preset-config";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface SavePresetButtonProps {
  /** The settings to persist when the user names + saves the kit. */
  config: Readonly<PresetConfig>;
  /** Optional label for the trigger button. */
  label?: string;
  /** Called with the created preset after a successful save. */
  onSaved?: (preset: Preset) => void;
  className?: string;
}

type Phase = "idle" | "editing" | "saved";

/**
 * A compact, reusable "Save these settings as a preset" affordance. Clicking it
 * reveals an inline name field; saving POSTs `/me/presets` with the supplied
 * config and briefly confirms. Self-contained (owns its token + request), so it
 * can be dropped into the wizard review step or anywhere a config is in hand.
 */
export function SavePresetButton({
  config,
  label = "Save these settings as a preset",
  onSaved,
  className,
}: SavePresetButtonProps) {
  const getApiToken = useApiToken();
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [name, setName] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const empty = isConfigEmpty(config);
  const trimmedName = name.trim();

  const reset = React.useCallback(() => {
    setPhase("idle");
    setName("");
    setError(null);
  }, []);

  const handleSave = React.useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!trimmedName) return;
      setSaving(true);
      setError(null);
      try {
        const token = await getApiToken();
        const created = await createPreset(
          { name: trimmedName, config: toConfigRecord(config) },
          { token },
        );
        onSaved?.(created);
        setPhase("saved");
        setName("");
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Couldn't save this preset. Please try again.");
        setError(message);
      } finally {
        setSaving(false);
      }
    },
    [config, getApiToken, onSaved, trimmedName],
  );

  if (phase === "saved") {
    return (
      <p
        className={className}
        role="status"
      >
        <span className="inline-flex items-center gap-1.5 text-sm text-success">
          <Check className="size-4" aria-hidden /> Saved as a preset.
        </span>{" "}
        <button
          type="button"
          className="text-sm text-primary underline-offset-4 hover:underline"
          onClick={reset}
        >
          Save another
        </button>
      </p>
    );
  }

  if (phase === "idle") {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={className}
        disabled={empty}
        title={
          empty ? "Choose some settings first" : "Save these settings as a preset"
        }
        onClick={() => setPhase("editing")}
      >
        <Save aria-hidden /> {label}
      </Button>
    );
  }

  return (
    <form onSubmit={handleSave} className={className}>
      <div className="flex items-center gap-2">
        <Input
          aria-label="Preset name"
          placeholder="Name this preset"
          value={name}
          maxLength={80}
          autoFocus
          disabled={saving}
          onChange={(e) => setName(e.target.value)}
          className="h-8"
        />
        <Button type="submit" size="sm" disabled={!trimmedName || saving}>
          {saving ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <Save aria-hidden />
          )}
          Save
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Cancel"
          disabled={saving}
          onClick={reset}
        >
          <X aria-hidden />
        </Button>
      </div>
      {error && (
        <p
          role="alert"
          className="mt-2 flex items-center gap-2 text-sm text-destructive"
        >
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </form>
  );
}
