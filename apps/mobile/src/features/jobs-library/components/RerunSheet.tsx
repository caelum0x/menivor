import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  ApiError,
  listAvatars,
  listCaptionStyles,
  listLayouts,
  listMusic,
  listVoices,
  rerunJob,
} from "@/lib/api";
import {
  LAYOUTS,
  avatarLabel,
  avatarSelectId,
  type Avatar,
  type CaptionStyle,
  type Job,
  type LayoutOption,
  type MusicTrack,
  type RerunOverrides,
  type Voice,
} from "@/lib/types";

import { OptionChips, type ChipOption } from "./OptionChips";
import { colors } from "@/src/shared/theme";
import { Icon } from "@/components/ui/Icon";

/**
 * Jobs-library "Re-run with tweaks" sheet. Clones the source job's params, applies
 * only the fields the user changes (avatar / voice / layout / caption style /
 * music / language), calls `POST /jobs/{id}/rerun`, and hands the new job id
 * back to the caller for navigation. Overrides are held immutably; unset fields
 * reuse the source job's stored value.
 */

export interface RerunSheetProps {
  visible: boolean;
  job: Job;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  onClose: () => void;
  /** Called with the freshly created job id after a successful re-run. */
  onRerun: (newJobId: string) => void;
}

/** Fixed language choices (matches `Language` in lib/types). */
const LANGUAGE_OPTIONS: readonly ChipOption[] = [
  { id: "auto", label: "Auto" },
  { id: "tr", label: "Türkçe" },
  { id: "en", label: "English" },
];

const LAYOUT_FALLBACK: readonly ChipOption[] = LAYOUTS.map((l) => ({
  id: l,
  label: l,
}));

interface Catalogs {
  avatars: readonly ChipOption[];
  voices: readonly ChipOption[];
  captions: readonly ChipOption[];
  music: readonly ChipOption[];
  layouts: readonly ChipOption[];
}

const EMPTY_CATALOGS: Catalogs = {
  avatars: [],
  voices: [],
  captions: [],
  music: [],
  layouts: LAYOUT_FALLBACK,
};

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function RerunSheet({
  visible,
  job,
  token,
  onClose,
  onRerun,
}: Readonly<RerunSheetProps>) {
  const [overrides, setOverrides] = useState<RerunOverrides>({});
  const [catalogs, setCatalogs] = useState<Catalogs>(EMPTY_CATALOGS);
  const [loadingCatalogs, setLoadingCatalogs] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the option catalogs when the sheet opens. Each source degrades to an
  // empty list independently so one failing catalog doesn't blank the others.
  useEffect(() => {
    if (!visible) return;
    let active = true;
    setLoadingCatalogs(true);
    setError(null);
    Promise.all([
      listAvatars({ token }).catch(() => [] as Avatar[]),
      listVoices({ token }).catch(() => [] as Voice[]),
      listCaptionStyles({ token }).catch(() => [] as CaptionStyle[]),
      listMusic({ token }).catch(() => [] as MusicTrack[]),
      listLayouts({ token }).catch(() => [] as LayoutOption[]),
    ])
      .then(([avatars, voices, captions, music, layouts]) => {
        if (!active) return;
        setCatalogs({
          avatars: avatars.map((a) => ({
            id: avatarSelectId(a),
            label: avatarLabel(a),
          })),
          voices: voices.map((v) => ({
            id: v.voice_id,
            label: v.name || v.voice_id,
          })),
          captions: captions.map((c) => ({ id: c.id, label: c.name })),
          music: music.map((m) => ({ id: m.id, label: m.name })),
          layouts:
            layouts.length > 0
              ? layouts.map((l) => ({ id: String(l.id), label: l.name }))
              : LAYOUT_FALLBACK,
        });
      })
      .finally(() => {
        if (active) setLoadingCatalogs(false);
      });
    return () => {
      active = false;
    };
  }, [visible, token]);

  // Reset the pending tweaks each time the sheet is reopened.
  useEffect(() => {
    if (visible) {
      setOverrides({});
      setError(null);
    }
  }, [visible]);

  // Immutable single-field update: null clears the override (reuse source).
  const setField = useCallback(
    <K extends keyof RerunOverrides>(
      key: K,
      value: RerunOverrides[K] | null,
    ) => {
      setOverrides((prev) => {
        const next = { ...prev };
        if (value === null || value === undefined || value === "") {
          delete next[key];
        } else {
          next[key] = value;
        }
        return next;
      });
    },
    [],
  );

  const changeCount = Object.keys(overrides).length;

  const handleSubmit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const created = await rerunJob(job.job_id, overrides, { token });
      onRerun(created.job_id);
    } catch (err) {
      setError(describe(err, "Failed to start the re-run."));
      setSubmitting(false);
    }
  }, [job.job_id, overrides, token, onRerun]);

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
            <Text style={styles.title}>Re-run with tweaks</Text>
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
            Clone this reel&apos;s settings, adjust any option below, and render a
            fresh variant. Unchanged fields reuse the original. Costs 1 credit.
          </Text>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
          >
            <Field label="Layout">
              <OptionChips
                options={catalogs.layouts}
                value={(overrides.layout as string | undefined) ?? null}
                loading={loadingCatalogs}
                disabled={submitting}
                onChange={(v) => setField("layout", v)}
              />
            </Field>

            <Field label="Caption style">
              <OptionChips
                options={catalogs.captions}
                value={overrides.caption_style ?? null}
                loading={loadingCatalogs}
                disabled={submitting}
                onChange={(v) => setField("caption_style", v)}
              />
            </Field>

            <Field label="Background music">
              <OptionChips
                options={catalogs.music}
                value={overrides.music_id ?? null}
                loading={loadingCatalogs}
                disabled={submitting}
                onChange={(v) => setField("music_id", v)}
                emptyText="No music tracks available."
              />
            </Field>

            <Field label="Language">
              <OptionChips
                options={LANGUAGE_OPTIONS}
                value={(overrides.language as string | undefined) ?? null}
                disabled={submitting}
                onChange={(v) => setField("language", v)}
              />
            </Field>

            <Field label="Avatar">
              <OptionChips
                options={catalogs.avatars}
                value={overrides.avatar_id ?? null}
                loading={loadingCatalogs}
                disabled={submitting}
                onChange={(v) => setField("avatar_id", v)}
                emptyText="No avatars available."
              />
            </Field>

            <Field label="Voice">
              <OptionChips
                options={catalogs.voices}
                value={overrides.voice_id ?? null}
                loading={loadingCatalogs}
                disabled={submitting}
                onChange={(v) => setField("voice_id", v)}
                emptyText="No voices available."
              />
            </Field>

            {error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>

          <Text style={styles.tweakCount}>
            {changeCount > 0
              ? `${changeCount} tweak${changeCount === 1 ? "" : "s"} applied`
              : "No tweaks — re-renders as-is"}
          </Text>
          <Pressable
            style={[styles.primary, submitting && styles.disabled]}
            onPress={handleSubmit}
            disabled={submitting}
            accessibilityRole="button"
          >
            {submitting ? (
              <ActivityIndicator color={colors.onAccent} />
            ) : (
              <Text style={styles.primaryText}>Re-run job</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

interface FieldProps {
  label: string;
  children: ReactNode;
}

function Field({ label, children }: Readonly<FieldProps>) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.surface,
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
    backgroundColor: colors.border,
    marginBottom: 12,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  close: { color: colors.textSecondary, fontSize: 18, fontWeight: "700" },
  subtitle: { color: colors.textSecondary, fontSize: 13, marginTop: 6, lineHeight: 18 },
  scroll: { marginTop: 12 },
  scrollContent: { gap: 18, paddingBottom: 8 },
  field: { gap: 8 },
  fieldLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  error: { color: colors.danger, fontSize: 14 },
  tweakCount: { color: colors.textFaint, fontSize: 12, marginTop: 12, marginBottom: 8 },
  primary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: colors.onAccent, fontSize: 16, fontWeight: "700" },
});
