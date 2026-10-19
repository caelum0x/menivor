import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { ApiError, generateCover, listCoverStyles } from "@/lib/api";
import { toDisplayUrl } from "@/src/shared/media";
import type { CoverResult, CoverStyle } from "@/lib/types";

import { CoverStyleChips } from "./CoverStyleChips";
import { saveOrShareCover } from "./cover-share";
import {
  DEFAULT_COVER_STYLE_ID,
  FALLBACK_COVER_STYLES,
  withStyleName,
} from "./cover-styles";
import { Icon } from "@/components/ui/Icon";
import { GenerationErrorNotice } from "@/components/billing/GenerationErrorNotice";

/** Max headline length accepted by the input (kept generous; backend clamps). */
const MAX_HEADLINE = 120;

/**
 * "Cover" bottom sheet. For any job, the creator types a headline (defaults to
 * the job's HOOK server-side when left blank), picks a style, and taps Generate
 * to render a 1080x1920 cover image (POST /jobs/{id}/cover). The rendered cover
 * is shown inline with a Save / Share action, and can be regenerated with a
 * different headline/style. Selection + input are held immutably in state.
 */
export interface CoverSheetProps {
  visible: boolean;
  /** The job to generate a cover for. */
  jobId: string;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  /** Prefills the headline input (e.g. the job's HOOK), when known. */
  defaultHeadline?: string;
  /** An already-generated cover URL to show on open, when known. */
  initialCoverUrl?: string;
  onClose: () => void;
  /** Called with the fresh cover after a successful generation. */
  onGenerated?: (result: CoverResult) => void;
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

/** Prefers a presigned `cover_url`, else resolves `cover_key` if it is a URL. */
function coverUrlOf(result: CoverResult): string | undefined {
  return toDisplayUrl(result.cover_url) ?? toDisplayUrl(result.cover_key);
}

export function CoverSheet({
  visible,
  jobId,
  token,
  defaultHeadline = "",
  initialCoverUrl,
  onClose,
  onGenerated,
}: Readonly<CoverSheetProps>) {
  const [styles_, setStyles] =
    useState<readonly CoverStyle[]>(FALLBACK_COVER_STYLES);
  const [styleId, setStyleId] = useState<string>(DEFAULT_COVER_STYLE_ID);
  const [headline, setHeadline] = useState<string>(defaultHeadline);
  const [coverUrl, setCoverUrl] = useState<string | undefined>(initialCoverUrl);

  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [imageErrored, setImageErrored] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load the style catalog when the sheet opens; degrade to the local fallback.
  useEffect(() => {
    if (!visible) return;
    let active = true;
    setLoading(true);
    setError(null);
    listCoverStyles({ token })
      .then((fetched) => {
        if (!active) return;
        setStyles(
          fetched.length > 0
            ? fetched.map(withStyleName)
            : FALLBACK_COVER_STYLES,
        );
      })
      .catch(() => {
        if (active) setStyles(FALLBACK_COVER_STYLES);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [visible, token]);

  // Reset transient state each time the sheet is reopened.
  useEffect(() => {
    if (visible) {
      setHeadline(defaultHeadline);
      setCoverUrl(initialCoverUrl);
      setStyleId(DEFAULT_COVER_STYLE_ID);
      setImageErrored(false);
      setError(null);
    }
  }, [visible, defaultHeadline, initialCoverUrl]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    setImageErrored(false);
    const trimmed = headline.trim();
    try {
      const result = await generateCover(
        jobId,
        // Omit an empty headline so the backend falls back to the job's HOOK.
        { style: styleId, ...(trimmed ? { headline: trimmed } : {}) },
        { token },
      );
      const url = coverUrlOf(result);
      setCoverUrl(url);
      onGenerated?.(result);
      if (!url) {
        setError("Cover generated, but no preview URL was returned.");
      }
    } catch (err) {
      setError(describe(err, "Failed to generate cover."));
    } finally {
      setGenerating(false);
    }
  }, [jobId, headline, styleId, token, onGenerated]);

  const handleShare = useCallback(async () => {
    if (!coverUrl) return;
    setSharing(true);
    setError(null);
    try {
      await saveOrShareCover({ url: coverUrl, jobId });
    } catch (err) {
      setError(describe(err, "Couldn't open the share sheet."));
    } finally {
      setSharing(false);
    }
  }, [coverUrl, jobId]);

  const busy = generating || sharing;
  const showImage = Boolean(coverUrl) && !imageErrored;

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
            <Text style={styles.title}>Cover</Text>
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
            Turn this reel into a scroll-stopping cover — your hook as a bold
            headline over the poster frame. Regenerate any time with a different
            headline or style.
          </Text>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
            keyboardShouldPersistTaps="handled"
          >
            <Text style={styles.fieldLabel}>Headline</Text>
            <TextInput
              style={styles.input}
              value={headline}
              onChangeText={setHeadline}
              placeholder="Leave blank to use the reel's hook"
              placeholderTextColor="#5a5a6b"
              multiline
              maxLength={MAX_HEADLINE}
              editable={!busy}
              accessibilityLabel="Cover headline"
            />
            <Text style={styles.counter}>
              {headline.length}/{MAX_HEADLINE}
            </Text>

            <Text style={styles.fieldLabel}>Style</Text>
            <CoverStyleChips
              styles={styles_}
              value={styleId}
              onChange={setStyleId}
              loading={loading}
              disabled={busy}
            />

            {showImage ? (
              <>
                <Text style={styles.fieldLabel}>Preview</Text>
                <Image
                  source={{ uri: coverUrl }}
                  style={styles.preview}
                  resizeMode="cover"
                  accessibilityLabel="Generated cover image"
                  onError={() => setImageErrored(true)}
                />
                <Pressable
                  style={[styles.secondary, sharing && styles.disabled]}
                  onPress={handleShare}
                  disabled={busy}
                  accessibilityRole="button"
                  accessibilityLabel="Save or share the cover"
                >
                  {sharing ? (
                    <ActivityIndicator color="#E6C76A" />
                  ) : (
                    <Text style={styles.secondaryText}>Save / Share</Text>
                  )}
                </Pressable>
              </>
            ) : null}

            {coverUrl && imageErrored ? (
              <Text style={styles.hint}>
                Couldn&apos;t load the cover preview. Try generating again.
              </Text>
            ) : null}

            <GenerationErrorNotice message={error} style={styles.error} />
          </ScrollView>

          <Pressable
            style={[styles.primary, busy && styles.disabled]}
            onPress={handleGenerate}
            disabled={busy}
            accessibilityRole="button"
          >
            {generating ? (
              <ActivityIndicator color="#0f0f10" />
            ) : (
              <Text style={styles.primaryText}>
                {coverUrl ? "Regenerate cover" : "Generate cover"}
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
    maxHeight: "90%",
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
  scrollContent: { gap: 10, paddingBottom: 12 },
  fieldLabel: {
    color: "#ece9e1",
    fontSize: 15,
    fontWeight: "600",
    marginTop: 6,
  },
  input: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: "#ece9e1",
    fontSize: 15,
    minHeight: 64,
    textAlignVertical: "top",
  },
  counter: { color: "#6f6c65", fontSize: 12, alignSelf: "flex-end" },
  preview: {
    width: "100%",
    aspectRatio: 9 / 16,
    borderRadius: 12,
    backgroundColor: "#000000",
  },
  hint: { color: "#E6C76A", fontSize: 13 },
  error: { color: "#E0847F", fontSize: 14 },
  secondary: {
    backgroundColor: "#0f0f10",
    borderColor: "#E6C76A",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  secondaryText: { color: "#E6C76A", fontSize: 15, fontWeight: "700" },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 12,
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: "#0f0f10", fontSize: 16, fontWeight: "700" },
});
