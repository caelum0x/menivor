/**
 * Root stack `screenLayout`: decides access BEFORE a screen mounts, so a
 * blocked screen never renders or fires its effects (API calls included).
 *
 * - Internal screens (labs, admin, developer keys, Mint token transfers,
 *   marketplaces) redirect to Create, or to sign-in when signed out. They are
 *   unreachable from a store build, by deep link or stale menu row alike.
 * - Creator screens redirect to sign-in when there is no account: Menivor is
 *   signup-first, with no guest use.
 * See ./route-access for the decision table.
 */
import type { ReactElement } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Redirect } from "expo-router";

import { useSession } from "@/src/shared/auth";
import { colors } from "@/src/shared/theme";

import { routeAccess } from "./route-access";

interface RouteGateProps {
  /** expo-router route name, e.g. "job/[id]", "wallet/index", "(tabs)". */
  routeName: string;
  children: ReactElement;
}

export function RouteGate({ routeName, children }: RouteGateProps): ReactElement {
  const { apiKey, loading } = useSession();
  const signedIn = Boolean(apiKey);
  const decision = routeAccess(routeName, { signedIn, authLoading: loading });

  if (decision === "internal") {
    return <Redirect href={signedIn ? "/(tabs)/create" : "/"} />;
  }
  if (decision === "signin") return <Redirect href="/" />;
  if (decision === "wait") {
    return (
      <View style={styles.wait}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }
  return children;
}

/** `screenLayout` adapter for the root Stack. */
export function gateScreen({
  route,
  children,
}: {
  route: { name: string };
  children: ReactElement;
}): ReactElement {
  return <RouteGate routeName={route.name}>{children}</RouteGate>;
}

const styles = StyleSheet.create({
  wait: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg },
});
