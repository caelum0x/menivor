import * as React from "react";
import { RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  REEL_FILTERS,
  type ReelFilter,
} from "../reels-filter";

export interface ReelsFilterBarProps {
  filter: ReelFilter;
  query: string;
  counts: Record<ReelFilter, number>;
  refreshing: boolean;
  onFilterChange: (filter: ReelFilter) => void;
  onQueryChange: (query: string) => void;
  onRefresh: () => void;
}

/**
 * Toolbar above the reels table: a state-bucket picker (with per-bucket
 * counts), a free-text search box, and a refresh control. Purely presentational
 * — all state lives in the parent page.
 */
export function ReelsFilterBar({
  filter,
  query,
  counts,
  refreshing,
  onFilterChange,
  onQueryChange,
  onRefresh,
}: Readonly<ReelsFilterBarProps>) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <label htmlFor="reel-filter" className="sr-only">
          Filter by status
        </label>
        <Select
          id="reel-filter"
          className="w-44"
          value={filter}
          onChange={(e) => onFilterChange(e.target.value as ReelFilter)}
        >
          {REEL_FILTERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label} ({counts[option.value]})
            </option>
          ))}
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <label htmlFor="reel-search" className="sr-only">
            Search reels
          </label>
          <Input
            id="reel-search"
            className="pl-9"
            placeholder="Search by id or hook…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={refreshing}
        >
          <RefreshCw
            className={refreshing ? "size-4 animate-spin" : "size-4"}
            aria-hidden
          />
          Refresh
        </Button>
      </div>
    </div>
  );
}
