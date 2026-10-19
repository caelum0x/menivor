"use client";

import * as React from "react";
import Link from "next/link";
import { Clapperboard, Mic } from "lucide-react";
import type { Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useVoicesCatalog } from "@/components/catalog/use-catalog";
import { EmptyState, ErrorPanel } from "@/components/catalog/states";
import { VoicePreviewButton } from "@/components/catalog/VoicePreviewButton";
import { voiceLabel } from "@/components/catalog/VoicesGallery";

interface VoiceDetailProps {
  voiceId: string;
}

/** Client detail view for a single voice, resolved from GET /voices by id. */
export function VoiceDetail({ voiceId }: VoiceDetailProps) {
  const { status, data, error, reload } = useVoicesCatalog();

  if (status === "loading") {
    return (
      <Card>
        <CardContent className="space-y-4 p-6">
          <Skeleton className="h-7 w-1/2" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load this voice"
        message={error}
        onRetry={reload}
      />
    );
  }

  const voice = (data ?? []).find((v) => v.voice_id === voiceId);
  if (!voice) {
    return (
      <EmptyState
        title="Voice not found"
        message={`No voice matches the id "${voiceId}". It may have been removed.`}
        icon={<Mic className="size-6" aria-hidden />}
        action={
          <Button asChild variant="outline" size="sm">
            <Link href="/catalog/voices">Back to gallery</Link>
          </Button>
        }
      />
    );
  }

  const label = voiceLabel(voice);
  const labels = voice.labels ?? {};
  const labelEntries = Object.entries(labels).filter(
    ([, value]) => typeof value === "string" && value.length > 0,
  );

  return (
    <Card>
      <CardContent className="space-y-6 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Mic className="size-6" aria-hidden />
            </span>
            <div>
              <h2 className="text-2xl font-bold tracking-tight">{label}</h2>
              {voice.category && (
                <p className="text-sm text-muted-foreground">
                  {voice.category}
                </p>
              )}
            </div>
          </div>
          <VoicePreviewButton url={voice.preview_url} label={label} />
        </div>

        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">
              Voice id
            </dt>
            <dd className="font-mono text-sm break-all">{voice.voice_id}</dd>
          </div>
          {labelEntries.map(([key, value]) => (
            <div key={key}>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                {key.replace(/_/g, " ")}
              </dt>
              <dd className="text-sm">{value}</dd>
            </div>
          ))}
        </dl>

        {labelEntries.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {labelEntries.map(([key, value]) => (
              <Badge key={key} variant="outline">
                {value}
              </Badge>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2 pt-1">
          <Button asChild>
            <Link href={`/new?voice=${encodeURIComponent(voice.voice_id)}`}>
              <Clapperboard className="size-4" aria-hidden /> Narrate a reel
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/catalog/voices">Back to gallery</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
