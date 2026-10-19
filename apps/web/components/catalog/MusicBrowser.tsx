"use client";

import * as React from "react";
import { Music } from "lucide-react";
import type { MusicTrack } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { useMusic } from "@/components/catalog/use-catalog";
import { CardGridSkeleton, EmptyState, ErrorPanel } from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 15;

/** Format seconds as `m:ss`; returns an em dash when duration is unknown. */
function formatDuration(seconds: number | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) {
    return "—";
  }
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function matches(track: MusicTrack, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    track.name.toLowerCase().includes(q) ||
    track.id.toLowerCase().includes(q) ||
    track.filename.toLowerCase().includes(q)
  );
}

/** Searchable, paginated table of background-music tracks. */
export function MusicBrowser() {
  const { status, data, error, reload } = useMusic();
  const [query, setQuery] = React.useState("");

  const tracks = data ?? [];
  const filtered = React.useMemo(
    () => tracks.filter((t) => matches(t, query)),
    [tracks, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(filtered, PAGE_SIZE);

  if (status === "loading") return <CardGridSkeleton count={6} lines={1} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load the music library"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (tracks.length === 0) {
    return (
      <EmptyState
        title="No music tracks"
        message="The background-music library is empty right now."
        icon={<Music className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search tracks by name or file"
        resultLabel={`${filtered.length} of ${tracks.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No track matches "${query}".`}
          icon={<Music className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <Card className="overflow-hidden">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-4 py-3 font-medium">Track</th>
                      <th className="px-4 py-3 font-medium">Music ID</th>
                      <th className="px-4 py-3 font-medium">File</th>
                      <th className="px-4 py-3 text-right font-medium">Length</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((track) => (
                      <tr
                        key={track.id}
                        className="border-b border-border/60 last:border-0 hover:bg-secondary/40"
                      >
                        <td className="px-4 py-3">
                          <span className="flex items-center gap-2 font-medium">
                            <Music
                              className="size-4 shrink-0 text-primary"
                              aria-hidden
                            />
                            {track.name}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <code className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                            {track.id}
                          </code>
                        </td>
                        <td className="max-w-[16rem] truncate px-4 py-3 text-muted-foreground">
                          {track.filename}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                          {formatDuration(track.duration_s)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
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
