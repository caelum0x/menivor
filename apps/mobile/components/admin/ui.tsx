/**
 * Shared presentational pieces + formatters for the platform-admin screens.
 * Keeps each screen small and consistent: a full-screen loading / empty / error
 * / forbidden state machine, a labelled card row, a key/value line, a status
 * badge, and a few pure formatters. Purely presentational — no data access.
 */

import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { JobState } from "@/lib/types";

/** Format an ISO-8601 timestamp as a short, locale-readable date-time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Format integer minor units (cents) as a USD amount (e.g. 12345 -> "$123.45"). */
export function formatCents(cents: number): string {
  if (!Number.isFinite(cents)) return "$0.00";
  return (cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
  });
}

/** Format an integer count with locale grouping (e.g. 1234 -> "1,234"). */
export function formatCount(value: number): string {
  if (!Number.isFinite(value)) return "0";
  return Math.round(value).toLocaleString("en-US");
}

/** Human label for a backend integer job state (with a queued/processing split). */
export function jobStateLabel(
  state: number | null | undefined,
  progress: number | null | undefined,
): string {
  if (state === JobState.Failed) return "Failed";
  if (state === JobState.Complete) return "Complete";
  if (state === JobState.Processing) {
    return (progress ?? 0) > 0 ? "Processing" : "Queued";
  }
  if (state === null || state === undefined) return "Unknown";
  return "Queued";
}

/** Retention-window label — a `null` day-count reads as "keep forever". */
export function retentionLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return "Keep forever";
  if (days === 0) return "Immediate";
  return `${days.toLocaleString("en-US")} day${days === 1 ? "" : "s"}`;
}

type BadgeTone = "neutral" | "success" | "warning" | "danger";

interface BadgeProps {
  label: string;
  tone?: BadgeTone;
}

/** A compact status pill. */
export function Badge({ label, tone = "neutral" }: BadgeProps) {
  const toneStyle =
    tone === "success"
      ? styles.badgeSuccess
      : tone === "warning"
        ? styles.badgeWarning
        : tone === "danger"
          ? styles.badgeDanger
          : styles.badgeNeutral;
  const textStyle =
    tone === "success"
      ? styles.badgeSuccessText
      : tone === "warning"
        ? styles.badgeWarningText
        : tone === "danger"
          ? styles.badgeDangerText
          : styles.badgeNeutralText;
  return (
    <View style={[styles.badge, toneStyle]}>
      <Text style={[styles.badgeText, textStyle]}>{label}</Text>
    </View>
  );
}

interface KeyValueProps {
  label: string;
  value: string;
}

/** A single label/value line inside a card. */
export function KeyValue({ label, value }: KeyValueProps) {
  return (
    <View style={styles.kv}>
      <Text style={styles.kvLabel}>{label}</Text>
      <Text style={styles.kvValue} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

interface CardProps {
  children: ReactNode;
}

/** The standard bordered card container used across the admin screens. */
export function Card({ children }: CardProps) {
  return <View style={styles.card}>{children}</View>;
}

interface AdminListStateProps {
  /** True while the first page is loading (nothing to show yet). */
  loading: boolean;
  /** Error message, or "" when there is no error. */
  error: string;
  /** True once loaded and the list is empty. */
  empty: boolean;
  emptyTitle: string;
  emptyHint?: string;
  onRetry: () => void;
}

/**
 * A full-width state block for the top of a list: spinner while loading, an
 * inline error with retry, a forbidden (403) hint for non-staff callers, or an
 * empty-state message. Returns `null` when there is content to render.
 */
export function AdminListState({
  loading,
  error,
  empty,
  emptyTitle,
  emptyHint,
  onRetry,
}: AdminListStateProps): ReactNode {
  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  if (error) {
    const forbidden = /403|staff|admin access|not authorized|forbidden/i.test(
      error,
    );
    return (
      <Card>
        <Text style={styles.errorTitle}>
          {forbidden ? "Platform-admin only" : "Could not load"}
        </Text>
        <Text style={styles.errorText}>
          {forbidden
            ? "This surface is restricted to platform staff. Your account does not have access."
            : error}
        </Text>
        {forbidden ? null : (
          <Pressable style={styles.retry} onPress={onRetry}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        )}
      </Card>
    );
  }
  if (empty) {
    return (
      <Card>
        <Text style={styles.emptyTitle}>{emptyTitle}</Text>
        {emptyHint ? <Text style={styles.emptyHint}>{emptyHint}</Text> : null}
      </Card>
    );
  }
  return null;
}

interface LoadMoreFooterProps {
  hasMore: boolean;
  loading: boolean;
  count: number;
  onLoadMore: () => void;
}

/** The footer under a paginated list: a spinner, a "Load more" button, or a tally. */
export function LoadMoreFooter({
  hasMore,
  loading,
  count,
  onLoadMore,
}: LoadMoreFooterProps) {
  if (count === 0) return null;
  if (loading) {
    return (
      <View style={styles.footer}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  if (hasMore) {
    return (
      <Pressable
        style={[styles.footer, styles.loadMore]}
        onPress={onLoadMore}
        accessibilityRole="button"
      >
        <Text style={styles.loadMoreText}>Load more</Text>
      </Pressable>
    );
  }
  return (
    <View style={styles.footer}>
      <Text style={styles.footerTally}>
        {count.toLocaleString("en-US")} shown
      </Text>
    </View>
  );
}

export const adminStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, gap: 12 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
  },
});

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 40 },
  kv: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  kvLabel: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  kvValue: {
    color: colors.textSecondary,
    fontSize: 13,
    flexShrink: 1,
    textAlign: "right",
  },
  badge: {
    alignSelf: "flex-start",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderWidth: 1,
  },
  badgeText: { fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  badgeNeutral: { backgroundColor: colors.cardAlt, borderColor: colors.border },
  badgeNeutralText: { color: colors.textSecondary },
  badgeSuccess: { backgroundColor: "transparent", borderColor: colors.success },
  badgeSuccessText: { color: colors.success },
  badgeWarning: { backgroundColor: "transparent", borderColor: colors.accent },
  badgeWarningText: { color: colors.accent },
  badgeDanger: { backgroundColor: "transparent", borderColor: colors.error },
  badgeDangerText: { color: colors.error },
  errorTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  errorText: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  retry: {
    alignSelf: "flex-start",
    marginTop: 4,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  emptyHint: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  footer: { paddingVertical: 16, alignItems: "center" },
  footerTally: { color: colors.muted, fontSize: 12 },
  loadMore: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 12,
  },
  loadMoreText: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
});
