/**
 * Entry point for the timeline editor when it is opened without a reel (e.g.
 * from the Me menu or the navigation hub): lists the creator's finished reels
 * that have a rendered result and opens the editor on the chosen one.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Icon } from "@/components/ui/Icon";
import { jobDisplayName, listJobs } from "@/lib/api";
import { JobState, type Job } from "@/lib/types";
import { useSession } from "@/src/shared/auth";
import { jobResultUrl } from "@/src/shared/media/job-media";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

const MAX_ROWS = 30;

interface EditableReel {
  job: Job;
  url: string;
}

export function EditorJobPicker() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [rows, setRows] = useState<EditableReel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    try {
      const jobs = await listJobs({ token });
      const editable = jobs
        .filter((job) => job.state === JobState.Complete && !job.cancelled)
        .map((job) => ({ job, url: jobResultUrl(job) ?? "" }))
        .filter((row) => row.url.length > 0)
        .slice(0, MAX_ROWS);
      setRows(editable);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load your reels.");
      setRows([]);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (row: EditableReel) => {
    router.replace(
      `/editor?jobId=${encodeURIComponent(row.job.job_id)}&url=${encodeURIComponent(row.url)}`,
    );
  };

  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>Timeline editor</Text>
      <Text style={styles.intro}>
        Pick a finished reel to trim, reorder, caption and overlay into a new export.
      </Text>

      {rows === null ? <ActivityIndicator color={colors.accent} style={styles.spinner} /> : null}
      {error ? (
        <View style={styles.errorRow}>
          <Text style={styles.error}>{error}</Text>
          <Pressable onPress={() => void load()} accessibilityRole="button">
            <Text style={styles.link}>Retry</Text>
          </Pressable>
        </View>
      ) : null}

      {rows && rows.length === 0 && !error ? (
        <View style={styles.empty}>
          <Text style={styles.intro}>
            You have no finished reels yet. Create one, or import footage to start from your own clip.
          </Text>
          <Pressable
            style={styles.button}
            onPress={() => router.push("/(tabs)/create")}
            accessibilityRole="button"
          >
            <Text style={styles.buttonText}>Create a reel</Text>
          </Pressable>
          <Pressable
            style={styles.secondary}
            onPress={() => router.push("/capture/screen-import" as never)}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryText}>Import footage</Text>
          </Pressable>
        </View>
      ) : null}

      {rows?.map((row) => (
        <Pressable
          key={row.job.job_id}
          style={styles.row}
          onPress={() => open(row)}
          accessibilityRole="button"
          accessibilityLabel={`Edit ${jobDisplayName(row.job)}`}
        >
          <Icon name="film-outline" size={20} color={colors.textSecondary} />
          <Text style={styles.rowTitle} numberOfLines={1}>
            {jobDisplayName(row.job)}
          </Text>
          <Icon name="chevron-forward" size={18} color={colors.textFaint} />
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "700" },
  intro: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  spinner: { marginVertical: spacing.lg },
  errorRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  error: { color: colors.danger, fontSize: typeScale.caption, flex: 1 },
  link: { color: colors.accent, fontSize: typeScale.caption, fontWeight: "700" },
  empty: { gap: spacing.sm, marginTop: spacing.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
  },
  rowTitle: { color: colors.textPrimary, fontSize: typeScale.body, flex: 1 },
  button: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
  },
  buttonText: { color: colors.onAccent, fontSize: typeScale.body, fontWeight: "700" },
  secondary: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryText: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
});
