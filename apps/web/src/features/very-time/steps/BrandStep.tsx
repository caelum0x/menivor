"use client";

import * as React from "react";
import { Shirt, Store } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { VeryTimeBrand } from "../api";
import {
  CHEST_MAX,
  CTA_MAX,
  CTA_PLACEHOLDER,
  GARMENT_MAX,
  LINE_MAX,
  OXHAN_SUMMARY,
  garmentFileProblem,
  logoFileProblem,
} from "../model";
import { ImageUploadField } from "./ImageUploadField";

export interface BrandStepProps {
  readonly brand: VeryTimeBrand;
  readonly line: string;
  readonly onChange: (brand: VeryTimeBrand) => void;
  readonly onLine: (line: string) => void;
  readonly onUploading?: (uploading: boolean) => void;
}

const CHOICES = [
  { id: "oxhan", title: OXHAN_SUMMARY.name, note: "Our own shirt, host and closing card.", Icon: Shirt },
  { id: "custom", title: "Your brand", note: "Your garment, words, closing line and logo.", Icon: Store },
] as const;

/** Step 4 (optional): the built-in Oxhan Atelier brand, or your own garment, line, call to action and logo. */
export function BrandStep({ brand, line, onChange, onLine, onUploading }: BrandStepProps) {
  const uploads = React.useRef(0);
  const trackUpload = (busy: boolean) => {
    uploads.current = Math.max(0, uploads.current + (busy ? 1 : -1));
    onUploading?.(uploads.current > 0);
  };

  return (
    <div className="space-y-5">
      <ul className="grid gap-3 sm:grid-cols-2" aria-label="Brand">
        {CHOICES.map(({ id, title, note, Icon }) => {
          const selected = brand.preset === id;
          return (
            <li key={id}>
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onChange(id === "oxhan" ? { preset: "oxhan" } : { ...brand, preset: "custom" })}
                className={cn(
                  "glass-subtle flex h-full w-full flex-col items-start gap-2 rounded-2xl p-4 text-left transition-colors",
                  "hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selected && "border-primary/70",
                )}
              >
                <Icon className="size-5 text-primary" aria-hidden />
                <span className="font-semibold">{title}</span>
                <span className="text-sm text-muted-foreground">{note}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {brand.preset === "oxhan" ? (
        <dl className="space-y-1 rounded-xl border border-white/10 p-4 text-sm" data-testid="vt-oxhan-summary">
          <div><dt className="inline font-medium">Garment: </dt><dd className="inline">{OXHAN_SUMMARY.garment}</dd></div>
          <div><dt className="inline font-medium">Host: </dt><dd className="inline">{OXHAN_SUMMARY.host}</dd></div>
          <div><dt className="inline font-medium">Line: </dt><dd className="inline">{OXHAN_SUMMARY.line}</dd></div>
          <div><dt className="inline font-medium">Ends with: </dt><dd className="inline">{OXHAN_SUMMARY.cta}</dd></div>
        </dl>
      ) : null}

      {brand.preset === "custom" ? (
        <div className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="vt-garment">What the character wears</Label>
            <Input
              id="vt-garment"
              value={brand.garment ?? ""}
              maxLength={GARMENT_MAX}
              autoComplete="off"
              onChange={(event) => onChange({ ...brand, garment: event.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vt-chest">Words on the chest</Label>
            <Input
              id="vt-chest"
              value={brand.chest_text ?? ""}
              maxLength={CHEST_MAX}
              autoComplete="off"
              onChange={(event) => onChange({ ...brand, chest_text: event.target.value })}
            />
          </div>
          <ImageUploadField
            id="vt-garment-photo"
            label="Upload your garment photo"
            hint="Optional. A flat photo of the shirt keeps it the same in every shot."
            value={brand.garment_ref}
            readyText="Garment photo added"
            previewAlt="Your garment"
            problemFor={garmentFileProblem}
            onChange={(key) => onChange({ ...brand, garment_ref: key })}
            onUploading={trackUpload}
          />
          <div className="space-y-2">
            <Label htmlFor="vt-line">Closing line</Label>
            <Input
              id="vt-line"
              value={line}
              maxLength={LINE_MAX}
              autoComplete="off"
              onChange={(event) => onLine(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vt-cta">Call to action on the end card</Label>
            <Input
              id="vt-cta"
              value={brand.cta ?? ""}
              maxLength={CTA_MAX}
              placeholder={CTA_PLACEHOLDER}
              autoComplete="off"
              onChange={(event) => onChange({ ...brand, cta: event.target.value })}
            />
          </div>
          <ImageUploadField
            id="vt-logo"
            label="Upload your logo"
            hint="Optional. Shown on the end card. PNG, JPEG or WebP, up to 5 MB."
            value={brand.logo_ref}
            readyText="Logo added"
            previewAlt="Your logo"
            problemFor={logoFileProblem}
            onChange={(key) => onChange({ ...brand, logo_ref: key })}
            onUploading={trackUpload}
          />
        </div>
      ) : null}
    </div>
  );
}
