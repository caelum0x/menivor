"use client";

import * as React from "react";
import { Package, Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import type { AgentNeed } from "./api";

export const PICKER_MAX = 6;

type Option = AgentNeed["options"][number];

/** The brand's products as one-click choices (thumbnail + name); a search box when there are more than 6. */
export function ProductPicker({
  options,
  disabled,
  onPick,
}: {
  options: Option[];
  disabled?: boolean;
  onPick: (option: Option) => void;
}) {
  const [query, setQuery] = React.useState("");
  const q = query.trim().toLowerCase();
  const shown = (q ? options.filter((o) => o.name.toLowerCase().includes(q)) : options).slice(0, PICKER_MAX);
  return (
    <div className="space-y-2" role="group" aria-label="Pick a product">
      {options.length > PICKER_MAX && (
        <label className="relative block max-w-sm">
          <span className="sr-only">Search products</span>
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${options.length} products`}
            className="pl-8"
          />
        </label>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {shown.map((o) => (
          <button
            key={o.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(o)}
            className="flex items-center gap-2 rounded-xl border border-border bg-white/[0.03] p-2 text-left text-sm hover:bg-white/[0.07] disabled:opacity-50"
          >
            {o.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element -- remote catalog images, any host
              <img src={o.thumbnail_url} alt="" className="size-10 shrink-0 rounded-lg object-cover" />
            ) : (
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-white/[0.06]">
                <Package className="size-4 text-muted-foreground" aria-hidden />
              </span>
            )}
            <span className="min-w-0">
              <span className="block truncate font-medium">{o.name}</span>
              {o.detail && <span className="block truncate text-xs text-muted-foreground">{o.detail}</span>}
            </span>
          </button>
        ))}
        {shown.length === 0 && <p className="text-sm text-muted-foreground">No product matches “{query}”.</p>}
      </div>
    </div>
  );
}
