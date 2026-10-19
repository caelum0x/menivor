"use client";

import * as React from "react";
import { Image as ImageIcon } from "lucide-react";
import type { CoverStyle } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useCoverStylesCatalog } from "@/components/catalog/use-catalog";
import {
  CardGridSkeleton,
  EmptyState,
  ErrorPanel,
} from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 12;

/** Accept only `#RGB`/`#RRGGBB` hex strings for use as an inline style value. */
function safeHex(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value.trim())
    ? value.trim()
    : undefined;
}

function matches(style: CoverStyle, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    style.name.toLowerCase().includes(q) ||
    style.id.toLowerCase().includes(q) ||
    style.description.toLowerCase().includes(q)
  );
}

/** Searchable, paginated grid of cover / thumbnail style presets. */
export function CoverStylesBrowser() {
  const { status, data, error, reload } = useCoverStylesCatalog();
  const [query, setQuery] = React.useState("");

  const styles = data ?? [];
  const filtered = React.useMemo(
    () => styles.filter((s) => matches(s, query)),
    [styles, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(
    filtered,
    PAGE_SIZE,
  );

  if (status === "loading") return <CardGridSkeleton lines={2} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load cover styles"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (styles.length === 0) {
    return (
      <EmptyState
        title="No cover styles"
        message="The cover-style catalog is empty right now."
        icon={<ImageIcon className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search cover styles"
        resultLabel={`${filtered.length} of ${styles.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No cover style matches "${query}".`}
          icon={<ImageIcon className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((style) => (
              <li key={style.id}>
                <CoverStyleCard style={style} />
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

function CoverStyleCard({ style }: Readonly<{ style: CoverStyle }>) {
  const accent = safeHex(style.accent);
  const background = safeHex(style.background);

  return (
    <Card className="h-full overflow-hidden">
      <div
        className="flex aspect-video items-center justify-center border-b border-border"
        style={{ backgroundColor: background ?? "#0b0b0f" }}
        aria-hidden
      >
        <span
          className="px-4 text-center text-lg font-extrabold uppercase leading-tight tracking-tight"
          style={{ color: accent ?? "#ffde59" }}
        >
          Your headline here
        </span>
      </div>
      <CardContent className="flex flex-col gap-2 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold leading-tight">{style.name}</h3>
          <Badge variant="outline">{style.id}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{style.description}</p>
        {(accent || background) && (
          <div className="flex items-center gap-3 pt-1 text-xs text-muted-foreground">
            {accent && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="size-3.5 rounded-full border border-border"
                  style={{ backgroundColor: accent }}
                />
                Accent
              </span>
            )}
            {background && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="size-3.5 rounded-full border border-border"
                  style={{ backgroundColor: background }}
                />
                Background
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
