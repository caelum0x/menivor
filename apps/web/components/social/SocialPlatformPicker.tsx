"use client";

import * as React from "react";
import type { SocialPlatform } from "@/lib/types";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

export interface SocialPlatformPickerProps {
  platforms: readonly SocialPlatform[];
  /** Currently selected platform id. */
  value: string;
  disabled?: boolean;
  onChange: (platformId: string) => void;
}

/**
 * Native-select picker for the target social platform. Selection is owned by the
 * parent; this component only reports changes.
 */
export function SocialPlatformPicker({
  platforms,
  value,
  disabled = false,
  onChange,
}: Readonly<SocialPlatformPickerProps>) {
  const selectId = React.useId();

  return (
    <div className="space-y-1.5">
      <Label htmlFor={selectId}>Platform</Label>
      <Select
        id={selectId}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {platforms.map((platform) => (
          <option key={platform.id} value={platform.id}>
            {platform.name}
          </option>
        ))}
      </Select>
    </div>
  );
}
