/**
 * A single public marketplace listing: title, description, tag chips, the
 * aggregate star rating (+ count and clone count), a "Your rating" interactive
 * star row, and a Clone action. The parent owns the clone/rate network calls and
 * navigation; this card owns only the transient cloning state and the caller's
 * optimistic own-rating so a tap feels instant and rolls back on failure.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { MarketplaceTemplate } from "@/lib/types";
import { colors } from "@/components/me/theme";

import { StarRating } from "./StarRating";

interface MarketplaceCardProps {
  template: MarketplaceTemplate;
  /** Clone into the caller's private templates; resolves on success. */
  onClone: (id: string) => Promise<void>;
  /** Upsert the caller's 1..5 rating; resolves on success, rejects on failure. */
  onRate: (id: string, stars: number) => Promise<void>;
}

/** Compact rating summary, e.g. "4.6 (128)"; blank when never rated. */
function ratingSummary(avg: number, count: number): string {
  if (count <= 0) return "No ratings yet";
  return `${avg.toFixed(1)} (${count})`;
}

export function MarketplaceCard({
  template,
  onClone,
  onRate,
}: MarketplaceCardProps) {
  const [cloning, setCloning] = useState(false);
  const [cloned, setCloned] = useState(false);
  const [rating, setRating] = useState(false);

  const initialStars =
    typeof template.viewer_stars === "number" ? template.viewer_stars : 0;
  const [myStars, setMyStars] = useState(initialStars);

  const clone = async () => {
    if (cloning || cloned) return;
    setCloning(true);
    try {
      await onClone(template.id);
      setCloned(true);
    } finally {
      setCloning(false);
    }
  };

  const rate = async (stars: number) => {
    if (rating) return;
    const previous = myStars;
    setMyStars(stars); // optimistic
    setRating(true);
    try {
      await onRate(template.id, stars);
    } catch {
      setMyStars(previous); // roll back on failure
    } finally {
      setRating(false);
    }
  };

  const tags = Array.isArray(template.tags) ? template.tags : [];

  return (
    <View style={styles.card}>
      <Text style={styles.title}>{template.title || "Untitled template"}</Text>

      {template.description ? (
        <Text style={styles.description}>{template.description}</Text>
      ) : null}

      <View style={styles.meta}>
        <StarRating value={template.rating_avg} />
        <Text style={styles.metaText}>
          {ratingSummary(template.rating_avg, template.rating_count)}
        </Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.metaText}>
          {template.clone_count} clone{template.clone_count === 1 ? "" : "s"}
        </Text>
      </View>

      {tags.length > 0 || template.language ? (
        <View style={styles.tags}>
          {template.language ? (
            <View style={[styles.tag, styles.langTag]}>
              <Text style={styles.tagText}>{template.language}</Text>
            </View>
          ) : null}
          {tags.map((tag, i) => (
            <View key={`${tag}-${i}`} style={styles.tag}>
              <Text style={styles.tagText}>{tag}</Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.rateRow}>
        <Text style={styles.rateLabel}>Your rating</Text>
        <StarRating value={myStars} onRate={rate} disabled={rating} size={22} />
      </View>

      <Pressable
        style={[styles.primary, cloned && styles.primaryDone]}
        onPress={clone}
        disabled={cloning || cloned}
        accessibilityRole="button"
      >
        {cloning ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.primaryText}>
            {cloned ? "Cloned" : "Clone to my templates"}
          </Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  title: { color: colors.textPrimary, fontSize: 17, fontWeight: "800" },
  description: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  meta: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  metaText: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  dot: { color: colors.muted, fontSize: 13 },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  tag: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  langTag: { borderColor: colors.primary },
  tagText: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  rateRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 2,
  },
  rateLabel: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
  },
  primaryDone: { backgroundColor: colors.cardAlt, borderColor: colors.success, borderWidth: 1 },
  primaryText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
});
