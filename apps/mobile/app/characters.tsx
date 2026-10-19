/**
 * Characters screen — browse saved character identities and create new ones on
 * mobile. Mirrors the web characters gallery.
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { useSession } from "@/src/shared/auth";
import { createCharacter, listCharacters, type Character } from "@/lib/characters";

export default function CharactersScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [characters, setCharacters] = React.useState<Character[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const [name, setName] = React.useState("");
  const [descriptors, setDescriptors] = React.useState("");
  const [style, setStyle] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [formError, setFormError] = React.useState("");

  React.useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await listCharacters({ token });
        if (active) setCharacters(res.characters);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load characters.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [token]);

  const onCreate = React.useCallback(async () => {
    if (!name.trim()) {
      setFormError("Name is required.");
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      const parsedDescriptors = descriptors
        .split(",")
        .map((d) => d.trim())
        .filter((d) => d.length > 0);
      const created = await createCharacter(
        {
          name: name.trim(),
          descriptors: parsedDescriptors.length > 0 ? parsedDescriptors : undefined,
          style: style.trim() ? style.trim() : undefined,
        },
        { token },
      );
      setCharacters((prev) => [created, ...prev]);
      setName("");
      setDescriptors("");
      setStyle("");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create character.");
    } finally {
      setSubmitting(false);
    }
  }, [name, descriptors, style, token]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.intro}>
        Reusable character identities keep the same look and voice across every reel.
      </Text>

      <View style={styles.form}>
        <Text style={styles.formTitle}>New character</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="Name"
          placeholderTextColor={colors.muted}
        />
        <TextInput
          style={styles.input}
          value={descriptors}
          onChangeText={setDescriptors}
          placeholder="Descriptors (comma separated)"
          placeholderTextColor={colors.muted}
        />
        <TextInput
          style={styles.input}
          value={style}
          onChangeText={setStyle}
          placeholder="Style"
          placeholderTextColor={colors.muted}
        />
        {formError ? <Text style={styles.error}>{formError}</Text> : null}
        <Pressable
          style={[styles.button, submitting && styles.buttonDisabled]}
          onPress={onCreate}
          disabled={submitting}
        >
          {submitting ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.buttonText}>Create character</Text>
          )}
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>Saved characters</Text>
      {loading ? (
        <ActivityIndicator color={colors.primary} style={styles.spacer} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : characters.length === 0 ? (
        <Text style={styles.empty}>No characters yet — create your first one above.</Text>
      ) : (
        characters.map((c) => (
          <View key={c.id} style={styles.card}>
            <Text style={styles.name}>{c.name}</Text>
            {c.descriptors.length > 0 ? (
              <Text style={styles.desc}>{c.descriptors.join(", ")}</Text>
            ) : null}
            {c.style ? <Text style={styles.meta}>{c.style}</Text> : null}
          </View>
        ))
      )}
      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, marginBottom: 16 },
  form: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 20,
  },
  formTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 12 },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
    marginBottom: 10,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: colors.bg, fontSize: 14, fontWeight: "600" },
  sectionTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 12 },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  name: { color: colors.textPrimary, fontSize: 16, fontWeight: "600", marginBottom: 4 },
  desc: { color: colors.textSecondary, fontSize: 13, marginBottom: 8 },
  meta: { color: colors.muted, fontSize: 12 },
  empty: { color: colors.muted, fontSize: 14 },
  error: { color: colors.error, fontSize: 14, marginBottom: 8 },
  spacer: { height: 24 },
});
