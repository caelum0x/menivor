"use client";

import * as React from "react";
import { Type } from "lucide-react";
import type { CaptionStyle } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useCaptionStyles } from "@/components/catalog/use-catalog";
import { CardGridSkeleton, EmptyState, ErrorPanel } from "@/components/catalog/states";
import { Pagination, usePaginated } from "@/components/catalog/Pagination";
import { SearchBar } from "@/components/catalog/SearchBar";

const PAGE_SIZE = 12;

/**
 * Convert an ASS `&HAABBGGRR` colour to a CSS `#RRGGBB` so a swatch can preview
 * the caption colour. Returns `undefined` for anything that is not a valid ASS
 * colour literal, so the caller can fall back gracefully.
 */
function assColorToCss(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const match = /^&H?([0-9A-Fa-f]{2})?([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})$/.exec(
    value.trim(),
  );
  if (!match) return undefined;
  const [, , bb, gg, rr] = match;
  return `#${rr}${gg}${bb}`;
}

function matches(style: CaptionStyle, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    style.name.toLowerCase().includes(q) ||
    style.id.toLowerCase().includes(q) ||
    style.description.toLowerCase().includes(q)
  );
}

/** Browsable, searchable, paginated grid of caption-style presets. */
export function CaptionStylesBrowser() {
  const { status, data, error, reload } = useCaptionStyles();
  const [query, setQuery] = React.useState("");

  const styles = data ?? [];
  const filtered = React.useMemo(
    () => styles.filter((s) => matches(s, query)),
    [styles, query],
  );
  const { page, pageCount, pageItems, setPage } = usePaginated(filtered, PAGE_SIZE);

  if (status === "loading") return <CardGridSkeleton lines={2} />;
  if (status === "error") {
    return (
      <ErrorPanel
        title="Couldn't load caption styles"
        message={error}
        onRetry={reload}
      />
    );
  }
  if (styles.length === 0) {
    return (
      <EmptyState
        title="No caption styles"
        message="The caption-style catalog is empty right now. Check back soon."
        icon={<Type className="size-6" aria-hidden />}
      />
    );
  }

  return (
    <div>
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="Search caption styles"
        resultLabel={`${filtered.length} of ${styles.length}`}
        className="mb-6"
      />

      {filtered.length === 0 ? (
        <EmptyState
          title="No matches"
          message={`No caption style matches "${query}".`}
          icon={<Type className="size-6" aria-hidden />}
        />
      ) : (
        <>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {pageItems.map((style) => (
              <li key={style.id}>
                <CaptionStyleCard style={style} />
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

function CaptionStyleCard({ style }: Readonly<{ style: CaptionStyle }>) {
  const primary = assColorToCss(style.primary);
  const secondary = assColorToCss(style.secondary);

  return (
    <Card className="h-full">
      <CardContent className="flex h-full flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold leading-tight">{style.name}</h3>
          <Badge variant="outline">{style.id}</Badge>
        </div>
        <p className="flex-1 text-sm text-muted-foreground">
          {style.description}
        </p>
        <div
          className="flex items-center justify-center rounded-md bg-black px-3 py-4"
          aria-hidden
        >
          <span
            className="text-lg font-extrabold uppercase tracking-tight"
            style={{
              color: primary ?? "#ffffff",
              WebkitTextStroke: "1px rgba(0,0,0,0.6)",
            }}
          >
            THIS{" "}
            <span style={{ color: secondary ?? primary ?? "#ffde59" }}>
              changed
            </span>{" "}
            everything
          </span>
        </div>
        {(primary || secondary) && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {primary && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="size-3.5 rounded-full border border-border"
                  style={{ backgroundColor: primary }}
                />
                Primary
              </span>
            )}
            {secondary && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  className="size-3.5 rounded-full border border-border"
                  style={{ backgroundColor: secondary }}
                />
                Highlight
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
