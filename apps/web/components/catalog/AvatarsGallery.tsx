"use client";

import * as React from "react";
import Link from "next/link";
import { User } from "lucide-react";
import type { Avatar } from "@/lib/types";
import { isCustomAvatar } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { avatarLabel } from "@/components/avatars/avatar-utils";
import { useAvatarsCatalog } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 18;

function matches(avatar: Avatar, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    avatarLabel(avatar).toLowerCase().includes(q) ||
    avatar.avatar_id.toLowerCase().includes(q) ||
    (avatar.provider ?? "").toLowerCase().includes(q)
  );
}

/** Searchable, paginated gallery of selectable avatars, each linking to detail. */
export function AvatarsGallery() {
  const { status, data, error, reload } = useAvatarsCatalog();
  const [query, setQuery] = React.useState("");

  const avatars = data ?? [];
  const filtered = React.useMemo(
    () => avatars.filter((a) => matches(a, query)),
    [avatars, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton count={9} lines={1} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load the avatar gallery"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (avatars.length === 0) {
    return (
      <EmptyState
        title="No avatars"
        message="No presenter avatars are available right now."
        icon={<User className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search avatars by name or provider"
        resultLabel={`${filtered.length} of ${avatars.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No avatar matches "${query}".`}
          icon={<User className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((avatar) => (
              <li key={avatar.avatar_id}>
                <AvatarGalleryCard avatar={avatar} />
              </li>
            ))}
          </ul>
          <Pagination
            page={page}
            pageCount={pageCount}
            totalItems={filtered.length}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}

function AvatarGalleryCard({ avatar }: Readonly<{ avatar: Avatar }>) {
  const label = avatarLabel(avatar);
  const yours = isCustomAvatar(avatar);
  const href = `/catalog/avatars/${encodeURIComponent(avatar.avatar_id)}`;

  return (
    <Card className="h-full overflow-hidden transition-colors hover:border-primary/60">
      <Link href={href} className="block">
        <div className="relative aspect-[4/5] bg-secondary">
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
              <User className="size-10" aria-hidden />
            </span>
          )}
          {yours && (
            <Badge variant="secondary" className="absolute right-2 top-2">
              Yours
            </Badge>
          )}
        </div>
        <CardContent className="flex items-center justify-between gap-2 p-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{label}</p>
            {avatar.provider && (
              <p className="truncate text-xs text-muted-foreground">
                {avatar.provider}
              </p>
            )}
          </div>
        </CardContent>
      </Link>
    </Card>
  );
}
