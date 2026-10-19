/**
 * Studio · Caption Studio · Safe Zones
 *
 * Nav manifest: { route: "/studio/captions/safezones", title: "Safe Zones" }
 *
 * Resolve per-platform caption placement (GET /captions/safezones?play_h=…):
 * font size + top margin + vertical fraction for each supported surface at a
 * chosen playback height. Loads on mount, refetches when the height changes,
 * pull-to-refresh, and explicit loading / error / empty states. Each row also
 * renders a proportional preview of where the caption band sits in the frame.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  getSafezones,
  PLAY_HEIGHTS,
  type SafeZone,
  type SafezonesResult,
} from "@/lib/captions";
import { useSession } from "@/src/shared/auth";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { Chips } from "@/components/captions/ui";

interface SurfaceRow {
  surface: string;
  zone: SafeZone;
}

export default function SafezonesScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [playH, setPlayH] = useState<number>(PLAY_HEIGHTS[1].value);
  const [data, setData] = useState<SafezonesResult | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (height: number, mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const res = await getSafezones(height, { token });
        setData(res);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load safe zones."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load(playH, "initial");
  }, [load, playH]);

  const rows: SurfaceRow[] = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.safezones).map(([surface, zone]) => ({ surface, zone }));
  }, [data]);

  const heightOptions = useMemo(
    () => PLAY_HEIGHTS.map((h) => ({ id: h.value, label: h.label })),
    [],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Where captions sit for each platform at a given playback height. Pick a height to
        recompute font size and top margin.
      </Text>
      <Text style={styles.fieldLabel}>Playback height</Text>
      <Chips options={heightOptions} selected={playH} onSelect={setPlayH} />
      {data ? <Text style={styles.count}>play_h = {data.play_h}px</Text> : null}
    </View>
  );

  const renderItem = useCallback(
    ({ item }: { item: SurfaceRow }) => {
      const bandTop = `${Math.max(0, Math.min(100, item.zone.y_frac * 100))}%` as const;
      return (
        <View style={styles.row}>
          <View style={styles.rowHeader}>
            <Text style={styles.surface}>{item.surface}</Text>
            <Text style={styles.yfrac}>y {Math.round(item.zone.y_frac * 100)}%</Text>
          </View>
          <View style={styles.rowBody}>
            <View style={styles.frame}>
              <View style={[styles.band, { top: bandTop }]} />
            </View>
            <View style={styles.metrics}>
              <Text style={styles.metric}>
                Font size <Text style={styles.metricValue}>{item.zone.fontsize}px</Text>
              </Text>
              <Text style={styles.metric}>
                Top margin <Text style={styles.metricValue}>{item.zone.margin_v}px</Text>
              </Text>
            </View>
          </View>
        </View>
      );
    },
    [],
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load(playH, "initial")}
      loadingLabel="Loading safe zones…"
    >
      <FlatList
        data={rows}
        keyExtractor={(r) => r.surface}
        renderItem={renderItem}
        ListHeaderComponent={header}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={() => <View style={styles.sep} />}
        ListEmptyComponent={<Text style={styles.empty}>No safe zones returned.</Text>}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load(playH, "refresh")}
            tintColor={colors.accent}
          />
        }
      />
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 10, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  fieldLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  count: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  row: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  rowHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  surface: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", textTransform: "capitalize" },
  yfrac: { color: colors.muted, fontSize: 12 },
  rowBody: { flexDirection: "row", gap: 16, alignItems: "center" },
  frame: {
    width: 54,
    height: 96,
    borderRadius: 8,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    position: "relative",
    overflow: "hidden",
  },
  band: {
    position: "absolute",
    left: 6,
    right: 6,
    height: 10,
    borderRadius: 3,
    backgroundColor: colors.primary,
  },
  metrics: { flex: 1, gap: 6 },
  metric: { color: colors.textSecondary, fontSize: 13 },
  metricValue: { color: colors.textPrimary, fontWeight: "700" },
  sep: { height: 10 },
  empty: { color: colors.muted, fontSize: 14, textAlign: "center", paddingVertical: 24 },
});
