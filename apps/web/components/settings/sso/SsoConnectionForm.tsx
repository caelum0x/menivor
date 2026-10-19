"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import type {
  SSOConfigRequest,
  SSOConnection,
  SsoProtocol,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { CopyBox } from "@/components/apikeys/CopyBox";
import { ApiError } from "@/lib/api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface SsoConnectionFormProps {
  /** The workspace's current cert-free connection, or `null` when unset. */
  connection: SSOConnection | null;
  /** Whether the caller may edit (holds `workspace.settings`). */
  canManage: boolean;
  /** Canonical SP ACS URL — persisted with the connection and shown to the IdP. */
  acsUrl: string;
  /** Public SP metadata URL to hand to the IdP admin. */
  metadataUrl: string;
  /** Persist the connection. Rejects with an {@link ApiError} on failure. */
  onSave: (body: SSOConfigRequest) => Promise<SSOConnection>;
  /** Delete the connection. Rejects with an {@link ApiError} on failure. */
  onDelete: () => Promise<void>;
}

type Phase =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "deleting" }
  | { status: "saved" }
  | { status: "error"; message: string };

function isSaml(protocol: string): boolean {
  return protocol !== "oidc";
}

/**
 * Configure a workspace's Enterprise SSO connection. The IdP signing certificate
 * and OIDC client secret are WRITE-ONLY — they are never rendered back (only a
 * "configured" indicator is shown), and the inputs start empty. Because the API
 * replaces the whole connection on save, leaving a secret field blank CLEARS the
 * stored secret; the form warns before that silent loss. All state is controlled
 * and updated immutably; the server independently re-enforces `workspace.settings`.
 */
export function SsoConnectionForm({
  connection,
  canManage,
  acsUrl,
  metadataUrl,
  onSave,
  onDelete,
}: SsoConnectionFormProps) {
  const [protocol, setProtocol] = React.useState<SsoProtocol>(
    (connection?.protocol as SsoProtocol) || "saml",
  );
  const [idpEntityId, setIdpEntityId] = React.useState(connection?.idp_entity_id ?? "");
  const [idpSsoUrl, setIdpSsoUrl] = React.useState(connection?.idp_sso_url ?? "");
  // The ACS URL is the deterministic SP endpoint — default to the canonical value
  // (falling back to any stored value) so the SP metadata is correct on first save.
  const spAcsUrl = connection?.sp_acs_url || acsUrl;
  const [oidcClientId, setOidcClientId] = React.useState(
    connection?.oidc_client_id ?? "",
  );
  // WRITE-ONLY secrets — never seeded from `connection`; kept only in local state.
  const [idpCert, setIdpCert] = React.useState("");
  const [oidcSecret, setOidcSecret] = React.useState("");
  const [enabled, setEnabled] = React.useState(connection?.enabled ?? false);
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  // Reseed the non-secret fields whenever the loaded connection changes (e.g. the
  // caller switches workspaces). Secrets stay blank by design.
  const connKey = connection
    ? `${connection.workspace_id}:${connection.updated_at ?? ""}`
    : "none";
  React.useEffect(() => {
    setProtocol((connection?.protocol as SsoProtocol) || "saml");
    setIdpEntityId(connection?.idp_entity_id ?? "");
    setIdpSsoUrl(connection?.idp_sso_url ?? "");
    setOidcClientId(connection?.oidc_client_id ?? "");
    setIdpCert("");
    setOidcSecret("");
    setEnabled(connection?.enabled ?? false);
    setPhase({ status: "idle" });
  }, [connKey, connection]);

  const busy = phase.status === "saving" || phase.status === "deleting";
  const saml = isSaml(protocol);

  // A configured secret is cleared if left blank on save (the API replaces the
  // whole connection). Warn only when there is something to lose.
  const willClearCert = saml && Boolean(connection?.has_certificate) && idpCert.trim() === "";
  const willClearSecret =
    !saml && Boolean(connection?.has_client_secret) && oidcSecret.trim() === "";

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage || busy) return;

      const body: SSOConfigRequest = {
        protocol,
        idp_entity_id: idpEntityId.trim(),
        idp_sso_url: idpSsoUrl.trim(),
        sp_acs_url: spAcsUrl.trim(),
        oidc_client_id: oidcClientId.trim(),
        enabled,
      };
      // Only attach a secret the admin actually typed. (A blank value still
      // replaces the stored secret server-side — surfaced via the warnings above.)
      if (idpCert.trim()) body.idp_x509_cert = idpCert.trim();
      if (oidcSecret.trim()) body.oidc_client_secret = oidcSecret.trim();

      setPhase({ status: "saving" });
      try {
        await onSave(body);
        setIdpCert("");
        setOidcSecret("");
        setPhase({ status: "saved" });
      } catch (err) {
        setPhase({
          status: "error",
          message:
            friendlyErrorMessage(err, "Couldn't save the SSO connection. Please try again."),
        });
      }
    },
    [
      busy,
      canManage,
      enabled,
      idpCert,
      idpEntityId,
      idpSsoUrl,
      oidcClientId,
      oidcSecret,
      onSave,
      protocol,
      spAcsUrl,
    ],
  );

  const handleDelete = React.useCallback(async () => {
    if (!canManage || busy) return;
    setPhase({ status: "deleting" });
    try {
      await onDelete();
      setPhase({ status: "idle" });
    } catch (err) {
      setPhase({
        status: "error",
        message:
          friendlyErrorMessage(err, "Couldn't delete the SSO connection. Please try again."),
      });
    }
  }, [busy, canManage, onDelete]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Identity provider</CardTitle>
        <CardDescription>
          Connect your workspace to a SAML or OIDC identity provider so members
          sign in through your IdP. Certificates and secrets are stored encrypted
          and never shown again.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <fieldset disabled={!canManage || busy} className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="sso-protocol">Protocol</Label>
                <Select
                  id="sso-protocol"
                  value={protocol}
                  onChange={(e) => setProtocol(e.target.value as SsoProtocol)}
                >
                  <option value="saml">SAML 2.0</option>
                  <option value="oidc">OIDC</option>
                </Select>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="checkbox"
                    className="size-4 rounded border-input accent-primary"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  Enable single sign-on
                </label>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="sso-entity-id">IdP entity ID</Label>
              <Input
                id="sso-entity-id"
                value={idpEntityId}
                placeholder="https://idp.example.com/entity"
                onChange={(e) => setIdpEntityId(e.target.value)}
                autoComplete="off"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="sso-sso-url">IdP SSO URL</Label>
              <Input
                id="sso-sso-url"
                value={idpSsoUrl}
                placeholder="https://idp.example.com/sso"
                onChange={(e) => setIdpSsoUrl(e.target.value)}
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                Where we redirect members to authenticate (the IdP&apos;s
                single-sign-on endpoint).
              </p>
            </div>

            {saml ? (
              <div className="space-y-2">
                <Label htmlFor="sso-cert">
                  IdP signing certificate (X.509 PEM)
                </Label>
                <Textarea
                  id="sso-cert"
                  value={idpCert}
                  rows={5}
                  placeholder={
                    connection?.has_certificate
                      ? "A certificate is configured. Paste a new one to replace it."
                      : "-----BEGIN CERTIFICATE-----\n…\n-----END CERTIFICATE-----"
                  }
                  onChange={(e) => setIdpCert(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  className="font-mono text-xs"
                />
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {connection?.has_certificate ? (
                    <>
                      <CheckCircle2 className="size-3.5 text-success" aria-hidden />
                      A certificate is stored. It is never displayed — paste a new
                      one only to rotate it.
                    </>
                  ) : (
                    "Used to verify the IdP&apos;s signature on SAML assertions."
                  )}
                </p>
                {willClearCert && (
                  <p
                    role="alert"
                    className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs"
                  >
                    <ShieldAlert
                      className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
                      aria-hidden
                    />
                    Saving without a certificate will remove the stored one and
                    break SSO. Re-paste the certificate to keep it.
                  </p>
                )}
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="sso-oidc-client-id">OIDC client ID</Label>
                  <Input
                    id="sso-oidc-client-id"
                    value={oidcClientId}
                    placeholder="acme-workspace"
                    onChange={(e) => setOidcClientId(e.target.value)}
                    autoComplete="off"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="sso-oidc-secret">OIDC client secret</Label>
                  <Input
                    id="sso-oidc-secret"
                    type="password"
                    value={oidcSecret}
                    placeholder={
                      connection?.has_client_secret
                        ? "A secret is configured. Enter a new one to replace it."
                        : "Client secret from your IdP"
                    }
                    onChange={(e) => setOidcSecret(e.target.value)}
                    autoComplete="off"
                  />
                  <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    {connection?.has_client_secret ? (
                      <>
                        <CheckCircle2
                          className="size-3.5 text-success"
                          aria-hidden
                        />
                        A secret is stored. It is never displayed — enter a new one
                        only to rotate it.
                      </>
                    ) : (
                      "Stored encrypted; never shown again."
                    )}
                  </p>
                  {willClearSecret && (
                    <p
                      role="alert"
                      className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs"
                    >
                      <ShieldAlert
                        className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
                        aria-hidden
                      />
                      Saving without a secret will remove the stored one and break
                      SSO. Re-enter the secret to keep it.
                    </p>
                  )}
                </div>
              </>
            )}
          </fieldset>

          {/* Give-the-IdP details — read-only, safe to display. */}
          <div className="space-y-3 rounded-lg border border-border bg-secondary/20 p-4">
            <p className="text-sm font-medium">Give these to your IdP</p>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">
                ACS URL (Assertion Consumer Service)
              </Label>
              <CopyBox value={spAcsUrl} label="Copy ACS URL" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">
                SP metadata URL
              </Label>
              <CopyBox value={metadataUrl} label="Copy metadata URL" />
            </div>
          </div>

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
              SSO connection saved.
            </p>
          )}

          {canManage && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Button type="submit" disabled={busy}>
                {phase.status === "saving" ? (
                  <>
                    <Loader2 className="animate-spin" /> Saving…
                  </>
                ) : (
                  "Save connection"
                )}
              </Button>
              {connection && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleDelete}
                  disabled={busy}
                  className="text-destructive hover:text-destructive"
                >
                  {phase.status === "deleting" ? (
                    <>
                      <Loader2 className="animate-spin" /> Removing…
                    </>
                  ) : (
                    <>
                      <Trash2 className="size-4" aria-hidden /> Remove SSO
                    </>
                  )}
                </Button>
              )}
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
