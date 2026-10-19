/**
 * "Share this reel" section for the job screen. The creator mints a public,
 * REVOCABLE share link for their OWN finished reel (POST /jobs/{id}/share —
 * owner-scoped + idempotent, so one live link per reel), copies the link, and can
 * revoke it (DELETE /me/shares/{token}). The public page the link points at is
 * UNAUTHENTICATED and only ever exposes SAFE fields (title, WATERMARKED preview,
 * referral code) — never the clean result key or any private financial — so
 * nothing sensitive is surfaced here either: the owner-facing {@link ShareLink}
 * carries only owner-safe metadata (token, url, view_count).
 *
 * The parent owns nothing beyond wiring the reel's `jobId` + auth `token`; this
 * component owns the create/revoke lifecycle. Nothing is created until the creator
 * opts in.
 */

import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { createShareLink, revokeShareLink } from "@/lib/api";
import type { ShareLink } from "@/lib/types";
import { colors } from "@/components/me/theme";
import { describeError } from "@/components/me/errors";
import { CopyableField } from "@/components/social/CopyableField";
import { useRevenueCat } from "@/src/shared/billing";

export interface ShareReelSectionProps {
  /** The caller's OWN finished reel to mint a public share link for. */
  jobId: string;
  /** Signed-in user's API key (x-api-key); required — sharing is owner-scoped. */
  token?: string;
}

type ShareState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; link: ShareLink };

export function ShareReelSection({
  jobId,
  token,
}: Readonly<ShareReelSectionProps>) {
  const { requireProExport } = useRevenueCat();
  const [state, setState] = useState<ShareState>({ status: "idle" });
  const [revoking, setRevoking] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const createLink = useCallback(async () => {
    setState({ status: "loading" });
    setNotice(null);
    try {
      const access = await requireProExport();
      if (!access.allowed) {
        setState({ status: "error", message: access.snapshot.message });
        return;
      }
      const link = await createShareLink(jobId, { token });
      setState({ status: "ready", link });
    } catch (err) {
      setState({
        status: "error",
        message: describeError(err, "Couldn't create a share link. Try again."),
      });
    }
  }, [jobId, requireProExport, token]);

  const share = useCallback(async () => {
    if (state.status !== "ready" || sharing) return;
    if (!/^https?:\/\//i.test(state.link.url)) {
      setNotice(
        "Public sharing is not configured. Set the backend share base URL.",
      );
      return;
    }

    setSharing(true);
    setNotice(null);
    try {
      await Share.share({
        title: "Share finished video",
        message: `Watch my video: ${state.link.url}`,
        url: state.link.url,
      });
    } catch (err) {
      setNotice(describeError(err, "Couldn't open sharing. Try again."));
    } finally {
      setSharing(false);
    }
  }, [sharing, state]);

  const revoke = useCallback(async () => {
    if (state.status !== "ready" || revoking) return;
    setRevoking(true);
    setNotice(null);
    try {
      const result = await revokeShareLink(state.link.token, { token });
      setState({ status: "idle" });
      setNotice(
        result.revoked
          ? "Share link revoked — the public page no longer works."
          : "This link was already revoked.",
      );
    } catch (err) {
      setNotice(describeError(err, "Couldn't revoke the link. Try again."));
    } finally {
      setRevoking(false);
    }
  }, [state, revoking, token]);

  const busy = state.status === "loading";

  return (
    <View style={styles.container}>
      <Text style={styles.subtitle}>
        Mint a public link to this reel. The public page shows a watermarked
        preview only — never your clean download. You can revoke it anytime.
      </Text>

      {state.status !== "ready" ? (
        <Pressable
          style={[styles.action, busy && styles.disabled]}
          onPress={() => void createLink()}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Create a public share link for this reel"
          accessibilityState={{ disabled: busy }}
        >
          {busy ? (
            <ActivityIndicator color={colors.accent} />
          ) : (
            <Text style={styles.actionText}>Create share link</Text>
          )}
        </Pressable>
      ) : null}

      {state.status === "error" ? (
        <Text style={styles.error}>{state.message}</Text>
      ) : null}

      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      {state.status === "ready" ? (
        <View style={styles.results}>
          <CopyableField
            label="Share link"
            value={state.link.url}
            emptyText="No link"
          />
          <Text style={styles.meta}>
            {state.link.view_count} view
            {state.link.view_count === 1 ? "" : "s"}
          </Text>

          <Pressable
            style={[styles.share, sharing && styles.disabled]}
            onPress={() => void share()}
            disabled={sharing}
            accessibilityRole="button"
            accessibilityLabel="Share this public reel link"
            accessibilityState={{ disabled: sharing, busy: sharing }}
          >
            {sharing ? (
              <ActivityIndicator color={colors.bg} />
            ) : (
              <Text style={styles.shareText}>Share link</Text>
            )}
          </Pressable>

          <Pressable
            style={[styles.revoke, revoking && styles.disabled]}
            onPress={() => void revoke()}
            disabled={revoking}
            accessibilityRole="button"
            accessibilityLabel="Revoke this share link"
            accessibilityState={{ disabled: revoking }}
          >
            {revoking ? (
              <ActivityIndicator color={colors.error} />
            ) : (
              <Text style={styles.revokeText}>Revoke link</Text>
            )}
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10, marginTop: 8 },
  subtitle: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  action: {
    backgroundColor: colors.card,
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  actionText: { color: colors.accent, fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  error: { color: colors.error, fontSize: 14 },
  notice: { color: colors.muted, fontSize: 13 },
  results: { gap: 10, marginTop: 2 },
  meta: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  share: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 13,
    alignItems: "center",
  },
  shareText: { color: colors.bg, fontSize: 14, fontWeight: "800" },
  revoke: {
    backgroundColor: colors.card,
    borderColor: colors.error,
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 2,
  },
  revokeText: { color: colors.error, fontSize: 14, fontWeight: "700" },
});
