"use client";

import * as React from "react";
import Link from "next/link";
import { Loader2, Mic, RefreshCw, Sparkles } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiToken } from "@/lib/use-api-token";
import {
  listSpeakProviders,
  listVoicesCatalog,
  type CatalogVoice,
  type SpeakProvider,
} from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

function langLabel(lang: string): string {
  if (lang === "tr") return "Turkish";
  if (lang === "en") return "English";
  if (lang === "multi") return "Multi-lingual";
  return lang;
}

function VoiceCard({ voice }: { voice: CatalogVoice }): React.JSX.Element {
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Mic className="h-4 w-4 shrink-0 text-primary" aria-hidden />
            <span className="font-medium">{voice.name}</span>
          </div>
          <div className="flex shrink-0 flex-wrap gap-1">
            <Badge variant="secondary">{langLabel(voice.language)}</Badge>
            {voice.gender && (
              <Badge variant="outline">{voice.gender}</Badge>
            )}
          </div>
        </div>
        {voice.description && (
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {voice.description}
          </p>
        )}
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-muted-foreground">
            {voice.id}
          </span>
          <Button asChild size="sm" variant="outline">
            <Link href={`/new?voice=${encodeURIComponent(voice.id)}`}>
              <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Use voice
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ProviderRow({ p }: { p: SpeakProvider }): React.JSX.Element {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="font-medium capitalize">{p.display_name ?? p.provider}</span>
        {p.license_class && (
          <Badge variant="outline" className="text-xs">
            {p.license_class}
          </Badge>
        )}
      </div>
      <Badge variant={p.available ? "success" : "secondary"}>
        {p.available ? "Available" : "Unavailable"}
      </Badge>
    </div>
  );
}

/**
 * Voices catalog — the TTS voice roster from GET /voices plus the lipsync
 * provider availability from GET /generation/speak/providers. Both are
 * surfaced here so a creator can pick a narrator voice and understand which
 * lipsync engine will animate it, before spending credits on a render.
 */
export function VoicesCatalog(): React.JSX.Element {
  const getApiToken = useApiToken();
  const [voices, setVoices] = React.useState<CatalogVoice[]>([]);
  const [providers, setProviders] = React.useState<SpeakProvider[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      const token = await getApiToken();
      try {
        const [vs, ps] = await Promise.all([
          listVoicesCatalog({ token, signal }),
          listSpeakProviders({ token, signal }).catch(() => ({
            modes: [],
            runtime: "",
            providers: [],
          })),
        ]);
        if (!signal?.aborted) {
          setVoices(vs);
          setProviders(ps.providers);
        }
      } catch (err) {
        if (!signal?.aborted) {
          setError(errText(err, "Failed to load voices."));
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [getApiToken],
  );

  React.useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  const onRefresh = React.useCallback(async () => {
    setRefreshing(true);
    setLoading(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  return (
    <div className="space-y-8">
      {/* Lipsync providers */}
      {providers.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Lipsync providers
          </h2>
          <div className="space-y-2">
            {providers.map((p) => (
              <ProviderRow key={p.provider} p={p} />
            ))}
          </div>
        </section>
      )}

      {/* Voice catalog */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Narrator voices
            {voices.length > 0 && (
              <span className="ml-1 font-normal normal-case">
                ({voices.length})
              </span>
            )}
          </h2>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => void onRefresh()}
            disabled={refreshing || loading}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              aria-hidden
            />
            Refresh
          </Button>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading
            voices…
          </p>
        ) : voices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <Mic className="mx-auto mb-2 h-8 w-8 text-muted-foreground" aria-hidden />
            <p className="text-sm text-muted-foreground">
              No voices available. Check your API configuration.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {voices.map((v) => (
              <VoiceCard key={v.id} voice={v} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
