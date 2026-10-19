"use client";

import * as React from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface CreateWorkspaceFormProps {
  creating: boolean;
  onCreate: (name: string) => void;
}

/**
 * Inline "new workspace" form. Purely presentational — validation is limited to
 * a non-empty, trimmed name; all async state comes from the parent hook.
 */
export function CreateWorkspaceForm({
  creating,
  onCreate,
}: Readonly<CreateWorkspaceFormProps>) {
  const [name, setName] = React.useState("");
  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && !creating;

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    onCreate(trimmed);
    setName("");
  };

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="New workspace name"
        aria-label="New workspace name"
        maxLength={80}
        disabled={creating}
      />
      <Button type="submit" disabled={!canSubmit}>
        <Plus className="size-4" aria-hidden />
        {creating ? "Creating…" : "Create"}
      </Button>
    </form>
  );
}
