"use client";

import * as React from "react";
import type { CoverStyle } from "@/lib/types";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

export interface CoverStylePickerProps {
  styles: readonly CoverStyle[];
  /** Currently selected style id. */
  value: string;
  disabled?: boolean;
  onChange: (styleId: string) => void;
}

/** Simple hex-colour validation for an optional swatch. */
function isHexColor(value: unknown): value is string {
  return typeof value === "string" && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value);
}

/**
 * Native-select picker for the cover render style. Selection is owned by the
 * parent; this component only reports changes. Renders an accent swatch and the
 * selected style's description as help text.
 */
export function CoverStylePicker({
  styles,
  value,
  disabled = false,
  onChange,
}: Readonly<CoverStylePickerProps>) {
  const selectId = React.useId();
  const selected = React.useMemo(
    () => styles.find((s) => s.id === value),
    [styles, value],
  );
  const accent = selected && isHexColor(selected.accent) ? selected.accent : undefined;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={selectId}>Style</Label>
      <div className="flex items-center gap-2">
        {accent && (
          <span
            aria-hidden
            className="size-5 shrink-0 rounded-full border border-border"
            style={{ backgroundColor: accent }}
          />
        )}
        <Select
          id={selectId}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {styles.map((style) => (
            <option key={style.id} value={style.id}>
              {style.name}
            </option>
          ))}
        </Select>
      </div>
      {selected?.description && (
        <p className="text-xs text-muted-foreground">{selected.description}</p>
      )}
    </div>
  );
}
