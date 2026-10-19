/**
 * The project's rendered ads: status, inline player, and the per-ad actions
 * (start the avatar reel, retry a failed render, open or remove it). The
 * parent polls while any ad is still rendering.
 */

import { useState } from "react";
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from "react-native";

import { Badge, Button, Icon, type BadgeVariant } from "@/components/ui";
import { JobVideo } from "@/src/shared/media";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import { AVATAR_AD_CREDITS, STATUS_LABELS, type AdVariant, type VariantStatus } from "../api";

const STATUS_VARIANT: Record<VariantStatus, BadgeVariant> = {
  queued: "neutral",
  rendering: "accent",
  ready: "neutral",
  submitted: "accent",
  done: "success",
  failed: "danger",
};

const ASPECT_RATIO: Record<string, number> = {
  "9:16": 9 / 16,
  "1:1": 1,
  "16:9": 16 / 9,
};

export interface VariantActions {
  readonly onRetry: (ad: AdVariant) => Promise<void>;
  readonly onDelete: (ad: AdVariant) => Promise<void>;
  readonly onStartAvatar: (ad: AdVariant) => Promise<void>;
}

function httpUrl(value: string | null | undefined): string | null {
  return value && /^https?:\/\//i.test(value) ? value : null;
}

function VariantCard({ ad, actions }: Readonly<{ ad: AdVariant; actions: VariantActions }>) {
  const [busy, setBusy] = useState(false);
  const [showScript, setShowScript] = useState(false);
  const run = (fn: (ad: AdVariant) => Promise<void>) => async () => {
    setBusy(true);
    try {
      await fn(ad);
    } finally {
      setBusy(false);
    }
  };
  const media = httpUrl(ad.video_url) ?? (ad.status === "ready" ? httpUrl(ad.montage_url) : null);
  const poster = httpUrl(ad.poster_url) ?? undefined;
  const download = httpUrl(ad.download_url);
  const portrait = ad.aspect === "9:16";

  return (
    <View style={styles.card}>
      {media ? (
        portrait ? (
          <JobVideo uri={media} posterUri={poster} />
        ) : (
          <View style={[styles.frame, { aspectRatio: ASPECT_RATIO[ad.aspect] ?? 1 }]}>
            <Pressable
              style={styles.center}
              onPress={() => void Linking.openURL(media).catch(() => undefined)}
              accessibilityRole="button"
              accessibilityLabel="Play this ad"
            >
              <Icon name="play-circle-outline" size={40} color={colors.textPrimary} />
              <Text style={styles.muted}>Play {ad.aspect} ad</Text>
            </Pressable>
          </View>
        )
      ) : (
        <View style={[styles.frame, styles.center, { aspectRatio: portrait ? 1 : ASPECT_RATIO[ad.aspect] ?? 1 }]}>
          {ad.status === "failed" ? (
            <Text style={styles.muted}>No video</Text>
          ) : (
            <ActivityIndicator color={colors.textSecondary} accessibilityLabel="Rendering" />
          )}
        </View>
      )}

      <View style={styles.metaRow}>
        <Badge label={STATUS_LABELS[ad.status]} variant={STATUS_VARIANT[ad.status]} />
        <Text style={[styles.muted, styles.flex]} numberOfLines={2}>
          {ad.format_label} · {ad.aspect} · {ad.angle_label}
          {ad.duration_s ? ` · ${ad.duration_s.toFixed(0)}s` : ""}
        </Text>
      </View>
      {ad.error ? <Text style={styles.error}>{ad.error}</Text> : null}
      {ad.status === "ready" ? (
        <Text style={styles.muted}>
          The product montage is ready. Starting the avatar reel uses {AVATAR_AD_CREDITS} reel
          credit; it is refunded automatically if the render fails.
        </Text>
      ) : null}

      <View style={styles.actions}>
        {ad.status === "done" && download ? (
          <Button
            label="Save or share"
            size="sm"
            onPress={() => void Linking.openURL(download).catch(() => undefined)}
          />
        ) : null}
        {ad.status === "ready" ? (
          <Button
            label={`Start avatar reel (${AVATAR_AD_CREDITS} credit)`}
            size="sm"
            loading={busy}
            onPress={() => void run(actions.onStartAvatar)()}
          />
        ) : null}
        {ad.status === "failed" ? (
          <Button label="Retry" size="sm" variant="secondary" loading={busy} onPress={() => void run(actions.onRetry)()} />
        ) : null}
        {ad.status !== "rendering" && ad.status !== "submitted" ? (
          <Button
            label="Remove"
            size="sm"
            variant="ghost"
            disabled={busy}
            onPress={() => void run(actions.onDelete)()}
            accessibilityLabel="Remove this ad"
          />
        ) : null}
      </View>

      <Pressable
        onPress={() => setShowScript((open) => !open)}
        accessibilityRole="button"
        accessibilityState={{ expanded: showScript }}
        hitSlop={8}
      >
        <Text style={styles.link}>{showScript ? "Hide script" : "Show script"}</Text>
      </Pressable>
      {showScript ? <Text style={styles.script}>{ad.script}</Text> : null}
    </View>
  );
}

export interface VariantGridProps {
  readonly variants: readonly AdVariant[];
  readonly actions: VariantActions;
}

export function VariantGrid({ variants, actions }: VariantGridProps) {
  if (variants.length === 0) {
    return <Text style={styles.muted}>No ads rendered yet. Pick angles and formats above.</Text>;
  }
  return (
    <View style={styles.list}>
      {variants.map((ad) => (
        <VariantCard key={ad.id} ad={ad} actions={actions} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { gap: spacing.md },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  frame: {
    width: "100%",
    borderRadius: radius.md,
    backgroundColor: colors.surfaceMuted,
    overflow: "hidden",
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  metaRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  flex: { flex: 1 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  link: { color: colors.textSecondary, fontSize: typeScale.caption, textDecorationLine: "underline" },
  script: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
});
