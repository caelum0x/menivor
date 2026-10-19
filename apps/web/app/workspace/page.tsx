"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Users } from "lucide-react";
import { getMe } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { AccountNav } from "@/components/account/AccountNav";
import { AppHeader } from "@/components/account/AppHeader";
import { WorkspaceDetail } from "@/components/team/WorkspaceDetail";
import { WorkspaceList } from "@/components/team/WorkspaceList";
import { MyInvitations } from "@/components/team/MyInvitations";
import { useWorkspaces } from "@/components/team/use-workspaces";
import { WorkspaceBillingSummary } from "@/components/workspace/WorkspaceBillingSummary";

/**
 * Account → Workspaces. The caller's workspaces on the left (with an inline
 * create form), and the selected workspace's members + plan/usage on the right.
 * Owners/admins get invite / role / remove controls and a billing link; members
 * can view and leave. This is an additive membership + billing layer keyed to
 * each workspace id — it never touches another tenant's data.
 */
export default function WorkspacePage() {
  const { getToken, isLoaded } = useAuth();
  const { status, workspaces, errorMessage, creating, reload, create } =
    useWorkspaces();

  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [currentUserId, setCurrentUserId] = React.useState<string | null>(null);

  // Resolve the signed-in user's id once, to flag their own member row and gate
  // self-actions (leave / can't demote yourself, etc.).
  React.useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    void (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const me = await getMe({ token });
        if (!cancelled) setCurrentUserId(me.user_id);
      } catch {
        if (!cancelled) setCurrentUserId(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, isLoaded]);

  // Keep a valid selection: default to the first workspace, and clear it if the
  // selected workspace disappears (e.g. after leaving).
  React.useEffect(() => {
    const first = workspaces[0];
    if (!first) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!workspaces.some((w) => w.id === selectedId)) setSelectedId(first.id);
  }, [workspaces, selectedId]);

  const handleCreate = React.useCallback(
    (name: string) => {
      void create(name).then((created) => {
        if (created) setSelectedId(created.id);
      });
    },
    [create],
  );

  const handleLeft = React.useCallback(() => {
    setSelectedId(null);
    reload();
  }, [reload]);

  const handleInviteAccepted = React.useCallback(
    (workspaceId: string | undefined) => {
      if (workspaceId) setSelectedId(workspaceId);
      reload();
    },
    [reload],
  );

  const selected = workspaces.find((w) => w.id === selectedId) ?? null;

  return (
    <main className="min-h-dvh">
      <AppHeader />

      <section className="container py-10">
        <div className="mx-auto max-w-5xl">
          <div className="mb-6">
            <p className="text-sm font-medium text-muted-foreground">Account</p>
            <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
              <Users className="size-7 text-primary" aria-hidden />
              Workspaces
            </h1>
            <p className="mt-2 max-w-2xl text-muted-foreground">
              Create workspaces, invite teammates by email, and share credits.
              Owners and admins manage members, roles, and billing; members can
              view and leave.
            </p>
          </div>

          <AccountNav />

          <MyInvitations onAccepted={handleInviteAccepted} />

          <div className="grid gap-6 lg:grid-cols-[20rem_1fr]">
            <WorkspaceList
              status={status}
              workspaces={workspaces}
              errorMessage={errorMessage}
              creating={creating}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onCreate={handleCreate}
              onRetry={reload}
            />

            {selected ? (
              <div className="space-y-8">
                <WorkspaceDetail
                  key={selected.id}
                  workspace={selected}
                  currentUserId={currentUserId}
                  onLeft={handleLeft}
                />
                <WorkspaceBillingSummary workspaceId={selected.id} />
              </div>
            ) : (
              <Card className="border-dashed">
                <CardContent className="flex flex-col items-center justify-center gap-2 py-20 text-center">
                  <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
                    <Users className="size-6 text-primary" aria-hidden />
                  </span>
                  <p className="font-medium">Select a workspace</p>
                  <p className="text-sm text-muted-foreground">
                    Choose a workspace on the left, or create one to get started.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
