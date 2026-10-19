import { StyleSheet, Text, View } from "react-native";

import { stageColor } from "../job-status";
import {
  JOB_STAGES,
  type JobStage,
  type StageStatus,
} from "@/lib/types";

/**
 * Jobs-library checklist of the ReelForge DAG stages (script → tts → avatar →
 * captions → compose → upload), each reflecting its per-stage status from
 * `job.stages`. Stages absent from the map render as "pending".
 */

const STAGE_LABELS: Record<JobStage, string> = {
  script: "Script",
  tts: "Voiceover",
  avatar: "Avatar",
  captions: "Captions",
  compose: "Compose",
  upload: "Publish",
};

export interface StageProgressProps {
  /** Per-stage status map from `job.stages`. */
  stages?: Partial<Record<JobStage, StageStatus>>;
  /** Which stages to display, in order. Defaults to the full DAG. */
  visibleStages?: readonly JobStage[];
}

export function StageProgress({
  stages,
  visibleStages = JOB_STAGES,
}: Readonly<StageProgressProps>) {
  return (
    <View style={styles.list}>
      {visibleStages.map((stage) => {
        const status: StageStatus = stages?.[stage] ?? "pending";
        const color = stageColor(status);
        return (
          <View key={stage} style={styles.row}>
            <View style={[styles.dot, { backgroundColor: color }]} />
            <Text style={styles.name}>{STAGE_LABELS[stage]}</Text>
            <Text style={[styles.status, { color }]}>{status}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  name: { color: "#c9c9d6", flex: 1 },
  status: { fontSize: 13, fontWeight: "600", textTransform: "capitalize" },
});
