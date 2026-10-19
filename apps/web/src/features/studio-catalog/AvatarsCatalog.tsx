"use client";

import * as React from "react";
import Link from "next/link";
import { Film, Loader2, RefreshCw, Sparkles, User, Users } from "lucide-react";

import { ApiError } from "@/src/shared/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useApiToken } from "@/lib/use-api-token";
import { listCharacters, type Character } from "@/src/features/characters/api";
import { listAvatarsCatalog, type CatalogAvatar } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

function errText(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

function AvatarCard({ avatar }: { avatar: CatalogAvatar }): React.JSX.Element {
  const label = avatar.display_name || avatar.provider_avatar_id || avatar.id;
  const avatarId = avatar.avatar_id || avatar.provider_avatar_id || avatar.id;
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        {avatar.thumbnail_url ? (
          <img
            src={avatar.thumbnail_url}
            alt={label}
            className="aspect-square w-full rounded-md object-cover"
          />
        ) : (
          <div className="flex aspect-square w-full items-center justify-center rounded-md bg-muted">
            <User className="h-8 w-8 text-muted-foreground" aria-hidden />
          </div>
        )}
        <div className="flex items-start justify-between gap-2">
          <span className="font-medium leading-tight">{label}</span>
          <Badge variant="outline" className="shrink-0 text-xs">
            {avatar.source}
          </Badge>
        </div>
        {avatar.voice_name && (
          <p className="text-xs text-muted-foreground">
            Voice: {avatar.voice_name}
          </p>
        )}
        <Button asChild size="sm" variant="outline" className="w-full">
          <Link href={`/new?avatar=${encodeURIComponent(avatarId)}`}>
            <Sparkles className="mr-1 h-4 w-4" aria-hidden /> Use avatar
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function CharacterCard({
  character,
}: {
  character: Character;
}): React.JSX.Element {
  return (
    <Card>
      <CardContent className="space-y-2 py-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Film className="h-4 w-4 shrink-0 text-primary" aria-hidden />
            <span className="font-medium">{character.name}</span>
          </div>
          {character.identity_key && (
            <Badge variant="secondary" className="shrink-0 font-mono text-xs">
              id {character.identity_key.slice(0, 8)}
            </Badge>
          )}
        </div>
        {character.style && (
          <Badge variant="outline" className="text-xs">
            {character.style}
          </Badge>
        )}
        {character.descriptors.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {character.descriptors.map((d) => (
              <Badge key={d} variant="secondary" className="text-xs">
                {d}
              </Badge>
            ))}
          </div>
        )}
        <Button asChild size="sm" variant="outline" className="w-full">
          <Link href={`/film?character_id=${encodeURIComponent(character.id)}`}>
            <Film className="mr-1 h-4 w-4" aria-hidden /> Use in film
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

/**
 * Avatars and characters catalog — merges the provider avatar roster
 * (GET /avatars) with the caller's identity-locked characters (GET /characters).
 * Avatars link into the quick-create compose flow; characters link to the film
 * planner. Both use real API calls; no fabricated data.
 */
export function AvatarsCatalog(): React.JSX.Element {
  const getApiToken = useApiToken();
  const [avatars, setAvatars] = React.useState<CatalogAvatar[]>([]);
  const [characters, setCharacters] = React.useState<Character[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(
    async (signal?: AbortSignal) => {
      setError("");
      const token = await getApiToken();
      try {
        const [avs, chars] = await Promise.all([
          listAvatarsCatalog({ token, signal }),
          listCharacters({ token, signal }).then((r) => r.characters),
        ]);
        if (!signal?.aborted) {
          setAvatars(avs);
          setCharacters(chars);
        }
      } catch (err) {
        if (!signal?.aborted) {
          setError(errText(err, "Failed to load avatars."));
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

  const refreshBtn = (
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
  );

  return (
    <div className="space-y-10">
      {error && <p className="text-sm text-destructive">{error}</p>}

      {/* Provider avatars */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <User className="h-5 w-5 text-primary" aria-hidden />
            <h2 className="font-semibold">
              Avatars
              {avatars.length > 0 && (
                <span className="ml-1 font-normal text-muted-foreground">
                  ({avatars.length})
                </span>
              )}
            </h2>
          </div>
          {refreshBtn}
        </div>
        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : avatars.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <User
              className="mx-auto mb-2 h-8 w-8 text-muted-foreground"
              aria-hidden
            />
            <p className="text-sm text-muted-foreground">
              No avatars available. Check your HeyGen configuration.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {avatars.map((a) => (
              <AvatarCard key={a.id} avatar={a} />
            ))}
          </div>
        )}
      </section>

      {/* Identity-locked characters */}
      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" aria-hidden />
            <h2 className="font-semibold">
              Characters
              {characters.length > 0 && (
                <span className="ml-1 font-normal text-muted-foreground">
                  ({characters.length})
                </span>
              )}
            </h2>
          </div>
          <Button asChild size="sm" variant="outline">
            <Link href="/characters">Manage characters</Link>
          </Button>
        </div>
        {loading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </p>
        ) : characters.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-8 text-center">
            <Users
              className="mx-auto mb-2 h-8 w-8 text-muted-foreground"
              aria-hidden
            />
            <p className="mb-4 text-sm text-muted-foreground">
              No saved characters yet. Create one to lock an identity across
              shots.
            </p>
            <Button asChild size="sm">
              <Link href="/characters">
                <Users className="mr-1 h-4 w-4" aria-hidden /> Create character
              </Link>
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {characters.map((c) => (
              <CharacterCard key={c.id} character={c} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
