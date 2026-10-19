/**
 * Horizontal picker of the caller's finished reels. The creator taps the job
 * they posted, then logs its real-world metrics below. Purely presentational —
 * the parent owns the job list and the selection state.
 */

import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { Job } from "@/lib/types";

import { colors } from "@/components/me/theme";

interface JobPickerProps {
  jobs: Job[];
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

/** A short, stable label for a job id (last 6 chars, uppercased). */
function shortId(jobId: string): string {
  const tail = jobId.length > 6 ? jobId.slice(-6) : jobId;
  return tail.toUpperCase();
}

export function JobPicker({ jobs, selectedJobId, onSelect }: JobPickerProps) {
  if (jobs.length === 0) {
    return (
      <Text style={styles.empty}>
        No finished reels yet. Create and render a reel, then come back to log
        how it performed.
      </Text>
    );
  }

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {jobs.map((job) => {
        const active = job.job_id === selectedJobId;
        return (
          <Pressable
            key={job.job_id}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onSelect(job.job_id)}
          >
            <Text style={[styles.chipLabel, active && styles.chipLabelActive]}>
              Reel {shortId(job.job_id)}
            </Text>
          </Pressable>
        );
      })}
      <View style={styles.tail} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 8, paddingRight: 4 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 9,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipLabelActive: { color: colors.textPrimary, fontWeight: "700" },
  empty: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  tail: { width: 4 },
});
