"use client";

import * as React from "react";
import { AlertCircle, Link2, Loader2, Trash2, X } from "lucide-react";
import { ApiError, createShare, revokeShare } from "@/lib/api";
import type { ShareLink } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/referral/CopyButton";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface ShareDialogProps {
  /** The caller's OWN finished reel to mint a public share link for. */
  jobId: string;
  open: boolean;
  onClose: () => void;
}

type DialogState =
  | { status: "loading" }
  | { status: "ready"; link: ShareLink }
  | { status: "revoked" }
  | { status: "error"; message: string };

/** Map an API/network failure onto a friendly, non-leaky message. */
function shareErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This reel isn't ready to share yet.";
    if (err.status === 401) return "Sign in to share this reel.";
    return friendlyErrorMessage(err);
  }
  if (err instanceof Error) return friendlyErrorMessage(err);
  return "Couldn't create a share link.";
}

/**
 * Owner-only dialog to mint (or reveal the existing) PUBLIC share link for one of
 * the caller's OWN reels, then copy it. Minting is idempotent server-side (one
 * live link per job), so re-opening the dialog surfaces the same link. The
 * revealed `url` points at the PUBLIC watermarked share page (`/r/{token}`); the
 * clean (un-watermarked) result is never exposed here. A "Revoke" action calls
 * DELETE /me/shares/{token} so the link can be turned off at any time.
 *
 * Closes on Escape, backdrop click, or the close button (blocked mid-revoke).
 */
export function ShareDialog({ jobId, open, onClose }: Readonly<ShareDialogProps>) {
  const getToken = useApiToken();
  const [state, setState] = React.useState<DialogState>({ status: "loading" });
  const [revoking, setRevoking] = React.useState(false);

  // Mint / reveal the share link whenever the dialog opens for a reel.
  React.useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let active = true;
    setState({ status: "loading" });
    setRevoking(false);
    void (async () => {
      try {
        const token = await getToken();
        const link = await createShare(jobId, {
          token,
          signal: controller.signal,
        });
        if (active) setState({ status: "ready", link });
      } catch (err) {
        if (controller.signal.aborted || !active) return;
        setState({ status: "error", message: shareErrorMessage(err) });
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, jobId, getToken]);

  const handleClose = React.useCallback(() => {
    if (revoking) return;
    onClose();
  }, [onClose, revoking]);

  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, handleClose]);

  const handleRevoke = React.useCallback(async () => {
    if (state.status !== "ready") return;
    setRevoking(true);
    try {
      const token = await getToken();
      await revokeShare(state.link.token, { token });
      setState({ status: "revoked" });
    } catch (err) {
      setState({ status: "error", message: shareErrorMessage(err) });
    } finally {
      setRevoking(false);
    }
  }, [state, getToken]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="share-dialog-title"
      onClick={handleClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <Link2 className="size-5 text-primary" aria-hidden />
            <h2 id="share-dialog-title" className="text-lg font-semibold">
              Share this reel
            </h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={revoking}
            aria-label="Close"
            className="rounded-md p-1 text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <X className="size-5" aria-hidden />
          </button>
        </div>

        {state.status === "loading" && (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Creating your share link…
          </div>
        )}

        {state.status === "ready" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Anyone with this link can watch a watermarked preview of your reel —
              no account needed. The original video stays private.
            </p>
            <div className="flex items-center gap-2">
              <input
                readOnly
                value={state.link.url}
                aria-label="Public share link"
                onFocus={(event) => event.currentTarget.select()}
                className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <CopyButton value={state.link.url} label="Copy link" />
            </div>
            <div className="flex items-center justify-between border-t border-border/60 pt-4">
              <span className="text-xs text-muted-foreground">
                Changed your mind? You can turn this link off.
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void handleRevoke()}
                disabled={revoking}
                className="text-destructive hover:text-destructive"
              >
                {revoking ? (
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="size-4" aria-hidden />
                )}
                {revoking ? "Revoking…" : "Revoke link"}
              </Button>
            </div>
          </div>
        )}

        {state.status === "revoked" && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              This share link has been revoked. Anyone who opens it now sees a
              &ldquo;not found&rdquo; page.
            </p>
            <Button type="button" size="md" onClick={handleClose}>
              Done
            </Button>
          </div>
        )}

        {state.status === "error" && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{state.message}</span>
          </div>
        )}
      </div>
    </div>
  );
}
