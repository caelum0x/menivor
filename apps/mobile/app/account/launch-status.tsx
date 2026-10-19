/**
 * Launch Status (account cluster).
 *
 * A dedicated, user-facing surface for the server-owned launch gates returned
 * by GET /launch/status. Elsewhere in the app these gates silently block paid
 * checkout, plan upgrades, and direct social publishing (the server rejects the
 * call with HTTP 403). This screen makes that state legible: it shows the
 * current launch phase and, feature by feature, what is open vs. still gated —
 * so a gated user understands WHY checkout/publish is unavailable instead of
 * hitting an opaque error.
 *
 * Data: GET /launch/status via `useLaunchStatus` (sent as `x-api-key`). The
 * document is non-sensitive by contract — no secrets are rendered here. This is
 * presentation only; it never grants access.
 *
 * Reuses the shared UI kit (Screen / Card / Badge / Button / Loading /
 * ErrorState) and the editorial theme. No emoji.
 *
 * NAV MANIFEST: { route: "/account/launch-status", title: "Launch Status",
 *   subtitle: "See which features are open in the current launch phase",
 *   group: "Settings", cluster: "account" }
 */

import * as React from "react";
import { StyleSheet, Text, View } from "react-native";

import { Stack, router } from "expo-router";

import {
  Badge,
  Button,
  Card,
  ErrorState,
  Loading,
  Screen,
  type BadgeVariant,
} from "@/components/ui";
import { colors } from "@/components/me/theme";
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";
import { useSession } from "@/src/shared/auth";
import { useLaunchStatus } from "@/src/shared/hooks";
import type { LaunchFeatures, LaunchStatus } from "@/lib/types";

interface FeatureRowSpec {
  key: keyof LaunchFeatures;
  title: string;
  description: string;
}

/** The gated features, in the order they matter most to a paying user. */
const FEATURE_ROWS: readonly FeatureRowSpec[] = [
  {
    key: "checkout",
    title: "Checkout & top-ups",
    description: "Buy credits or upgrade your plan.",
  },
  {
    key: "publishing",
    title: "Direct publishing",
    description: "Publish straight to connected social accounts.",
  },
  {
    key: "signup",
    title: "New sign-ups",
    description: "Create brand-new device accounts.",
  },
] as const;

function modeLabel(status: LaunchStatus): string {
  switch (status.mode) {
    case "public":
      return "Public launch";
    case "internal_pilot":
      return "Internal pilot";
    default:
      return status.mode;
  }
}

export default function LaunchStatusScreen(): React.JSX.Element {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const { status, loading, refreshing, error, refresh } = useLaunchStatus(token);

  const anyGated = React.useMemo<boolean>(() => {
    if (!status) return false;
    return FEATURE_ROWS.some((row) => !status.features[row.key]);
  }, [status]);

  return (
    <Screen scroll refreshing={refreshing} onRefresh={refresh}>
      <Stack.Screen options={{ title: "Launch Status" }} />

      {loading && !status ? (
        <Loading label="Checking launch status..." size="large" />
      ) : error && !status ? (
        <ErrorState message={error} onRetry={refresh} />
      ) : status ? (
        <View style={styles.stack}>
          {/* Phase summary */}
          <Card highlighted={!status.public_access}>
            <View style={styles.phaseHeader}>
              <Text style={styles.phaseLabel}>Current phase</Text>
              <Badge
                label={modeLabel(status)}
                variant={status.public_access ? "success" : "accent"}
              />
            </View>
            <Text style={styles.phaseBody}>
              {status.public_access
                ? "The product is in full public access. All features below are open."
                : "The product is in a limited launch phase. Some paid and publishing features are gated until public launch."}
            </Text>
          </Card>

          {/* Per-feature gate breakdown */}
          <Text style={styles.sectionTitle}>Feature access</Text>
          <View style={styles.list}>
            {FEATURE_ROWS.map((row, index) => (
              <FeatureRow
                key={row.key}
                spec={row}
                open={status.features[row.key]}
                isLast={index === FEATURE_ROWS.length - 1}
              />
            ))}
          </View>

          {/* Contextual guidance when something is gated */}
          {anyGated ? (
            <Card compact>
              <Text style={styles.helpTitle}>Why is this blocked?</Text>
              <Text style={styles.helpBody}>
                These gates are set by the team for the current launch phase, not
                by your account. Credits already on your account keep working, and
                you can still render and download videos. Access opens up as the
                product moves toward public launch.
              </Text>
              <View style={styles.actions}>
                {!status.features.signup ? (
                  <Button
                    label="Join the waitlist"
                    variant="primary"
                    size="sm"
                    onPress={() => router.push("/waitlist")}
                  />
                ) : null}
                <Button
                  label="Contact support"
                  variant="secondary"
                  size="sm"
                  onPress={() => router.push("/support")}
                />
              </View>
            </Card>
          ) : (
            <Text style={styles.footnote}>
              Everything is open in this phase. Pull down to refresh if that
              changes.
            </Text>
          )}

          {/* A non-blocking refresh error keeps the last-known status visible. */}
          {error ? (
            <Text style={styles.refreshError}>
              Could not refresh: {error}
            </Text>
          ) : null}
        </View>
      ) : (
        <ErrorState message="No launch status is available." onRetry={refresh} />
      )}
    </Screen>
  );
}

interface FeatureRowProps {
  spec: FeatureRowSpec;
  open: boolean;
  isLast: boolean;
}

function FeatureRow({ spec, open, isLast }: FeatureRowProps): React.JSX.Element {
  const variant: BadgeVariant = open ? "success" : "neutral";
  return (
    <View style={[styles.row, isLast && styles.rowLast]}>
      <View style={styles.rowText}>
        <Text style={styles.rowTitle}>{spec.title}</Text>
        <Text style={styles.rowDesc}>{spec.description}</Text>
      </View>
      <Badge label={open ? "Open" : "Gated"} variant={variant} />
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    gap: spacing.lg,
  },
  phaseHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  phaseLabel: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: weight.semibold,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  phaseBody: {
    color: colors.textPrimary,
    fontSize: typeScale.body,
    lineHeight: 21,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    fontWeight: weight.bold,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: -spacing.xs,
  },
  list: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowLast: {
    borderBottomWidth: 0,
  },
  rowText: {
    flex: 1,
    gap: 2,
  },
  rowTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.semibold,
  },
  rowDesc: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 17,
  },
  helpTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: weight.bold,
  },
  helpBody: {
    color: colors.textSecondary,
    fontSize: typeScale.caption,
    lineHeight: 19,
  },
  actions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  footnote: {
    color: colors.muted,
    fontSize: typeScale.caption,
    textAlign: "center",
  },
  refreshError: {
    color: colors.error,
    fontSize: typeScale.caption,
  },
});
