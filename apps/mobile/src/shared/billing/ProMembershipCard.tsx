import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  type EntitlementSnapshot,
  type EntitlementStatus,
} from "./entitlement-policy";
import { useRevenueCat } from "./RevenueCatProvider";
import { SubscriptionDisclosure } from "@/src/shared/legal";

type Action = "manage" | "refresh" | "restore" | "upgrade";

const STATUS_LABEL: Record<EntitlementStatus, string> = {
  active: "ACTIVE",
  inactive: "REQUIRED",
  loading: "CHECKING",
  stale: "REFRESH",
  error: "UNAVAILABLE",
  signed_out: "SIGN IN",
  unconfigured: "UNAVAILABLE",
};

function detail(snapshot: EntitlementSnapshot): string {
  if (snapshot.status === "active" && snapshot.expiresAtMs !== null) {
    return `Renews or expires ${new Date(snapshot.expiresAtMs).toLocaleDateString()}`;
  }
  if (snapshot.status === "active") return "No expiration date reported";
  return snapshot.message;
}

export function ProMembershipCard() {
  const {
    snapshot,
    presentCustomerCenter,
    presentPaywall,
    refresh,
    restore,
  } = useRevenueCat();
  const [action, setAction] = useState<Action | null>(null);
  const active = snapshot.status === "active";
  const unavailable =
    snapshot.status === "unconfigured" || snapshot.status === "signed_out";

  const run = async (next: Action, operation: () => Promise<unknown>) => {
    setAction(next);
    try {
      await operation();
    } finally {
      setAction(null);
    }
  };

  return (
    <View style={styles.card} accessibilityRole="summary">
      <View style={styles.header}>
        <Text style={styles.product}>Menivor Pro</Text>
      </View>

      <Text style={[styles.status, active && styles.statusActive]}>
        {STATUS_LABEL[snapshot.status]}
      </Text>
      <Text style={styles.detail}>{detail(snapshot)}</Text>

      <View style={styles.actions}>
        {active ? (
          <MembershipButton
            label="Manage subscription"
            busy={action === "manage"}
            disabled={action !== null}
            primary
            onPress={() => void run("manage", presentCustomerCenter)}
          />
        ) : (
          <MembershipButton
            label="Upgrade"
            busy={action === "upgrade"}
            disabled={unavailable || action !== null}
            primary
            onPress={() => void run("upgrade", presentPaywall)}
          />
        )}
        <MembershipButton
          label="Restore purchases"
          busy={action === "restore"}
          disabled={unavailable || action !== null}
          onPress={() => void run("restore", restore)}
        />
        <MembershipButton
          label="Refresh"
          busy={action === "refresh"}
          disabled={unavailable || action !== null}
          onPress={() => void run("refresh", refresh)}
        />
      </View>

      {active ? null : (
        <SubscriptionDisclosure textColor="#8f8b82" linkTint="#E6C76A" />
      )}
    </View>
  );
}

function MembershipButton({
  label,
  busy,
  disabled,
  primary = false,
  onPress,
}: {
  label: string;
  busy: boolean;
  disabled: boolean;
  primary?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ busy, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        primary && styles.buttonPrimary,
        disabled && styles.buttonDisabled,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={primary ? "#ffffff" : "#002fa7"} />
      ) : (
        <Text style={[styles.buttonText, primary && styles.buttonTextPrimary]}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    padding: 18,
    marginBottom: 28,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottomColor: "#27272a",
    borderBottomWidth: 1,
    paddingBottom: 10,
  },
  product: {
    color: "#ece9e1",
    fontFamily: "Helvetica Neue",
    fontSize: 14,
    fontWeight: "700",
  },
  entitlement: {
    color: "#9b978d",
    fontFamily: "Helvetica Neue",
    fontSize: 11,
  },
  status: {
    color: "#ece9e1",
    fontFamily: "Helvetica Neue",
    fontSize: 38,
    fontWeight: "700",
    letterSpacing: -1.4,
    marginTop: 22,
  },
  statusActive: { color: "#E6C76A" },
  detail: {
    color: "#9b978d",
    fontFamily: "Helvetica Neue",
    fontSize: 12,
    lineHeight: 18,
    marginTop: 6,
  },
  actions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 22,
    paddingTop: 12,
    borderTopColor: "#27272a",
    borderTopWidth: 1,
  },
  button: {
    minHeight: 40,
    justifyContent: "center",
    paddingHorizontal: 13,
    backgroundColor: "#1b1b1d",
    borderColor: "#27272a",
    borderWidth: 1,
  },
  buttonPrimary: { backgroundColor: "#E6C76A" },
  buttonDisabled: { opacity: 0.42 },
  buttonText: {
    color: "#ece9e1",
    fontFamily: "Helvetica Neue",
    fontSize: 12,
    fontWeight: "700",
  },
  buttonTextPrimary: { color: "#0f0f10" },
});
