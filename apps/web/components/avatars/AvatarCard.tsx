"use client";

import { User } from "lucide-react";
import type { Avatar } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { avatarLabel } from "@/components/avatars/avatar-utils";

interface AvatarCardProps {
  avatar: Avatar;
}

/** Read-only card for one of the caller's custom photo→avatars. */
export function AvatarCard({ avatar }: AvatarCardProps) {
  const label = avatarLabel(avatar);
  return (
    <Card className="overflow-hidden">
      <CardContent className="flex items-center gap-3 p-4">
        <span className="relative block size-14 shrink-0 overflow-hidden rounded-md bg-secondary">
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
              <User className="size-6" aria-hidden />
            </span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">Talking photo</p>
        </div>
        <Badge variant="secondary">Yours</Badge>
      </CardContent>
    </Card>
  );
}
