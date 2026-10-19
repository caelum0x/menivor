import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useRevenueCat } from "./RevenueCatProvider";
import { SubscriptionDisclosure } from "@/src/shared/legal";

export function ProExportAccess({
  feature = "export",
}: Readonly<{ feature?: "export" | "publishing" }>) {
  const {
    snapshot,
    presentCustomerCenter,
    presentPaywall,
    refresh,
    restore,
  } = useRevenueCat();
  const [action, setAction] = useState<
    "manage" | "upgrade" | "restore" | "refresh" | null
  >(null);

  const run = async (
    nextAction: "manage" | "upgrade" | "restore" | "refresh",
    operation: () => Promise<unknown>,
  ) => {
    setAction(nextAction);
    try {
      await operation();
    } finally {
      setAction(null);
    }
  };

  const active = snapshot.status === "active";
  const unavailable =
    snapshot.status === "unconfigured" || snapshot.status === "signed_out";
  const featureLabel = feature === "publishing" ? "publishing" : "export";

  return (
    <View
      style={[styles.card, active ? styles.activeCard : styles.lockedCard]}
      accessibilityRole="summary"
    >
      <Text style={styles.title}>
        {active
          ? `Pro ${featureLabel} unlocked`
          : `Pro ${featureLabel}`}
      </Text>
      <Text style={styles.message}>{snapshot.message}</Text>

      {active ? (
        <View style={styles.actions}>
          <AccessButton
            label="Manage subscription"
            busy={action === "manage"}
            disabled={action !== null}
            onPress={() => void run("manage", presentCustomerCenter)}
          />
        </View>
      ) : (
        <View style={styles.actions}>
          <AccessButton
            label="Unlock Pro"
            busy={action === "upgrade"}
            disabled={unavailable || action !== null}
            primary
            onPress={() => void run("upgrade", presentPaywall)}
          />
          <AccessButton
            label="Restore"
            busy={action === "restore"}
            disabled={unavailable || action !== null}
            onPress={() => void run("restore", restore)}
          />
          <AccessButton
            label="Refresh"
            busy={action === "refresh"}
            disabled={unavailable || action !== null}
            onPress={() => void run("refresh", refresh)}
          />
        </View>
      )}

      {active ? null : <SubscriptionDisclosure />}
    </View>
  );
}

function AccessButton({
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
      accessibilityState={{ disabled, busy }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        primary && styles.primaryButton,
        disabled && styles.disabled,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={primary ? "#0a0a0b" : "#ffffff"} size="small" />
      ) : (
        <Text style={[styles.buttonText, primary && styles.primaryButtonText]}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 12,
    borderWidth: 1,
    padding: 14,
    marginTop: 16,
  },
  activeCard: { backgroundColor: "#10241f", borderColor: "#2dd4a2" },
  lockedCard: { backgroundColor: "#17151f", borderColor: "#4f466f" },
  title: { color: "#ece9e1", fontSize: 15, fontWeight: "700" },
  message: { color: "#b8b5c8", fontSize: 13, lineHeight: 18, marginTop: 4 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  button: {
    minHeight: 40,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#27272a",
    paddingHorizontal: 13,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButton: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  disabled: { opacity: 0.45 },
  buttonText: { color: "#ece9e1", fontSize: 13, fontWeight: "700" },
  primaryButtonText: { color: "#0a0a0b" },
});
