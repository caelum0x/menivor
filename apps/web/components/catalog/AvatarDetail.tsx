"use client";

import * as React from "react";
import Link from "next/link";
import { Clapperboard, User } from "lucide-react";
import type { Avatar } from "@/lib/types";
import { isCustomAvatar } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { avatarLabel } from "@/components/avatars/avatar-utils";
import { useAvatarsCatalog } from "@/components/catalog/use-catalog";
import { EmptyState, ErrorPanel } from "@/components/catalog/states";

interface AvatarDetailProps {
  avatarId: string;
}

/** Metadata fields rendered as a definition list, skipping internal/empty ones. */
const HIDDEN_KEYS = new Set<string>([
  "avatar_id",
  "name",
  "display_name",
  "thumbnail_url",
  "source",
  "id",
]);

function scalarEntries(avatar: Avatar): ReadonlyArray<[string, string]> {
  return Object.entries(avatar)
    .filter(([key, value]) => {
      if (HIDDEN_KEYS.has(key)) return false;
      return (
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
      );
    })
    .map(([key, value]) => [key, String(value)] as [string, string]);
}

/** Client detail view for a single avatar, resolved from GET /avatars by id. */
export function AvatarDetail({ avatarId }: AvatarDetailProps) {
  const { status, data, error, reload } = useAvatarsCatalog();

  if (status === "loading") {
    return (
      <Card>
        <CardContent className="flex flex-col gap-6 p-6 sm:flex-row">
          <Skeleton className="aspect-[4/5] w-full max-w-xs rounded-md" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-7 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load this avatar"
        message={error}
        onRetry={reload}
      />
    );
  }

  const avatar = (data ?? []).find((a) => a.avatar_id === avatarId);
  if (!avatar) {
    return (
      <EmptyState
        title="Avatar not found"
        message={`No avatar matches the id "${avatarId}". It may have been removed.`}
        icon={<User className="size-6" aria-hidden />}
        action={
          <Button asChild variant="outline" size="sm">
            <Link href="/catalog/avatars">Back to gallery</Link>
          </Button>
        }
      />
    );
  }

  const label = avatarLabel(avatar);
  const yours = isCustomAvatar(avatar);
  const fields = scalarEntries(avatar);

  return (
    <Card>
      <CardContent className="flex flex-col gap-6 p-6 sm:flex-row">
        <div className="w-full max-w-xs shrink-0">
          <div className="relative aspect-[4/5] overflow-hidden rounded-md bg-secondary">
            {avatar.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatar.thumbnail_url}
                alt={label}
                className="size-full object-cover"
              />
            ) : (
              <span className="flex size-full items-center justify-center text-muted-foreground">
                <User className="size-12" aria-hidden />
              </span>
            )}
          </div>
        </div>

        <div className="flex-1 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-bold tracking-tight">{label}</h2>
            {yours && <Badge variant="secondary">Yours</Badge>}
          </div>

          <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                Avatar id
              </dt>
              <dd className="font-mono text-sm">{avatar.avatar_id}</dd>
            </div>
            {fields.map(([key, value]) => (
              <div key={key}>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </dt>
                <dd className="break-words text-sm">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="flex flex-wrap gap-2 pt-2">
            <Button asChild>
              <Link
                href={`/new?avatar=${encodeURIComponent(avatar.avatar_id)}`}
              >
                <Clapperboard className="size-4" aria-hidden /> Use as presenter
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/catalog/avatars">Back to gallery</Link>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
