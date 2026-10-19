import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError, suggestBroll } from "@/lib/api";
import {
  DEFAULT_BROLL_AMOUNT,
  type BrollClip,
  type BrollSource,
} from "@/lib/types";

import { BrollClipThumb } from "./BrollClipThumb";
import { BROLL_SOURCE_OPTIONS, sourceLabel } from "./broll-sources";

/**
 * Jobs-library B-roll cutaways for a reel. `introKey`/`outroKey` are
 * {@link BrollClip.key} values sent as `broll_intro_key` / `broll_outro_key`
 * on a create/rerun. Either may be undefined (no cutaway on that end).
 */
export interface BrollSelection {
  introKey?: string;
  outroKey?: string;
}

export interface BrollSectionProps {
  /** The job to suggest B-roll for (keywords derive from its subject/script). */
  jobId: string;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  /** Notified whenever the intro/outro selection changes (immutable object). */
  onSelectionChange?: (selection: BrollSelection) => void;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; clips: BrollClip[] };

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/**
 * "B-roll" section for the job screen (OPTIONAL). The creator picks a stock
 * source, taps "Suggest clips" to pull a few relevant muted stock clips
 * (POST /jobs/{id}/broll/suggest — MPT's vendored Pexels/Pixabay path), then
 * assigns any clip as a brief Intro (before the hook) and/or Outro (after the
 * reel). Nothing loads until the creator opts in; selection is surfaced via
 * `onSelectionChange` for a follow-up create/rerun. The main reel keeps its full
 * audio + captions — cutaways are always muted.
 */
export function BrollSection({
  jobId,
  token,
  onSelectionChange,
}: Readonly<BrollSectionProps>) {
  const [source, setSource] = useState<BrollSource>(BROLL_SOURCE_OPTIONS[0].id);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [introKey, setIntroKey] = useState<string | undefined>(undefined);
  const [outroKey, setOutroKey] = useState<string | undefined>(undefined);

  const emit = useCallback(
    (next: BrollSelection) => onSelectionChange?.(next),
    [onSelectionChange],
  );

  const loadSuggestions = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const clips = await suggestBroll(
        jobId,
        { source, amount: DEFAULT_BROLL_AMOUNT },
        { token },
      );
      setState({ status: "ready", clips });
    } catch (err) {
      setState({
        status: "error",
        message: describe(err, "Couldn't suggest B-roll clips. Try again."),
      });
    }
  }, [jobId, source, token]);

  // Toggling assigns/clears a single intro and a single outro. A clip can be
  // both. Selection is held immutably and echoed to the parent on every change.
  const toggleIntro = useCallback(
    (clip: BrollClip) => {
      setIntroKey((prev) => {
        const next = prev === clip.key ? undefined : clip.key;
        emit({ introKey: next, outroKey });
        return next;
      });
    },
    [emit, outroKey],
  );

  const toggleOutro = useCallback(
    (clip: BrollClip) => {
      setOutroKey((prev) => {
        const next = prev === clip.key ? undefined : clip.key;
        emit({ introKey, outroKey: next });
        return next;
      });
    },
    [emit, introKey],
  );

  const busy = state.status === "loading";
  const hasSelection = Boolean(introKey || outroKey);

  return (
    <View style={styles.container}>
      <Text style={styles.subtitle}>
        Add short, muted stock cutaways around your reel — a brief intro before
        the hook and/or an outro after. Your reel keeps its full audio and
        captions. Optional.
      </Text>

      {/* Stock source toggle */}
      <View style={styles.sourceRow}>
        {BROLL_SOURCE_OPTIONS.map((opt) => {
          const active = opt.id === source;
          return (
            <Pressable
              key={opt.id}
              style={[styles.sourceChip, active && styles.sourceChipActive]}
              onPress={() => setSource(opt.id)}
              disabled={busy}
              accessibilityRole="button"
              accessibilityState={{ selected: active, disabled: busy }}
            >
              <Text
                style={[
                  styles.sourceChipText,
                  active && styles.sourceChipTextActive,
                ]}
              >
                {opt.name}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <Pressable
        style={[styles.suggest, busy && styles.disabled]}
        onPress={() => void loadSuggestions()}
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel="Suggest B-roll clips for this reel"
      >
        {busy ? (
          <ActivityIndicator color="#E6C76A" />
        ) : (
          <Text style={styles.suggestText}>
            {state.status === "ready" || state.status === "error"
              ? "Suggest more clips"
              : "Suggest clips"}
          </Text>
        )}
      </Pressable>

      {state.status === "error" ? (
        <Text style={styles.error}>{state.message}</Text>
      ) : null}

      {state.status === "ready" ? (
        state.clips.length === 0 ? (
          <Text style={styles.empty}>
            No stock clips came back for this reel. Try the other source.
          </Text>
        ) : (
          <FlatList
            horizontal
            data={state.clips}
            keyExtractor={(item, index) => `${item.key}:${index}`}
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.list}
            renderItem={({ item }) => (
              <BrollClipThumb
                clip={item}
                introSelected={introKey === item.key}
                outroSelected={outroKey === item.key}
                disabled={busy}
                onToggleIntro={() => toggleIntro(item)}
                onToggleOutro={() => toggleOutro(item)}
              />
            )}
          />
        )
      ) : null}

      {hasSelection ? (
        <View style={styles.selectionBox}>
          <Text style={styles.selectionText}>
            Intro: {introKey ? sourceLabel(source) + " clip" : "none"} · Outro:{" "}
            {outroKey ? sourceLabel(source) + " clip" : "none"}
          </Text>
          <Text style={styles.selectionHint}>
            Selected cutaways apply the next time you create or re-run this reel.
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10, marginTop: 8 },
  subtitle: { color: "#8b8b9b", fontSize: 13, lineHeight: 18 },
  sourceRow: { flexDirection: "row", gap: 8, marginTop: 2 },
  sourceChip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  sourceChipActive: { borderColor: "#E6C76A", backgroundColor: "#2a2416" },
  sourceChipText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  sourceChipTextActive: { color: "#E6C76A" },
  suggest: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  suggestText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  list: { gap: 12, paddingVertical: 2, paddingRight: 4 },
  error: { color: "#E0847F", fontSize: 14 },
  empty: { color: "#6f6c65", fontSize: 13 },
  selectionBox: {
    backgroundColor: "#101018",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  selectionText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  selectionHint: { color: "#6f6c65", fontSize: 12, lineHeight: 16 },
});
