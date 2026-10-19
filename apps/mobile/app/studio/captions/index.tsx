/**
 * Studio · Caption Studio (hub)
 *
 * Nav manifest (for the integration agent to wire into navigation):
 *   { route: "/studio/captions",           title: "Caption Studio" }
 *   { route: "/studio/captions/hook-score", title: "Hook Score" }
 *   { route: "/studio/captions/hormozi",    title: "Hormozi Captions" }
 *   { route: "/studio/captions/safezones",  title: "Safe Zones" }
 *   { route: "/studio/captions/loop-check", title: "Loop Check" }
 *   { route: "/studio/captions/beat-fit",   title: "Beat Fit" }
 *   { route: "/studio/captions/seo",        title: "Caption SEO" }
 *
 * The hub loads the caller's real reel jobs (GET /jobs) with pull-to-refresh and
 * explicit loading / error / empty states. Selecting a job seeds the caption
 * tools with that reel's hook line (carried as a `seed` route param), so hook-
 * scoring and SEO run against real copy rather than a blank field. Each tool
 * card deep-links into one of the six captions server endpoints.
 */

import { useCallback, useMemo, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter, type Href } from "expo-router";

import { listJobs } from "@/lib/api";
import type { Job } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";

interface CaptionTool {
  route: string;
  title: string;
  description: string;
  /** Endpoint this tool exercises, shown as a small badge. */
  endpoint: string;
  /** Whether the tool consumes the selected job's hook seed. */
  usesSeed: boolean;
}

const TOOLS: readonly CaptionTool[] = [
  {
    route: "/studio/captions/hook-score",
    title: "Hook Score",
    description: "Score the first-3s cold-open against the 70% viral gate, with rewrite suggestions.",
    endpoint: "POST /captions/hook-score",
    usesSeed: true,
  },
  {
    route: "/studio/captions/hormozi",
    title: "Punch Captions",
    description: "Group a script into bold 1-2 word cues with one accented key word.",
    endpoint: "POST /captions/hormozi",
    usesSeed: true,
  },
  {
    route: "/studio/captions/seo",
    title: "Caption SEO",
    description: "Front-load searchable keywords and build platform hashtags from your copy.",
    endpoint: "POST /captions/seo",
    usesSeed: true,
  },
  {
    route: "/studio/captions/safezones",
    title: "Safe Zones",
    description: "Per-platform caption placement (font size + top margin) for a playback height.",
    endpoint: "GET /captions/safezones",
    usesSeed: false,
  },
  {
    route: "/studio/captions/loop-check",
    title: "Loop Check",
    description: "Find the frame that loops back to the start most seamlessly (ASMR / loop genres).",
    endpoint: "POST /captions/loop-check",
    usesSeed: false,
  },
  {
    route: "/studio/captions/beat-fit",
    title: "Beat Fit",
    description: "Rank -2 / -3 / -4 frame nudges by how tightly your cuts snap to the music beats.",
    endpoint: "POST /captions/beat-fit",
    usesSeed: false,
  },
];

function jobHook(job: Job): string {
  return (job.hook || "").trim();
}

function jobLabel(job: Job): string {
  const hook = jobHook(job);
  if (hook) return hook;
  return `Reel ${job.job_id.slice(0, 8)}`;
}

export default function CaptionStudioScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const data = await listJobs({ token });
        setJobs(data);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load your reels."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  const onRefresh = useCallback(() => void load("refresh"), [load]);

  const selected = useMemo(
    () => jobs.find((j) => j.job_id === selectedId) ?? null,
    [jobs, selectedId],
  );

  const seed = selected ? jobHook(selected) : "";

  const openTool = useCallback(
    (tool: CaptionTool) => {
      const href = (
        tool.usesSeed && seed
          ? { pathname: tool.route, params: { seed, jobId: selected?.job_id ?? "" } }
          : tool.route
      ) as Href;
      router.push(href);
    },
    [router, seed, selected],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Run the captions server tools against a real reel. Pick a job to seed hook-scoring
        and SEO with its hook line, then open a tool.
      </Text>
      <Text style={styles.sectionLabel}>Your reels</Text>
    </View>
  );

  const toolsSection = (
    <View style={styles.toolsSection}>
      <View style={styles.selectedBanner}>
        <Text style={styles.selectedBannerLabel}>Seed</Text>
        <Text style={styles.selectedBannerValue} numberOfLines={2}>
          {selected
            ? seed || "This reel has no hook line yet — seedable tools open blank."
            : "No reel selected — seedable tools open blank."}
        </Text>
      </View>
      <Text style={styles.sectionLabel}>Tools</Text>
      {TOOLS.map((tool) => (
        <Pressable
          key={tool.route}
          style={styles.toolCard}
          onPress={() => openTool(tool)}
          accessibilityRole="button"
        >
          <View style={styles.toolHeader}>
            <Text style={styles.toolTitle}>{tool.title}</Text>
            {tool.usesSeed ? (
              <View style={styles.seedBadge}>
                <Text style={styles.seedBadgeText}>seeded</Text>
              </View>
            ) : null}
          </View>
          <Text style={styles.toolDesc}>{tool.description}</Text>
        </Pressable>
      ))}
    </View>
  );

  const renderItem = useCallback(
    ({ item }: { item: Job }) => {
      const active = item.job_id === selectedId;
      return (
        <Pressable
          style={[styles.jobRow, active ? styles.jobRowActive : null]}
          onPress={() => setSelectedId(active ? null : item.job_id)}
          accessibilityRole="button"
          accessibilityState={{ selected: active }}
        >
          <View style={styles.jobInfo}>
            <Text style={styles.jobLabel} numberOfLines={2}>
              {jobLabel(item)}
            </Text>
            <Text style={styles.jobMeta}>
              {item.state}
              {item.language ? ` · ${item.language}` : ""}
            </Text>
          </View>
          <View style={[styles.radio, active ? styles.radioActive : null]}>
            {active ? <View style={styles.radioDot} /> : null}
          </View>
        </Pressable>
      );
    },
    [selectedId],
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading your reels…"
    >
      <FlatList
        data={jobs}
        keyExtractor={(j) => j.job_id}
        renderItem={renderItem}
        ListHeaderComponent={header}
        ListFooterComponent={toolsSection}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={
          <Text style={styles.empty}>
            No reels yet. You can still open any tool below — seedable tools will start blank.
          </Text>
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
      />
    </StudioScreen>
  );
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  header: { gap: 10, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  sectionLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  jobRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 12,
  },
  jobRowActive: { borderColor: colors.primary },
  jobInfo: { flex: 1, gap: 3 },
  jobLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "600" },
  jobMeta: { color: colors.muted, fontSize: 12 },
  radio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderColor: colors.border,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
  },
  radioActive: { borderColor: colors.primary },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.primary },
  sep: { height: 10 },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 20,
    textAlign: "center",
  },
  toolsSection: { marginTop: 24, gap: 12 },
  selectedBanner: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  selectedBannerLabel: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  selectedBannerValue: { color: colors.textPrimary, fontSize: 13, lineHeight: 18 },
  toolCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  toolHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  toolTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  seedBadge: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  seedBadgeText: { color: colors.muted, fontSize: 10, fontWeight: "700" },
  toolDesc: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  toolEndpoint: { color: colors.muted, fontSize: 11, fontFamily: "monospace" },
});
