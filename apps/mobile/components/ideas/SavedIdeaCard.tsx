/**
 * A single saved SPARK concept with "Make this" and delete affordances. The
 * parent owns navigation, the delete network call and the optimistic list
 * update; this card owns only the transient deleting state.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import type { Idea, SavedIdea } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { IdeaBody } from "./IdeaBody";

interface SavedIdeaCardProps {
  saved: SavedIdea;
  onMake: (idea: Idea) => void;
  onDelete: (id: string) => Promise<void>;
}

export function SavedIdeaCard({ saved, onMake, onDelete }: SavedIdeaCardProps) {
  const [deleting, setDeleting] = useState(false);

  // The full concept lives under `idea`; fall back to the denormalised
  // title/hook columns if an older row stored an empty payload.
  const idea: Idea =
    saved.idea && Object.keys(saved.idea).length > 0
      ? saved.idea
      : ({
          title: saved.title,
          hook: saved.hook,
          angle: "",
          format: "",
          script_outline: [],
        } as Idea);

  const remove = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await onDelete(saved.id);
    } finally {
      // On success the card unmounts; on failure re-enable it.
      setDeleting(false);
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
          style={styles.delete}
          onPress={remove}
          disabled={deleting}
          hitSlop={8}
        >
          {deleting ? (
            <ActivityIndicator color={colors.error} />
          ) : (
            <Text style={styles.deleteText}>Delete</Text>
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
  actions: { flexDirection: "row", gap: 10, alignItems: "center" },
  primary: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  primaryText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  delete: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 10,
    borderColor: colors.border,
    borderWidth: 1,
  },
  deleteText: { color: colors.error, fontWeight: "600", fontSize: 15 },
});
