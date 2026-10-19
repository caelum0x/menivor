"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ManualProductInput } from "./api";

export interface ManualDraft {
  title: string;
  brand: string;
  price: string;
  originalPrice: string;
  currency: string;
  bullets: string;
  images: string;
  description: string;
}

export const EMPTY_MANUAL: ManualDraft = {
  title: "",
  brand: "",
  price: "",
  originalPrice: "",
  currency: "TRY",
  bullets: "",
  images: "",
  description: "",
};

function toNumber(value: string): number | null {
  const n = Number(value.replace(",", "."));
  return Number.isFinite(n) && n > 0 ? n : null;
}

function lines(value: string, max: number): string[] {
  return value
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, max);
}

export function manualToInput(draft: ManualDraft): ManualProductInput {
  return {
    title: draft.title.trim(),
    brand: draft.brand.trim(),
    description: draft.description.trim(),
    price: toNumber(draft.price),
    original_price: toNumber(draft.originalPrice),
    currency: draft.currency,
    bullets: lines(draft.bullets, 8),
    images: lines(draft.images, 10).filter((u) => /^https?:\/\//i.test(u)),
  };
}

/** Product details for stores that block automated page fetches. */
export function ManualProductForm({
  draft,
  onChange,
  disabled,
}: {
  draft: ManualDraft;
  onChange: (next: ManualDraft) => void;
  disabled?: boolean;
}) {
  const set = (key: keyof ManualDraft) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    onChange({ ...draft, [key]: e.target.value });
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="grid gap-1 md:col-span-2">
        <Label htmlFor="ad-title">Product name</Label>
        <Input id="ad-title" value={draft.title} onChange={set("title")} maxLength={200} disabled={disabled} required />
      </div>
      <div className="grid gap-1">
        <Label htmlFor="ad-brand">Brand</Label>
        <Input id="ad-brand" value={draft.brand} onChange={set("brand")} maxLength={80} disabled={disabled} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div className="grid gap-1">
          <Label htmlFor="ad-price">Price</Label>
          <Input id="ad-price" inputMode="decimal" value={draft.price} onChange={set("price")} disabled={disabled} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="ad-oprice">Was</Label>
          <Input id="ad-oprice" inputMode="decimal" value={draft.originalPrice} onChange={set("originalPrice")} disabled={disabled} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="ad-currency">Currency</Label>
          <Select id="ad-currency" value={draft.currency} onChange={set("currency")} disabled={disabled}>
            {["TRY", "USD", "EUR", "GBP"].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <div className="grid gap-1">
        <Label htmlFor="ad-bullets">Key features (one per line)</Label>
        <Textarea id="ad-bullets" rows={4} value={draft.bullets} onChange={set("bullets")} disabled={disabled} />
      </div>
      <div className="grid gap-1">
        <Label htmlFor="ad-images">Image URLs (one per line)</Label>
        <Textarea id="ad-images" rows={4} value={draft.images} onChange={set("images")} disabled={disabled} />
      </div>
      <div className="grid gap-1 md:col-span-2">
        <Label htmlFor="ad-desc">Description</Label>
        <Textarea id="ad-desc" rows={3} value={draft.description} onChange={set("description")} maxLength={2000} disabled={disabled} />
      </div>
    </div>
  );
}
