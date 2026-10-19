"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/components/auth/clerk-safe";
import { AlertTriangle, CheckCircle2, Loader2, Users } from "lucide-react";
import { ApiError, acceptInvite, getInvite, type InvitePreview } from "@/lib/api";
import { signInHref, signUpHref } from "@/lib/auth-redirect";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AppTopBar } from "@/components/app-shell/AppTopBar";
import { roleLabel } from "@/components/team/roles";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

type LoadState = "loading" | "ready" | "error";

const STATUS_COPY: Record<string, string> = {
  accepted: "This invite has already been used.",
  revoked: "This invite was withdrawn by the workspace admin.",
  expired: "This invite has expired. Ask the workspace admin for a new link.",
};

function messageOf(err: unknown, fallback: string): string {
  return friendlyErrorMessage(err, fallback);
}

/**
 * Accept a workspace invite link (`/invite/{token}`). Shows what the invite
 * grants (public preview), asks the visitor to sign in or create an account
 * with the invited email, then joins them (POST /invites/{token}/accept) and
 * opens the workspace page.
 */
export function AcceptInvitePage() {
  const params = useParams<{ token: string }>();
  const token = typeof params.token === "string" ? params.token : "";
  const router = useRouter();
  const { isLoaded, isSignedIn } = useAuth();
  const getApiToken = useApiToken();

  const [status, setStatus] = React.useState<LoadState>("loading");
  const [preview, setPreview] = React.useState<InvitePreview | null>(null);
  const [loadError, setLoadError] = React.useState("");
  const [accepting, setAccepting] = React.useState(false);
  const [acceptError, setAcceptError] = React.useState("");
  const [joined, setJoined] = React.useState(false);

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      try {
        const data = await getInvite(token);
        if (cancelled) return;
        setPreview(data);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof ApiError && err.status === 404
            ? "This invite link is not valid. Check that you copied the whole link."
            : messageOf(err, "Couldn't load this invite."),
        );
        setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const returnPath = `/invite/${encodeURIComponent(token)}`;

  const onAccept = async () => {
    setAccepting(true);
    setAcceptError("");
    try {
      const apiToken = await getApiToken();
      await acceptInvite(token, { token: apiToken });
      setJoined(true);
      window.setTimeout(() => router.push("/workspace"), 1200);
    } catch (err) {
      setAcceptError(
        err instanceof ApiError && err.status === 403
          ? `This invite was sent to ${preview?.email ?? "a different email"}. Sign in with that address to accept it.`
          : messageOf(err, "Couldn't accept this invite."),
      );
    } finally {
      setAccepting(false);
    }
  };

  const closed = preview && preview.status !== "pending";

  return (
    <main className="min-h-dvh">
      <AppTopBar />
      <section className="container flex justify-center py-16">
        <Card className="w-full max-w-md">
          <CardContent className="space-y-5 py-8 text-center">
            <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10">
              <Users className="size-6 text-primary" aria-hidden />
            </span>

            {status === "loading" && (
              <p className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" aria-hidden /> Checking your invite
              </p>
            )}

            {status === "error" && (
              <div className="space-y-3">
                <p className="flex items-center justify-center gap-2 font-medium">
                  <AlertTriangle className="size-4 text-destructive" aria-hidden /> Invite unavailable
                </p>
                <p className="text-sm text-muted-foreground">{loadError}</p>
                <Button asChild variant="outline">
                  <Link href="/workspace">Go to workspaces</Link>
                </Button>
              </div>
            )}

            {status === "ready" && preview && (
              <>
                <div className="space-y-1">
                  <h1 className="text-xl font-semibold">
                    Join {preview.workspace_name || "a Menivor workspace"}
                  </h1>
                  <p className="text-sm text-muted-foreground">
                    {preview.invited_by ? `${preview.invited_by} invited you` : "You're invited"} as{" "}
                    {roleLabel(preview.role)}
                    {preview.email ? ` (${preview.email})` : ""}.
                  </p>
                </div>

                {closed && (
                  <div className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      {STATUS_COPY[preview.status] ?? "This invite can no longer be used."}
                    </p>
                    <Button asChild variant="outline">
                      <Link href="/workspace">Go to workspaces</Link>
                    </Button>
                  </div>
                )}

                {!closed && joined && (
                  <p className="flex items-center justify-center gap-2 text-sm font-medium">
                    <CheckCircle2 className="size-4 text-success" aria-hidden /> You joined the
                    workspace. Opening it now.
                  </p>
                )}

                {!closed && !joined && isLoaded && !isSignedIn && (
                  <div className="space-y-3">
                    <p className="text-sm text-muted-foreground">
                      Sign in or create a free account with the invited email address to join.
                    </p>
                    <div className="flex flex-wrap justify-center gap-2">
                      <Button asChild>
                        <Link href={signUpHref(returnPath)}>Create account</Link>
                      </Button>
                      <Button asChild variant="outline">
                        <Link href={signInHref(returnPath)}>Sign in</Link>
                      </Button>
                    </div>
                  </div>
                )}

                {!closed && !joined && isLoaded && isSignedIn && (
                  <div className="space-y-3">
                    <Button onClick={() => void onAccept()} disabled={accepting} className="w-full">
                      {accepting && <Loader2 className="size-4 animate-spin" aria-hidden />}
                      Accept and join
                    </Button>
                    {acceptError && (
                      <p className="text-sm text-destructive" role="alert">
                        {acceptError}
                      </p>
                    )}
                  </div>
                )}

                {!isLoaded && !closed && (
                  <Loader2 className="mx-auto size-4 animate-spin text-muted-foreground" aria-label="Loading" />
                )}
              </>
            )}
          </CardContent>
        </Card>
      </section>
    </main>
  );
}
