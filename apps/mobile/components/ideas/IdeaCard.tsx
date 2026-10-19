/**
 * A single generated SPARK concept with its "Make this" (one-click -> Create)
 * and "Save" affordances. The parent owns navigation and the save network call;
 * this card owns only the transient saving/saved UI state.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Idea } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { IdeaBody } from "./IdeaBody";

interface IdeaCardProps {
  idea: Idea;
  onMake: (idea: Idea) => void;
  onSave: (idea: Idea) => Promise<void>;
}

export function IdeaCard({ idea, onMake, onSave }: IdeaCardProps) {
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    if (saving || saved) return;
    setSaving(true);
    try {
      await onSave(idea);
      setSaved(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={styles.card}>
      <IdeaBody idea={idea} />

      <View style={styles.actions}>
        <Pressable style={styles.primary} onPress={() => onMake(idea)}>
          <Text style={styles.primaryText}>Make this</Text>
        </Pressable>
        <Pressable
          style={[styles.secondary, saved && styles.secondaryDone]}
          onPress={save}
          disabled={saving || saved}
        >
          {saving ? (
            <ActivityIndicator color={colors.textSecondary} />
          ) : (
            <Text style={styles.secondaryText}>{saved ? "Saved" : "Save"}</Text>
          )}
        </Pressable>
      </View>
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
    gap: 12,
  },
  actions: { flexDirection: "row", gap: 10 },
  primary: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  primaryText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  secondary: {
    flex: 1,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryDone: { borderColor: colors.success },
  secondaryText: { color: colors.textSecondary, fontWeight: "600", fontSize: 15 },
});
