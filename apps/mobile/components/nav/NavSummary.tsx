/**
 * NavSummary — the live activity strip at the top of the navigation hub.
 * Renders credits, active jobs and unread notifications as StatTiles, each
 * tappable to jump to the relevant surface. Shows a loading skeleton on first
 * load and a compact error with retry when every signal failed.
 */

import { Pressable, StyleSheet, View } from "react-native";

import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Loading";
import { StatTile } from "@/components/ui/StatTile";
import { spacing } from "@/src/shared/theme";
import type { NavHubState } from "@/lib/nav/useNavHubData";

export interface NavSummaryProps {
  state: NavHubState;
  onOpen: (route: string) => void;
}

function tileValue(n: number | undefined): string {
  return typeof n === "number" ? String(n) : "—";
}

export function NavSummary({ state, onOpen }: NavSummaryProps): React.JSX.Element {
  const { data, loading, error, reload } = state;

  if (loading) {
    return (
      <View style={styles.row}>
        <Skeleton height={64} style={styles.skeleton} />
        <Skeleton height={64} style={styles.skeleton} />
        <Skeleton height={64} style={styles.skeleton} />
      </View>
    );
  }

  if (error) {
    return <ErrorState message={error} onRetry={reload} retryLabel="Retry" />;
  }

  return (
    <View style={styles.row}>
      <Pressable style={styles.cell} onPress={() => onOpen("/wallet")}>
        <StatTile label="Credits" value={tileValue(data.credits)} subLabel="Wallet" />
      </Pressable>
      <Pressable style={styles.cell} onPress={() => onOpen("/jobs/reels/tasks")}>
        <StatTile
          label="Active jobs"
          value={tileValue(data.activeJobs)}
          subLabel="Queue"
        />
      </Pressable>
      <Pressable style={styles.cell} onPress={() => onOpen("/notifications")}>
        <StatTile label="Unread" value={tileValue(data.unread)} subLabel="Alerts" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.sm },
  cell: { flex: 1 },
  skeleton: { flex: 1, borderRadius: 10 },
});
