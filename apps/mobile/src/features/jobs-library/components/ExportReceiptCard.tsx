import { StyleSheet, Text, View } from "react-native";

import type { ExportReceipt } from "@/src/shared/media";

function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) {
    return "Not available";
  }
  const megabytes = value / (1024 * 1024);
  return megabytes >= 0.1
    ? `${megabytes.toFixed(megabytes >= 10 ? 1 : 2)} MB`
    : `${Math.round(value / 1024)} KB`;
}

function formatDuration(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value <= 0) {
    return "Not reported";
  }
  const minutes = Math.floor(value / 60);
  const seconds = value - minutes * 60;
  return minutes > 0
    ? `${minutes}m ${seconds.toFixed(1)}s`
    : `${seconds.toFixed(1)}s`;
}

function formatAttemptTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "Not reported"
    : parsed.toLocaleString();
}

function receiptStatus(receipt: ExportReceipt): string {
  if (receipt.status === "shared") return "Share completed";
  if (receipt.status === "ready") {
    return receipt.shareStatus === "dismissed"
      ? "Downloaded; share dismissed"
      : "Ready to share";
  }
  if (receipt.status === "downloading") return "Download interrupted";
  return receipt.failedStep === "share"
    ? "Downloaded; sharing failed"
    : "Export failed";
}

export function ExportReceiptCard({
  receipt,
}: Readonly<{ receipt: ExportReceipt }>) {
  const failed =
    receipt.status === "failed" || receipt.status === "downloading";
  const retryText = failed
    ? `Retry available for this job. Attempts: ${receipt.attemptCount}.`
    : `Attempts: ${receipt.attemptCount}. You can share this file again.`;

  return (
    <View style={styles.card} accessibilityLabel="Export receipt">
      <View style={styles.headingRow}>
        <Text style={styles.heading}>Output receipt</Text>
        <Text style={[styles.status, failed && styles.statusFailed]}>
          {receiptStatus(receipt)}
        </Text>
      </View>

      <View style={styles.rule} />
      <View style={styles.row}>
        <Text style={styles.label}>File</Text>
        <Text style={styles.value}>{receipt.fileName}</Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Duration</Text>
        <Text style={styles.value}>
          {formatDuration(receipt.durationSeconds)}
        </Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Size</Text>
        <Text style={styles.value}>{formatBytes(receipt.sizeBytes)}</Text>
      </View>
      <View style={styles.row}>
        <Text style={styles.label}>Last attempt</Text>
        <Text style={styles.value}>
          {formatAttemptTime(receipt.lastAttemptAt)}
        </Text>
      </View>
      <View style={styles.locationRow}>
        <Text style={styles.label}>Location</Text>
        <Text selectable style={styles.path} numberOfLines={2}>
          {receipt.localUri}
        </Text>
      </View>

      {receipt.errorMessage ? (
        <Text style={styles.error}>{receipt.errorMessage}</Text>
      ) : null}
      <Text style={styles.retry}>{retryText}</Text>
    </View>
  );
}

const mono = "Menlo";

const styles = StyleSheet.create({
  card: {
    backgroundColor: "#000000",
    borderColor: "#35353f",
    borderWidth: 1,
    borderRadius: 0,
    padding: 14,
    gap: 9,
    marginTop: 4,
  },
  headingRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
  },
  heading: {
    color: "#ffffff",
    fontFamily: mono,
    fontSize: 14,
    fontWeight: "700",
  },
  status: {
    color: "#00e676",
    fontFamily: mono,
    fontSize: 11,
    textAlign: "right",
    flexShrink: 1,
  },
  statusFailed: { color: "#D0605B" },
  rule: { height: 1, backgroundColor: "#35353f" },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 12,
  },
  locationRow: { gap: 4 },
  label: { color: "#7f7f89", fontFamily: mono, fontSize: 11 },
  value: {
    color: "#ffffff",
    fontFamily: mono,
    fontSize: 11,
    textAlign: "right",
    flexShrink: 1,
  },
  path: { color: "#b8b8c2", fontFamily: mono, fontSize: 10, lineHeight: 14 },
  error: { color: "#D0605B", fontFamily: mono, fontSize: 11, lineHeight: 16 },
  retry: { color: "#b8b8c2", fontFamily: mono, fontSize: 10, lineHeight: 14 },
});
