/**
 * LaunchStatusBanner — a compact, reusable banner that explains WHY a
 * launch-gated action (checkout / publishing / signup) is currently blocked.
 *
 * Drop it above a gated CTA (e.g. the wallet top-up or publish button). When
 * the relevant feature is open it renders nothing, so callers can mount it
 * unconditionally. Tapping it routes to the full /account/launch-status screen
 * for the complete gate breakdown.
 *
 * Server-owned: the same gates are enforced by the API (HTTP 403) regardless of
 * what this renders — this is presentation only, never authorization.
 *
 * No emoji. Explicit types. Immutable props.
 */

import { StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { router } from "expo-router";

import { colors } from "@/components/me/theme";
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";
import type { LaunchFeatures, LaunchStatus } from "@/lib/types";
import { isRouteAvailable } from "@/src/shared/release/surface";

/** Which gate this banner is guarding. */
export type LaunchGate = keyof LaunchFeatures;

export interface LaunchStatusBannerProps {
  /** The loaded launch status, or null while it is still loading. */
  status: LaunchStatus | null;
  /** The gate this banner guards; the banner hides when that gate is open. */
  gate: LaunchGate;
  /** Hide the "View launch status" affordance (e.g. when already on that screen). */
  hideLink?: boolean;
}

const GATE_COPY: Record<LaunchGate, { title: string; body: string }> = {
  checkout: {
    title: "Checkout is not open yet",
    body: "Paid top-ups and plan upgrades are disabled during the current launch phase. You can keep using the credits already on your account.",
  },
  publishing: {
    title: "Direct publishing is not open yet",
    body: "Publishing straight to your connected social accounts is disabled for this launch phase. You can still render and download your videos.",
  },
  signup: {
    title: "Sign-up is not open yet",
    body: "New account creation is limited during the current launch phase.",
  },
};

export function LaunchStatusBanner({
  status,
  gate,
  hideLink = false,
}: LaunchStatusBannerProps): React.JSX.Element | null {
  // Until we know the status, or once the gate is open, render nothing so the
  // banner never blocks or flickers over a working CTA.
  if (!status || status.features[gate]) return null;

  const copy = GATE_COPY[gate];

  return (
    <View style={styles.banner} accessibilityRole="alert">
      <Text style={styles.title}>{copy.title}</Text>
      <Text style={styles.body}>{copy.body}</Text>
      {hideLink || !isRouteAvailable("/account/launch-status") ? null : (
        <TouchableOpacity
          accessibilityRole="button"
          onPress={() => router.push("/account/launch-status")}
          hitSlop={8}
        >
          <Text style={styles.link}>View launch status</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
  },
  body: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 18,
  },
  link: {
    color: colors.accent,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
    marginTop: spacing.xs,
  },
});
