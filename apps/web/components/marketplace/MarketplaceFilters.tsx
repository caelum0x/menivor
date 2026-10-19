"use client";

import * as React from "react";
import { Search, Tag } from "lucide-react";
import type { MarketplaceSort } from "@/lib/types";
import { DUB_LANGUAGE_CODES, MARKETPLACE_SORTS } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { languageLabel } from "@/components/marketplace/format";

export interface MarketplaceFiltersProps {
  query: string;
  tag: string;
  language: string;
  sort: MarketplaceSort;
  onQueryChange: (value: string) => void;
  onTagChange: (value: string) => void;
  onLanguageChange: (value: string) => void;
  onSortChange: (value: MarketplaceSort) => void;
}

const SORT_LABELS: Record<MarketplaceSort, string> = {
  top: "Top rated",
  new: "Newest",
  clones: "Most cloned",
  proven: "Proven (win-score)",
  most_remixed: "Most remixed",
};

/**
 * The browse controls for the marketplace: a text search, a single-tag filter,
 * a language filter, and a sort selector. Fully controlled — the page owns the
 * filter state and debounces the text inputs before fetching.
 */
export function MarketplaceFilters({
  query,
  tag,
  language,
  sort,
  onQueryChange,
  onTagChange,
  onLanguageChange,
  onSortChange,
}: Readonly<MarketplaceFiltersProps>) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search templates…"
          aria-label="Search templates by title or description"
          className="pl-9"
        />
      </div>

      <div className="relative">
        <Tag
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="text"
          value={tag}
          onChange={(event) => onTagChange(event.target.value)}
          placeholder="Filter by tag"
          aria-label="Filter by tag"
          className="pl-9"
        />
      </div>

      <Select
        value={language}
        onChange={(event) => onLanguageChange(event.target.value)}
        aria-label="Filter by language"
      >
        <option value="">All languages</option>
        {DUB_LANGUAGE_CODES.map((code) => (
          <option key={code} value={code}>
            {languageLabel(code)}
          </option>
        ))}
      </Select>

      <Select
        value={sort}
        onChange={(event) => onSortChange(event.target.value as MarketplaceSort)}
        aria-label="Sort templates"
      >
        {MARKETPLACE_SORTS.map((value) => (
          <option key={value} value={value}>
            {SORT_LABELS[value]}
          </option>
        ))}
      </Select>
    </div>
  );
}
