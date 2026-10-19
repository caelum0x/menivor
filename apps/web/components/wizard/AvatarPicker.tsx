"use client";

import * as React from "react";
import Link from "next/link";
import { AlertCircle, Check, ImagePlus, RefreshCw, User } from "lucide-react";
import type { Avatar } from "@/lib/types";
import { isCustomAvatar } from "@/lib/types";
import { ApiError, listAvatars } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useApiToken } from "@/lib/use-api-token";
import { avatarLabel } from "@/components/avatars/avatar-utils";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface AvatarPickerProps {
  value: string | null;
  onSelect: (avatarId: string) => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; avatars: readonly Avatar[] };

/** Header link to the custom-avatar builder, shown above the picker grid. */
function CreateFromPhotoLink() {
  return (
    <div className="mb-3 flex items-center justify-end">
      <Link
        href="/avatars"
        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        <ImagePlus className="size-3.5" aria-hidden /> Create from a photo
      </Link>
    </div>
  );
}

/**
 * Grid of talking-head avatars from `GET /avatars`. Handles loading, error,
 * and empty states and reports the chosen `avatar_id` upward.
 */
export function AvatarPicker({ value, onSelect }: AvatarPickerProps) {
  const getApiToken = useApiToken();
  const [state, setState] = React.useState<LoadState>({ status: "loading" });

  const load = React.useCallback(async () => {
    setState({ status: "loading" });
    try {
      const token = await getApiToken();
      const avatars = await listAvatars({ token });
      setState({ status: "ready", avatars });
    } catch (err) {
      const message =
        friendlyErrorMessage(err, "Could not load avatars. Please try again.");
      setState({ status: "error", message });
    }
  }, [getApiToken]);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (state.status === "loading") {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="aspect-[3/4] w-full" />
        ))}
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-8 text-center">
        <AlertCircle className="size-6 text-destructive" aria-hidden />
        <p className="text-sm text-destructive">{state.message}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw /> Retry
        </Button>
      </div>
    );
  }

  const activeAvatars = state.avatars.filter((a) => a.is_active !== false);

  if (activeAvatars.length === 0) {
    return (
      <div>
        <CreateFromPhotoLink />
        <div className="rounded-lg border border-border bg-secondary/20 p-8 text-center text-sm text-muted-foreground">
          No avatars are available yet. Create your own from a photo to get
          started.
        </div>
      </div>
    );
  }

  return (
    <div>
      <CreateFromPhotoLink />
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {activeAvatars.map((avatar) => {
          const selected = avatar.avatar_id === value;
          const label = avatarLabel(avatar);
          const custom = isCustomAvatar(avatar);
          return (
            <li key={avatar.avatar_id}>
            <button
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(avatar.avatar_id)}
              className={cn(
                "group relative flex w-full flex-col overflow-hidden rounded-lg border text-left transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                selected
                  ? "border-primary ring-2 ring-primary"
                  : "border-border hover:border-primary/60",
              )}
            >
              <span className="relative block aspect-[3/4] w-full overflow-hidden bg-secondary">
                {avatar.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatar.thumbnail_url}
                    alt={label}
                    loading="lazy"
                    className="size-full object-cover"
                  />
                ) : (
                  <span className="flex size-full items-center justify-center text-muted-foreground">
                    <User className="size-8" aria-hidden />
                  </span>
                )}
                {selected && (
                  <span className="absolute right-2 top-2 flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Check className="size-4" aria-hidden />
                  </span>
                )}
                {custom && (
                  <Badge
                    variant="secondary"
                    className="absolute left-2 top-2 shadow-sm"
                  >
                    Yours
                  </Badge>
                )}
              </span>
              <span className="truncate px-2.5 py-2 text-xs font-medium">
                {label}
              </span>
            </button>
          </li>
        );
      })}
      </ul>
    </div>
  );
}
