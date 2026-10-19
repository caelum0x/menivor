"use client";

import * as React from "react";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { SecurityPolicy, SecurityPolicyRequest } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { formatList, parseList } from "@/components/settings/sso/domains";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface SecurityPolicyFormProps {
  /** The workspace's current policy, or `null` when none is configured. */
  policy: SecurityPolicy | null;
  canManage: boolean;
  onSave: (body: SecurityPolicyRequest) => Promise<SecurityPolicy>;
}

type Phase =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved" }
  | { status: "error"; message: string };

/**
 * Configure a workspace's enterprise login security policy: require SSO, session
 * timeout, allowed email domains, MFA, and an IP allowlist. Multi-value fields are
 * edited as free text (one entry per line) and normalized to `string[]` on save.
 * Cert-free / secret-free. Controls are gated on `workspace.settings` (the server
 * re-enforces it). All form state is controlled and updated immutably.
 */
export function SecurityPolicyForm({
  policy,
  canManage,
  onSave,
}: SecurityPolicyFormProps) {
  const [requireSso, setRequireSso] = React.useState(policy?.require_sso ?? false);
  const [timeout, setTimeoutMin] = React.useState<string>(
    policy ? String(policy.session_timeout_min) : "0",
  );
  const [domains, setDomains] = React.useState(
    formatList(policy?.allowed_email_domains),
  );
  const [mfaRequired, setMfaRequired] = React.useState(policy?.mfa_required ?? false);
  const [ipAllowlist, setIpAllowlist] = React.useState(
    formatList(policy?.ip_allowlist),
  );
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  // Reseed whenever the loaded policy changes (e.g. the caller switches workspaces).
  const policyKey = policy
    ? `${policy.workspace_id}:${policy.updated_at ?? ""}`
    : "none";
  React.useEffect(() => {
    setRequireSso(policy?.require_sso ?? false);
    setTimeoutMin(policy ? String(policy.session_timeout_min) : "0");
    setDomains(formatList(policy?.allowed_email_domains));
    setMfaRequired(policy?.mfa_required ?? false);
    setIpAllowlist(formatList(policy?.ip_allowlist));
    setPhase({ status: "idle" });
  }, [policyKey, policy]);

  const busy = phase.status === "saving";

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage || busy) return;

      const parsedTimeout = Number.parseInt(timeout, 10);
      const body: SecurityPolicyRequest = {
        require_sso: requireSso,
        session_timeout_min:
          Number.isFinite(parsedTimeout) && parsedTimeout >= 0 ? parsedTimeout : 0,
        allowed_email_domains: parseList(domains),
        mfa_required: mfaRequired,
        ip_allowlist: parseList(ipAllowlist),
      };

      setPhase({ status: "saving" });
      try {
        await onSave(body);
        setPhase({ status: "saved" });
      } catch (err) {
        setPhase({
          status: "error",
          message:
            friendlyErrorMessage(err, "Couldn't save the security policy. Please try again."),
        });
      }
    },
    [busy, canManage, domains, ipAllowlist, mfaRequired, onSave, requireSso, timeout],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Security policy</CardTitle>
        <CardDescription>
          Set login requirements for everyone in this workspace. These rules are
          enforced on top of your identity provider.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <fieldset disabled={!canManage || busy} className="space-y-5">
            <label className="flex items-start gap-3 rounded-lg border border-border p-3">
              <input
                type="checkbox"
                className="mt-0.5 size-4 rounded border-input accent-primary"
                checked={requireSso}
                onChange={(e) => setRequireSso(e.target.checked)}
              />
              <span>
                <span className="text-sm font-medium">Require SSO</span>
                <span className="block text-xs text-muted-foreground">
                  Members must sign in through your identity provider.
                </span>
              </span>
            </label>

            <label className="flex items-start gap-3 rounded-lg border border-border p-3">
              <input
                type="checkbox"
                className="mt-0.5 size-4 rounded border-input accent-primary"
                checked={mfaRequired}
                onChange={(e) => setMfaRequired(e.target.checked)}
              />
              <span>
                <span className="text-sm font-medium">Require MFA</span>
                <span className="block text-xs text-muted-foreground">
                  Require multi-factor authentication for workspace access.
                </span>
              </span>
            </label>

            <div className="space-y-2">
              <Label htmlFor="policy-timeout">Session timeout (minutes)</Label>
              <Input
                id="policy-timeout"
                type="number"
                min={0}
                inputMode="numeric"
                value={timeout}
                onChange={(e) => setTimeoutMin(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                How long a session stays valid before re-authentication. Use 0 for
                no enforced timeout.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="policy-domains">Allowed email domains</Label>
              <Textarea
                id="policy-domains"
                rows={3}
                value={domains}
                placeholder={"acme.com\npartner.example"}
                onChange={(e) => setDomains(e.target.value)}
                spellCheck={false}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                One domain per line. Leave empty to allow any domain.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="policy-ips">IP allowlist</Label>
              <Textarea
                id="policy-ips"
                rows={3}
                value={ipAllowlist}
                placeholder={"203.0.113.0/24\n198.51.100.7"}
                onChange={(e) => setIpAllowlist(e.target.value)}
                spellCheck={false}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                One IP or CIDR range per line. Leave empty to allow any IP.
              </p>
            </div>
          </fieldset>

          {phase.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          )}
          {phase.status === "saved" && (
            <p className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="size-4 shrink-0" aria-hidden />
              Security policy saved.
            </p>
          )}

          {canManage && (
            <Button type="submit" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="animate-spin" /> Saving…
                </>
              ) : (
                "Save policy"
              )}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
