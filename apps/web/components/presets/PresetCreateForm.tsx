"use client";

import * as React from "react";
import { AlertCircle, Loader2, Save, Users } from "lucide-react";
import { ApiError } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  isConfigEmpty,
  type PresetConfig,
} from "@/components/presets/preset-config";
import { PresetConfigFields } from "@/components/presets/PresetConfigFields";
import type {
  CatalogsStatus,
  PresetCatalogs,
} from "@/components/presets/use-catalogs";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface PresetCreateFormProps {
  /**
   * Persists the preset. Rejects with an ApiError/Error on failure.
   * `workspaceId` (when set) SHARES the kit to that workspace.
   */
  onCreate: (
    name: string,
    config: Readonly<PresetConfig>,
    workspaceId?: string | null,
  ) => Promise<unknown>;
  /** Catalog options (loaded by the parent so they're fetched once). */
  catalogs: Readonly<PresetCatalogs>;
  catalogStatus: CatalogsStatus;
  catalogError: string;
  /** The caller's workspaces, for the optional "Share to team" picker. */
  workspaces: readonly Workspace[];
  /** True while the workspace list is still loading. */
  workspacesLoading: boolean;
}

/** Sentinel value for the "keep private" (unshared) option. */
const PRIVATE = "";

const EMPTY_CONFIG: PresetConfig = {};

/**
 * Form for creating a new brand kit: a required name plus the optional config
 * fields. On success it resets to a blank form so several kits can be added in
 * a row. Loading + error states are surfaced inline; the config catalogs load
 * independently and never block naming a kit.
 */
export function PresetCreateForm({
  onCreate,
  catalogs,
  catalogStatus,
  catalogError,
  workspaces,
  workspacesLoading,
}: PresetCreateFormProps) {
  const [name, setName] = React.useState("");
  const [config, setConfig] = React.useState<PresetConfig>(EMPTY_CONFIG);
  const [shareWorkspaceId, setShareWorkspaceId] =
    React.useState<string>(PRIVATE);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const trimmedName = name.trim();
  const canSubmit = trimmedName.length > 0 && !submitting;

  // Reset the share target if the chosen workspace disappears from the list.
  React.useEffect(() => {
    if (shareWorkspaceId === PRIVATE) return;
    if (!workspaces.some((w) => w.id === shareWorkspaceId)) {
      setShareWorkspaceId(PRIVATE);
    }
  }, [workspaces, shareWorkspaceId]);

  const patchConfig = React.useCallback(
    (patch: Readonly<Partial<PresetConfig>>) => {
      setConfig((prev) => ({ ...prev, ...patch }));
    },
    [],
  );

  const handleSubmit = React.useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!trimmedName) return;
      setSubmitting(true);
      setError(null);
      try {
        await onCreate(trimmedName, config, shareWorkspaceId || null);
        setName("");
        setConfig(EMPTY_CONFIG);
        setShareWorkspaceId(PRIVATE);
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Couldn't save this preset. Please try again.");
        setError(message);
      } finally {
        setSubmitting(false);
      }
    },
    [config, onCreate, shareWorkspaceId, trimmedName],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>New brand kit</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid gap-5">
          <div className="grid gap-1.5">
            <Label htmlFor="preset-name">Name</Label>
            <Input
              id="preset-name"
              placeholder="e.g. TikTok — bold violet"
              value={name}
              maxLength={80}
              disabled={submitting}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="preset-share" className="flex items-center gap-2">
              <Users className="size-4 text-primary" aria-hidden />
              Share to team
            </Label>
            <Select
              id="preset-share"
              value={shareWorkspaceId}
              disabled={submitting || workspacesLoading}
              onChange={(e) => setShareWorkspaceId(e.target.value)}
            >
              <option value={PRIVATE}>Private (only you)</option>
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              {shareWorkspaceId
                ? "Every member of this workspace will see this kit."
                : "Keep this kit private, or share it with a workspace."}
            </p>
          </div>

          {catalogStatus === "loading" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : (
            <PresetConfigFields
              value={config}
              onChange={patchConfig}
              catalogs={catalogs}
              disabled={submitting}
            />
          )}

          {catalogStatus === "error" && (
            <p className="text-xs text-muted-foreground">
              Some options couldn&apos;t load ({catalogError}); you can still
              name and save this kit.
            </p>
          )}

          {isConfigEmpty(config) && (
            <p className="text-xs text-muted-foreground">
              Tip: pick at least one setting so this kit pre-fills your next reel.
            </p>
          )}

          {error && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {error}
            </p>
          )}

          <div className="flex justify-end">
            <Button type="submit" disabled={!canSubmit}>
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" aria-hidden /> Saving…
                </>
              ) : (
                <>
                  <Save aria-hidden /> Save brand kit
                </>
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
