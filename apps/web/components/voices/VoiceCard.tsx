"use client";

import * as React from "react";
import { Loader2, Mic, Trash2 } from "lucide-react";
import type { UserVoice } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  formatCreatedAt,
  isVoiceReady,
} from "@/components/voices/voice-utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface VoiceCardProps {
  voice: UserVoice;
  /** Delete by row id; resolves once the server confirms removal. */
  onDelete: (id: string) => Promise<void>;
}

/** A single cloned voice with its status and a confirm-guarded delete. */
export function VoiceCard({ voice, onDelete }: VoiceCardProps) {
  const [confirming, setConfirming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const ready = isVoiceReady(voice);
  const created = formatCreatedAt(voice.created_at);

  const handleDelete = React.useCallback(async () => {
    setDeleting(true);
    setError(null);
    try {
      await onDelete(voice.id);
      // On success the parent removes this card; no further state needed.
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not delete this voice. Please try again.");
      setError(message);
      setDeleting(false);
      setConfirming(false);
    }
  }, [onDelete, voice.id]);

  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Mic className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{voice.name}</p>
              {created && (
                <p className="text-xs text-muted-foreground">Added {created}</p>
              )}
            </div>
          </div>
          <Badge variant={ready ? "success" : "secondary"}>
            {ready ? "Ready" : voice.status || "Pending"}
          </Badge>
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {confirming ? (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? (
                <>
                  <Loader2 className="animate-spin" /> Deleting…
                </>
              ) : (
                <>
                  <Trash2 /> Confirm delete
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setConfirming(false)}
              disabled={deleting}
            >
              Cancel
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setConfirming(true)}
            className="text-destructive hover:text-destructive"
          >
            <Trash2 /> Delete
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
