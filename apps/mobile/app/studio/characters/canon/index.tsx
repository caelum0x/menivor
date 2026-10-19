/**
 * Studio · Character Canon — manager
 *
 * Nav manifest: { route: "/studio/characters/canon", title: "Character Canon" }
 *
 * Governs canonical brand/character identities. Lists the caller's canons
 * (GET /canon) with pull-to-refresh, and creates a new one (POST /canon) that
 * locks version 1 from a name + optional bound character + a shared value
 * surface (style, palette, typography, voice, product, brand). Tapping a canon
 * opens its detail (version history + lock + verify). Explicit loading / empty /
 * error states; the create form validates the required name and blocks a fully
 * empty value surface.
 *
 * Related routes (integration handles nav):
 *   /studio/characters/canon/[id]                    canon detail
 *   /studio/characters/canon/[id]/versions/[version] immutable snapshot
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Stack, useRouter } from "expo-router";

import { createCanon, listCanons, type CanonSummary } from "@/lib/canon";
import { listCharacters, type Character } from "@/lib/characters";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { CanonValueFields } from "@/components/canon/CanonValueFields";
import {
  EMPTY_CANON_FIELDS,
  fieldsAreEmpty,
  fieldsToBody,
  type CanonValueFields as Fields,
} from "@/components/canon/canon-fields";

export default function CanonManagerScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [canons, setCanons] = useState<CanonSummary[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const [characters, setCharacters] = useState<Character[]>([]);
  const [name, setName] = useState("");
  const [characterId, setCharacterId] = useState("");
  const [fields, setFields] = useState<Fields>(EMPTY_CANON_FIELDS);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setStatus("loading");
      else setRefreshing(true);
      try {
        const [rows, chars] = await Promise.all([
          listCanons({ token }),
          listCharacters({ token }).then((r) => r.characters).catch(() => []),
        ]);
        setCanons(rows);
        setCharacters(chars);
        setStatus("ready");
        setError("");
      } catch (err) {
        setError(describeError(err, "Failed to load canons."));
        if (mode === "initial") setStatus("error");
      } finally {
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const onChangeField = useCallback((key: keyof Fields, value: string) => {
    setFields((prev) => ({ ...prev, [key]: value }));
  }, []);

  const onCreate = useCallback(async () => {
    if (!name.trim()) {
      setFormError("A canon name is required.");
      return;
    }
    if (fieldsAreEmpty(fields)) {
      setFormError("Add at least one value (style, voice, product, or brand) to lock.");
      return;
    }
    setSubmitting(true);
    setFormError("");
    try {
      const result = await createCanon(
        {
          name: name.trim(),
          character_id: characterId || undefined,
          ...fieldsToBody(fields),
        },
        { token },
      );
      // Prepend a header row so the list reflects the new canon immediately.
      setCanons((prev) => [
        {
          canon_id: result.canon_id,
          name: name.trim(),
          current_canon_hash: result.canon_hash,
          current_version: result.version,
        },
        ...prev,
      ]);
      setName("");
      setCharacterId("");
      setFields(EMPTY_CANON_FIELDS);
      router.push(`/studio/characters/canon/${result.canon_id}`);
    } catch (err) {
      setFormError(describeError(err, "Failed to create the canon."));
    } finally {
      setSubmitting(false);
    }
  }, [name, characterId, fields, token, router]);

  const keyExtractor = useCallback((c: CanonSummary) => c.canon_id, []);

  const renderItem = useCallback(
    ({ item }: { item: CanonSummary }) => (
      <Pressable
        style={styles.card}
        onPress={() => router.push(`/studio/characters/canon/${item.canon_id}`)}
        accessibilityRole="button"
        accessibilityLabel={`Open canon ${item.name}`}
      >
        <View style={styles.cardBody}>
          <Text style={styles.cardName} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={styles.cardHash} numberOfLines={1}>
            {item.current_canon_hash || "unlocked"}
          </Text>
        </View>
        <View style={styles.versionBadge}>
          <Text style={styles.versionText}>v{item.current_version}</Text>
        </View>
      </Pressable>
    ),
    [router],
  );

  const header = (
    <View style={styles.headerBlock}>
      <Text style={styles.intro}>
        A canon locks a canonical identity into immutable, hashed versions. Lock
        new values to append a version — old versions are never overwritten, so
        every generation can be verified against exactly what was approved.
      </Text>

      <View style={styles.form}>
        <Text style={styles.formTitle}>New canon</Text>
        <Text style={styles.label}>Name</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          placeholder="e.g. Menivor brand v2026"
          placeholderTextColor={colors.muted}
          editable={!submitting}
        />

        <Text style={styles.label}>Bind a character (optional)</Text>
        {characters.length === 0 ? (
          <Text style={styles.hint}>
            No saved characters to bind. Values below still lock a brand canon.
          </Text>
        ) : (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.chips}
            keyboardShouldPersistTaps="handled"
          >
            <Chip
              label="None"
              selected={characterId === ""}
              onPress={() => setCharacterId("")}
              disabled={submitting}
            />
            {characters.map((c) => (
              <Chip
                key={c.id}
                label={c.name}
                selected={characterId === c.id}
                onPress={() => setCharacterId(c.id)}
                disabled={submitting}
              />
            ))}
          </ScrollView>
        )}

        <View style={styles.divider} />
        <Text style={styles.formTitle}>Values to lock</Text>
        <CanonValueFields fields={fields} onChange={onChangeField} disabled={submitting} />

        {formError ? <Text style={styles.error}>{formError}</Text> : null}
        <Pressable
          style={[styles.primary, submitting && styles.disabled]}
          onPress={() => void onCreate()}
          disabled={submitting}
          accessibilityRole="button"
        >
          {submitting ? (
            <ActivityIndicator color={colors.bg} />
          ) : (
            <Text style={styles.primaryText}>Create and lock v1</Text>
          )}
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>YOUR CANONS</Text>
    </View>
  );

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load("initial")}
      loadingLabel="Loading canons…"
    >
      <Stack.Screen options={{ title: "Character Canon" }} />
      <FlatList
        data={canons}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        ListHeaderComponent={header}
        ItemSeparatorComponent={Separator}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>
            No canons yet. Create one above to lock a canonical identity you can
            verify every generation against.
          </Text>
        }
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load("refresh")}
            tintColor={colors.accent}
          />
        }
        keyboardShouldPersistTaps="handled"
      />
    </StudioScreen>
  );
}

interface ChipProps {
  label: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
}

function Chip({ label, selected, onPress, disabled }: ChipProps) {
  return (
    <Pressable
      style={[styles.chip, selected && styles.chipSelected]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ selected }}
    >
      <Text style={[styles.chipText, selected && styles.chipTextSelected]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

function Separator() {
  return <View style={styles.sep} />;
}

const styles = StyleSheet.create({
  list: { padding: 16, paddingBottom: 48 },
  headerBlock: { gap: 14, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  form: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 10,
  },
  formTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  label: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase",
  },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 14,
  },
  hint: { color: colors.muted, fontSize: 12 },
  chips: { gap: 8, paddingVertical: 2 },
  chip: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    maxWidth: 180,
  },
  chipSelected: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  chipTextSelected: { color: colors.bg },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.border,
    marginVertical: 4,
  },
  primary: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  primaryText: { color: colors.bg, fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.6 },
  error: { color: colors.error, fontSize: 13 },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
    marginTop: 4,
  },
  sep: { height: 10 },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  cardBody: { flex: 1, gap: 4 },
  cardName: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  cardHash: { color: colors.muted, fontSize: 12, fontFamily: "monospace" },
  versionBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  versionText: { color: colors.textSecondary, fontSize: 12, fontWeight: "700" },
  empty: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 20,
    paddingVertical: 24,
    textAlign: "center",
  },
});
