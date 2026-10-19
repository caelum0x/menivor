/**
 * Self-contained "Your access" section for a workspace: fetches the caller's
 * effective role + permissions (GET /me/permissions) and renders them via
 * {@link PermissionsCard}. Owns its own loading / error state so a failure here
 * never blanks the surrounding screen.
 *
 * Reused on both the legacy Team workspace screen (to surface the caller's
 * enterprise role/permissions) and the Team Roles screen.
 */

import { useCallback } from "react";

import { getMyPermissions } from "@/lib/api";
import type { Permissions } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { useResource } from "@/components/me/use-resource";

import { PermissionsCard } from "./PermissionsCard";

interface PermissionsViewProps {
  workspaceId: string;
  token: string | undefined;
}

export function PermissionsView({ workspaceId, token }: PermissionsViewProps) {
  const fetcher = useCallback(
    () => getMyPermissions(workspaceId, { token }),
    [workspaceId, token],
  );
  const { status, data, error, reload } = useResource<Permissions>(fetcher);

  return (
    <Section title="YOUR ACCESS">
      <SectionState status={status} error={error} onRetry={reload}>
        {data ? <PermissionsCard permissions={data} /> : null}
      </SectionState>
    </Section>
  );
}
