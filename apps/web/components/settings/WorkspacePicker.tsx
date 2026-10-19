"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { Workspace } from "@/lib/types";

export interface WorkspacePickerProps {
  workspaces: readonly Workspace[];
  selectedId: string | null;
  onSelect: (workspaceId: string) => void;
  disabled?: boolean;
}

/**
 * A small labelled workspace selector. Presentational — the parent owns the
 * workspace list + selection state. Hidden when there is only a single
 * workspace (nothing to choose).
 */
export function WorkspacePicker({
  workspaces,
  selectedId,
  onSelect,
  disabled,
}: Readonly<WorkspacePickerProps>) {
  if (workspaces.length <= 1) return null;

  return (
    <div className="flex flex-col gap-1.5 sm:max-w-xs">
      <Label htmlFor="workspace-picker">Workspace</Label>
      <Select
        id="workspace-picker"
        value={selectedId ?? ""}
        disabled={disabled}
        onChange={(e) => onSelect(e.target.value)}
      >
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </Select>
    </div>
  );
}
