"use client";

import * as React from "react";
import { AlertTriangle, RefreshCw, Users } from "lucide-react";
import type { Workspace } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateWorkspaceForm } from "@/components/team/CreateWorkspaceForm";
import { roleBadgeVariant, roleLabel } from "@/components/team/roles";
import type { WorkspacesStatus } from "@/components/team/use-workspaces";

export interface WorkspaceListProps {
  status: WorkspacesStatus;
  workspaces: readonly Workspace[];
  errorMessage: string;
  creating: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCreate: (name: string) => void;
  onRetry: () => void;
}

/**
 * Left-hand list of the caller's workspaces plus an inline create form. Each row
 * shows the caller's own role; selecting one drives the detail pane. Purely
 * presentational.
 */
export function WorkspaceList({
  status,
  workspaces,
  errorMessage,
  creating,
  selectedId,
  onSelect,
  onCreate,
  onRetry,
}: Readonly<WorkspaceListProps>) {
  return (
    <div className="space-y-4">
      <CreateWorkspaceForm creating={creating} onCreate={onCreate} />

      {status === "loading" && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )}

      {status === "error" && (
        <Card className="border-destructive/40 bg-destructive/5">
          <CardContent className="flex items-start gap-3 p-4">
            <AlertTriangle
              className="mt-0.5 size-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div className="flex-1">
              <p className="text-sm text-muted-foreground">{errorMessage}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={onRetry}
              >
                <RefreshCw className="size-4" aria-hidden /> Try again
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status === "ready" && workspaces.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
            <span className="flex size-10 items-center justify-center rounded-full bg-primary/10">
              <Users className="size-5 text-primary" aria-hidden />
            </span>
            <p className="text-sm font-medium">No workspaces yet</p>
            <p className="text-sm text-muted-foreground">
              Create one above to start inviting teammates.
            </p>
          </CardContent>
        </Card>
      )}

      {status === "ready" && workspaces.length > 0 && (
        <ul className="space-y-2">
          {workspaces.map((ws) => {
            const active = ws.id === selectedId;
            return (
              <li key={ws.id}>
                <button
                  type="button"
                  onClick={() => onSelect(ws.id)}
                  aria-current={active}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${
                    active
                      ? "border-primary bg-primary/5"
                      : "border-border hover:bg-secondary/60"
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {ws.name}
                    </span>
                    {typeof ws.member_count === "number" && (
                      <span className="block text-xs text-muted-foreground">
                        {ws.member_count}{" "}
                        {ws.member_count === 1 ? "member" : "members"}
                      </span>
                    )}
                  </span>
                  <Badge variant={roleBadgeVariant(ws.role)}>
                    {roleLabel(ws.role)}
                  </Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
