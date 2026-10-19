"use client";

import * as React from "react";
import { UserPlus } from "lucide-react";
import {
  ASSIGNABLE_WORKSPACE_ROLES,
  type AssignableWorkspaceRole,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { roleLabel } from "@/components/team/roles";

export interface InviteMemberFormProps {
  inviting: boolean;
  inviteError: string;
  onInvite: (email: string, role: AssignableWorkspaceRole) => Promise<boolean>;
}

const DEFAULT_ROLE: AssignableWorkspaceRole = "member";

/**
 * Invite-by-email form with a role picker. Only rendered for owners/admins
 * (the caller gates it). People who already have an account join right away;
 * anyone else gets a pending invite whose accept link the parent shows.
 * Clears the email on success.
 */
export function InviteMemberForm({
  inviting,
  inviteError,
  onInvite,
}: Readonly<InviteMemberFormProps>) {
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<AssignableWorkspaceRole>(DEFAULT_ROLE);

  const trimmed = email.trim();
  // Minimal boundary check; the backend is the source of truth for validity.
  const emailLooksValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);
  const canSubmit = emailLooksValid && !inviting;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    const ok = await onInvite(trimmed, role);
    if (ok) {
      setEmail("");
      setRole(DEFAULT_ROLE);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
        <div className="space-y-1.5">
          <Label htmlFor="invite-email">Invite by email</Label>
          <Input
            id="invite-email"
            type="email"
            inputMode="email"
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@example.com"
            disabled={inviting}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="invite-role">Role</Label>
          <Select
            id="invite-role"
            value={role}
            onChange={(e) =>
              setRole(e.target.value as AssignableWorkspaceRole)
            }
            disabled={inviting}
          >
            {ASSIGNABLE_WORKSPACE_ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </Select>
        </div>
        <Button type="submit" disabled={!canSubmit}>
          <UserPlus className="size-4" aria-hidden />
          {inviting ? "Inviting…" : "Invite"}
        </Button>
      </div>
      {inviteError && (
        <p className="text-sm text-destructive" role="alert">
          {inviteError}
        </p>
      )}
    </form>
  );
}
