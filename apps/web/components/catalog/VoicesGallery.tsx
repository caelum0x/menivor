"use client";

import * as React from "react";
import Link from "next/link";
import { Mic } from "lucide-react";
import type { Voice } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useVoicesCatalog } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";
import { VoicePreviewButton } from "@/components/catalog/VoicePreviewButton";

const PAGE_SIZE = 18;

export function voiceLabel(voice: Voice): string {
  return voice.name?.trim() || voice.voice_id;
}

function matches(voice: Voice, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    voiceLabel(voice).toLowerCase().includes(q) ||
    voice.voice_id.toLowerCase().includes(q) ||
    (voice.category ?? "").toLowerCase().includes(q)
  );
}

/** Searchable, paginated gallery of narrator voices, each linking to detail. */
export function VoicesGallery() {
  const { status, data, error, reload } = useVoicesCatalog();
  const [query, setQuery] = React.useState("");

  const voices = data ?? [];
  const filtered = React.useMemo(
    () => voices.filter((v) => matches(v, query)),
    [voices, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton count={9} lines={2} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load the voice gallery"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (voices.length === 0) {
    return (
      <EmptyState
        title="No voices"
        message="No narrator voices are available right now."
        icon={<Mic className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search voices by name or category"
        resultLabel={`${filtered.length} of ${voices.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No voice matches "${query}".`}
          icon={<Mic className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((voice) => (
              <li key={voice.voice_id}>
                <VoiceGalleryCard voice={voice} />
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

function VoiceGalleryCard({ voice }: Readonly<{ voice: Voice }>) {
  const label = voiceLabel(voice);
  const href = `/catalog/voices/${encodeURIComponent(voice.voice_id)}`;
  const accent = voice.labels?.accent;
  const gender = voice.labels?.gender;

  return (
    <Card className="h-full transition-colors hover:border-primary/60">
      <CardContent className="flex h-full flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <Link href={href} className="flex min-w-0 items-start gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Mic className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="truncate font-medium leading-tight hover:underline">
                {label}
              </p>
              {voice.category && (
                <p className="truncate text-xs text-muted-foreground">
                  {voice.category}
                </p>
              )}
            </div>
          </Link>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {gender && <Badge variant="outline">{gender}</Badge>}
          {accent && <Badge variant="outline">{accent}</Badge>}
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 pt-1">
          <VoicePreviewButton url={voice.preview_url} label={label} />
          <Link
            href={href}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Details
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
