"use client";

import * as React from "react";
import { AlertCircle, Loader2, Trash2, Users } from "lucide-react";
import { ApiError } from "@/lib/api";
import type { Preset } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  coercePresetConfig,
  summarizePresetConfig,
  type PresetLabelMaps,
} from "@/components/presets/preset-config";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface PresetCardProps {
  preset: Preset;
  labelMaps: Readonly<PresetLabelMaps>;
  /** Deletes the preset; rejects on failure so the card can show the error. */
  onDelete: (id: string) => Promise<void>;
}

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * A single saved brand kit: its name, a summary of the settings it captures,
 * and a two-step (confirm) delete. Delete errors are shown inline and leave the
 * card in place so the user can retry.
 */
export function PresetCard({ preset, labelMaps, onDelete }: PresetCardProps) {
  const [confirming, setConfirming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const config = React.useMemo(
    () => coercePresetConfig(preset.config),
    [preset.config],
  );
  const items = React.useMemo(
    () => summarizePresetConfig(config, labelMaps),
    [config, labelMaps],
  );
  const createdAt = formatDate(preset.created_at);

  const handleDelete = React.useCallback(async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete(preset.id);
      // On success the parent removes this card; no local state update needed.
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Couldn't delete this preset. Please try again.");
      setError(message);
      setDeleting(false);
      setConfirming(false);
    }
  }, [onDelete, preset.id]);

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CardTitle className="truncate">{preset.name}</CardTitle>
            {preset.shared && (
              <Badge variant="default" className="shrink-0">
                <Users className="size-3" aria-hidden />
                Shared
              </Badge>
            )}
          </div>
          {createdAt && (
            <p className="mt-1 text-xs text-muted-foreground">
              Saved {createdAt}
            </p>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        {items.length > 0 ? (
          <dl className="grid gap-2">
            {items.map((item) => (
              <div
                key={item.key}
                className="flex items-center justify-between gap-3"
              >
                <dt className="text-sm text-muted-foreground">{item.label}</dt>
                <dd className="min-w-0">
                  <Badge variant="secondary" className="max-w-[12rem] truncate">
                    {item.value}
                  </Badge>
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            No settings captured in this kit.
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

        <div className="mt-auto flex items-center justify-end gap-2 pt-2">
          {confirming ? (
            <>
              <span className="mr-auto text-sm text-muted-foreground">
                Delete this kit?
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setConfirming(false)}
                disabled={deleting}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={() => void handleDelete()}
                disabled={deleting}
              >
                {deleting ? (
                  <>
                    <Loader2 className="animate-spin" aria-hidden /> Deleting…
                  </>
                ) : (
                  "Confirm delete"
                )}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setConfirming(true)}
            >
              <Trash2 aria-hidden /> Delete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
