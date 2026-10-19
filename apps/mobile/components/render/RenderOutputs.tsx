/**
 * Playable render outputs. Shows each presigned output URL as an inline video
 * (or image) with "Open" and "Share" actions, and explains when a completed
 * render has refs the device cannot play (e.g. LAN-only worker URLs).
 */

import { Image, Linking, Pressable, Share, StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import { Icon } from "@/components/ui/Icon";
import { JobVideo } from "@/src/shared/media";
import { isImageOutput, renderPlayableUrls, type RenderJob } from "@/lib/render";

interface RenderOutputsProps {
  job: RenderJob;
  /** Show only the first output (compact history rows). */
  compact?: boolean;
}

export function RenderOutputs({ job, compact = false }: RenderOutputsProps) {
  const urls = renderPlayableUrls(job);
  const shown = compact ? urls.slice(0, 1) : urls;
  const unusable =
    typeof job.unusable_output_refs === "number"
      ? job.unusable_output_refs
      : Math.max(0, (job.output_refs?.length ?? 0) - urls.length);

  if (urls.length === 0) {
    if (job.state !== "COMPLETED") return null;
    return (
      <Text style={styles.note}>
        {unusable > 0
          ? "This render finished, but its output is stored where the app cannot reach it."
          : "This render finished without a downloadable output."}
      </Text>
    );
  }

  return (
    <View style={styles.wrap}>
      {shown.map((url, index) => (
        <View key={url} style={styles.item}>
          {isImageOutput(url) ? (
            <Image
              source={{ uri: url }}
              style={styles.image}
              resizeMode="contain"
              accessibilityLabel={`Render output ${index + 1}`}
            />
          ) : (
            <JobVideo uri={url} />
          )}
          <View style={styles.actions}>
            <Pressable
              style={styles.action}
              onPress={() => void Linking.openURL(url)}
              accessibilityRole="button"
              accessibilityLabel={`Open output ${index + 1}`}
            >
              <Icon name="open-outline" size={16} color={colors.primary} />
              <Text style={styles.actionText}>Open</Text>
            </Pressable>
            <Pressable
              style={styles.action}
              onPress={() => void Share.share({ url, message: url })}
              accessibilityRole="button"
              accessibilityLabel={`Share output ${index + 1}`}
            >
              <Icon name="share-outline" size={16} color={colors.primary} />
              <Text style={styles.actionText}>Share</Text>
            </Pressable>
          </View>
        </View>
      ))}
      {compact && urls.length > 1 ? (
        <Text style={styles.note}>+{urls.length - 1} more output(s) on the job page</Text>
      ) : null}
      {!compact && unusable > 0 ? (
        <Text style={styles.note}>{unusable} output(s) could not be made playable.</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12, marginTop: 10 },
  item: { gap: 8 },
  image: { width: "100%", aspectRatio: 1, borderRadius: 10, backgroundColor: colors.card },
  actions: { flexDirection: "row", gap: 16 },
  action: { flexDirection: "row", alignItems: "center", gap: 4 },
  actionText: { color: colors.primary, fontSize: 13, fontWeight: "600" },
  note: { color: colors.muted, fontSize: 12, marginTop: 6 },
});
