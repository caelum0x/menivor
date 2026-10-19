import { StyleSheet, Text, View } from "react-native";

export type CreatorFlowStage = "footage" | "brief" | "render" | "export";

const STAGES: readonly { id: CreatorFlowStage; label: string }[] = [
  { id: "footage", label: "Footage" },
  { id: "brief", label: "Brief" },
  { id: "render", label: "Render" },
  { id: "export", label: "Export" },
];

export function CreatorFlowRail({
  active,
  completed = [],
}: {
  active?: CreatorFlowStage;
  completed?: readonly CreatorFlowStage[];
}) {
  const completedSet = new Set(completed);

  return (
    <View style={styles.shell} accessibilityRole="summary">
      <View style={styles.rail}>
        {STAGES.map((stage, index) => {
          const done = completedSet.has(stage.id);
          const current = active === stage.id;
          return (
            <View key={stage.id} style={styles.step}>
              <View style={styles.markerRow}>
                <View
                  style={[
                    styles.marker,
                    done && styles.markerDone,
                    current && styles.markerCurrent,
                  ]}
                >
                  <Text
                    style={[
                      styles.markerText,
                      done && styles.markerTextDone,
                      current && styles.markerTextCurrent,
                    ]}
                  >
                    {index + 1}
                  </Text>
                </View>
                {index < STAGES.length - 1 ? (
                  <View style={[styles.line, done && styles.lineDone]} />
                ) : null}
              </View>
              <Text
                style={[
                  styles.label,
                  (done || current) && styles.labelActive,
                ]}
              >
                {stage.label}
              </Text>
              <Text
                style={[
                  styles.status,
                  done && styles.statusDone,
                  current && styles.statusCurrent,
                ]}
              >
                {done ? "Done" : current ? "Current" : "Waiting"}
              </Text>
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    backgroundColor: "#0b0c0a",
    borderColor: "#343630",
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 13,
  },
  rail: { flexDirection: "row" },
  step: { flex: 1, minWidth: 0 },
  markerRow: { flexDirection: "row", alignItems: "center" },
  marker: {
    width: 24,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#0b0c0a",
    borderColor: "#4b4e46",
    borderWidth: 1,
  },
  markerDone: { backgroundColor: "#0b0c0a", borderColor: "#00e676" },
  markerCurrent: {
    backgroundColor: "#E6C76A",
    borderColor: "#E6C76A",
  },
  markerText: {
    color: "#777a70",
    fontFamily: "monospace",
    fontSize: 11,
    fontWeight: "800",
  },
  markerTextDone: { color: "#00e676" },
  markerTextCurrent: { color: "#0b0c0a" },
  line: {
    flex: 1,
    height: 1,
    backgroundColor: "#4b4e46",
    marginHorizontal: 4,
  },
  lineDone: { backgroundColor: "#00e676" },
  label: {
    color: "#777a70",
    fontFamily: "monospace",
    fontSize: 10,
    fontWeight: "700",
    marginTop: 6,
  },
  labelActive: { color: "#ffffff" },
  status: {
    color: "#777a70",
    fontFamily: "monospace",
    fontSize: 9,
    marginTop: 2,
  },
  statusDone: { color: "#00e676" },
  statusCurrent: { color: "#E6C76A" },
});
