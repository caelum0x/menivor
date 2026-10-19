/**
 * Small provider-health status badge shared by the model compare, model detail,
 * and provider-health screens. Renders the normalized health state as a colored
 * pill; an optional uptime percentage is appended when known.
 */

import type { ReactElement } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { ProviderHealthState } from "@/lib/marketplace";

const STATE_COLOR: Record<ProviderHealthState, string> = {
  healthy: colors.success,
  degraded: "#fbbf24",
  down: colors.error,
  unknown: colors.muted,
};

const STATE_LABEL: Record<ProviderHealthState, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  down: "Down",
  unknown: "Unknown",
};

interface HealthBadgeProps {
  /** Accepts a raw provider `health_state` string; coerced to a known state. */
  state: ProviderHealthState | string | undefined;
  /** Uptime fraction 0..1; shown as a percentage when finite and > 0 samples. */
  uptime?: number;
  samples?: number;
}

/** Coerce an arbitrary string into a known health state (defaults to unknown). */
export function coerceHealthState(value: string | undefined): ProviderHealthState {
  if (value === "healthy" || value === "degraded" || value === "down") return value;
  return "unknown";
}

export function HealthBadge({ state, uptime, samples }: HealthBadgeProps): ReactElement {
  const resolved = coerceHealthState(state);
  const color = STATE_COLOR[resolved];
  const hasUptime =
    typeof uptime === "number" &&
    Number.isFinite(uptime) &&
    (samples === undefined || samples > 0) &&
    resolved !== "unknown";
  const label = hasUptime
    ? `${STATE_LABEL[resolved]} · ${Math.round((uptime as number) * 100)}%`
    : STATE_LABEL[resolved];

  return (
    <View style={[styles.badge, { borderColor: color }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <Text style={[styles.text, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  dot: { width: 7, height: 7, borderRadius: 999 },
  text: { fontSize: 11, fontWeight: "700" },
});
