import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError, dubJob, listDubLanguages, me as fetchMe } from "@/lib/api";
import {
  DEFAULT_DUB_CREDIT_COST,
  type DubJobResult,
  type DubLanguage,
} from "@/lib/types";

import { LanguageChips } from "./LanguageChips";
import { FALLBACK_DUB_LANGUAGES, withDisplayNames } from "./languages";
import { Icon } from "@/components/ui/Icon";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

/**
 * "Dub into more languages" bottom sheet. From a finished source reel, the
 * creator multi-selects target languages; each selection re-translates the
 * source script and re-runs the pipeline (reusing recording/avatar/voice/layout/
 * caption style). All dubbed jobs share ONE `batch_id`. On success the created
 * batch is handed back to the caller for navigation. Selection is held
 * immutably (a Set of language codes).
 */
export interface DubSheetProps {
  visible: boolean;
  /** The finished source job to dub. */
  jobId: string;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  onClose: () => void;
  /** Called with the created batch after a successful dub. */
  onDone: (result: DubJobResult) => void;
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

function costOf(lang: DubLanguage): number {
  return typeof lang.credit_cost === "number" &&
    Number.isFinite(lang.credit_cost)
    ? lang.credit_cost
    : DEFAULT_DUB_CREDIT_COST;
}

export function DubSheet({
  visible,
  jobId,
  token,
  onClose,
  onDone,
}: Readonly<DubSheetProps>) {
  const [languages, setLanguages] =
    useState<readonly DubLanguage[]>(FALLBACK_DUB_LANGUAGES);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [credits, setCredits] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the supported languages + the caller's balance when the sheet opens.
  // Each source degrades independently so one failure doesn't blank the sheet.
  useEffect(() => {
    if (!visible) return;
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      listDubLanguages({ token }).catch(() => [] as DubLanguage[]),
      fetchMe({ token }).catch(() => null),
    ])
      .then(([langs, meResult]) => {
        if (!active) return;
        setLanguages(
          langs.length > 0
            ? langs.map(withDisplayNames)
            : FALLBACK_DUB_LANGUAGES,
        );
        setCredits(meResult ? meResult.credits : null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [visible, token]);

  // Reset the selection each time the sheet is reopened.
  useEffect(() => {
    if (visible) {
      setSelected(new Set());
      setError(null);
    }
  }, [visible]);

  const toggle = useCallback((code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const totalCost = useMemo(
    () =>
      languages
        .filter((l) => selected.has(l.code))
        .reduce((sum, l) => sum + costOf(l), 0),
    [languages, selected],
  );

  const selectedCount = selected.size;
  const insufficient = credits !== null && totalCost > credits;
  const canSubmit = selectedCount > 0 && !submitting && !insufficient;

  const handleSubmit = useCallback(async () => {
    if (selected.size === 0) return;
    setSubmitting(true);
    setError(null);
    // Preserve catalog order for a stable, predictable request.
    const codes = languages
      .map((l) => l.code)
      .filter((code) => selected.has(code));
    try {
      const result = await dubJob(jobId, codes, { token });
      onDone(result);
    } catch (err) {
      setError(describe(err, "Failed to start dubbing."));
      setSubmitting(false);
    }
  }, [jobId, languages, selected, token, onDone]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>Dub into more languages</Text>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Close"
              hitSlop={12}
            >
              <Icon name="close" style={styles.close} />
            </Pressable>
          </View>
          <Text style={styles.subtitle}>
            Translate this reel&apos;s script and re-render it in each language
            you pick — reusing the same recording, avatar, voice, layout and
            caption style. Each language is a separate reel; they render together
            as a batch.
          </Text>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
          >
            <Text style={styles.fieldLabel}>Target languages</Text>
            <LanguageChips
              languages={languages}
              selected={selected}
              onToggle={toggle}
              loading={loading}
              disabled={submitting}
            />
            <GenerationErrorNotice message={error} style={styles.error} />
          </ScrollView>

          <View style={styles.costRow}>
            <Text style={styles.costText}>
              {selectedCount === 0
                ? "Select at least one language"
                : `${selectedCount} language${
                    selectedCount === 1 ? "" : "s"
                  } · ${totalCost} credit${totalCost === 1 ? "" : "s"}`}
            </Text>
            {credits !== null ? (
              <Text
                style={[styles.balance, insufficient && styles.balanceLow]}
              >
                Balance: {credits}
              </Text>
            ) : null}
          </View>
          {insufficient ? (
            <Text style={styles.error}>
              Not enough credits for this selection.
            </Text>
          ) : null}

          <Pressable
            style={[styles.primary, !canSubmit && styles.disabled]}
            onPress={handleSubmit}
            disabled={!canSubmit}
            accessibilityRole="button"
          >
            {submitting ? (
              <ActivityIndicator color="#0f0f10" />
            ) : (
              <Text style={styles.primaryText}>
                {selectedCount > 0
                  ? `Dub ${selectedCount} language${
                      selectedCount === 1 ? "" : "s"
                    }`
                  : "Dub reel"}
              </Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: "#0f0f18",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingTop: 10,
    paddingBottom: 28,
    maxHeight: "88%",
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#27272a",
    marginBottom: 12,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  close: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  subtitle: { color: "#8b8b9b", fontSize: 13, marginTop: 6, lineHeight: 18 },
  scroll: { marginTop: 12 },
  scrollContent: { gap: 12, paddingBottom: 8 },
  fieldLabel: { color: "#ece9e1", fontSize: 15, fontWeight: "600" },
  error: { color: "#E0847F", fontSize: 14 },
  costRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
    marginBottom: 8,
  },
  costText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  balance: { color: "#6f6c65", fontSize: 13 },
  balanceLow: { color: "#ff9a9a" },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: "#0f0f10", fontSize: 16, fontWeight: "700" },
});
