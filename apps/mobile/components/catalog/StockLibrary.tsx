/**
 * Shared screen body for a legacy MoneyPrinterTurbo standalone stock library —
 * the background-music library (`GET/POST /musics`) or the local video-materials
 * library (`GET/POST /video_materials`).
 *
 * Both libraries have the identical `StockLibraryFile` shape and the identical
 * flow (list with pull-to-refresh + search, upload a new file with client-side
 * validation, per-file detail), so this component is generic over the two and
 * the route screens supply only the api functions, the picker, and copy.
 *
 * Behaviour:
 *  - GET on mount + pull-to-refresh (loading / empty / error+retry states).
 *  - Upload: pick a file → validate extension (and size) → confirm → POST with
 *    live progress → reload the list and show a success banner. All failures
 *    surface an inline, user-facing message; nothing is swallowed.
 *  - Tapping a row opens a detail dialog (name, size, the exact basename a
 *    render job references).
 */

import type { ReactElement } from "react";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { CatalogList } from "@/components/catalog/CatalogList";
import { useCatalogResource } from "@/components/catalog/use-catalog-resource";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import type { LocalFile, RequestOptions } from "@/lib/api";
import type { StockLibraryFile, StockLibraryUploadResult } from "@/lib/types";
import { extensionOf } from "@/src/shared/media";

type UploadOptions = RequestOptions & { onProgress?: (fraction: number) => void };

export interface StockLibraryProps {
  /** Per-user API key (falls back to the public app key inside the client). */
  token: string | undefined;
  /** GET the current library contents. */
  listFiles: (options?: RequestOptions) => Promise<StockLibraryFile[]>;
  /** POST a picked file to the library. */
  uploadFile: (
    file: LocalFile,
    options?: UploadOptions,
  ) => Promise<StockLibraryUploadResult>;
  /** Open the system picker for this library's file type. */
  pickFile: () => Promise<LocalFile | null>;
  /** Extensions the backend accepts (lower-case, no dot) — validated client-side. */
  allowedExtensions: readonly string[];
  /** Optional hard size cap in bytes (e.g. 30 MB for BGM). */
  maxSizeBytes?: number;
  /** Intro copy shown above the list. */
  intro: string;
  /** Human hint of what can be uploaded, shown on the upload card. */
  acceptHint: string;
  /** Singular noun for one entry, e.g. "track" or "clip". */
  itemNoun: string;
  /** Body copy for the empty state. */
  emptyBody: string;
}

type UploadPhase = "idle" | "uploading";

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "—";
  const megabytes = value / (1024 * 1024);
  if (megabytes >= 1) return `${megabytes.toFixed(megabytes >= 10 ? 1 : 2)} MB`;
  return `${Math.max(1, Math.round(value / 1024))} KB`;
}

export function StockLibrary({
  token,
  listFiles,
  uploadFile,
  pickFile,
  allowedExtensions,
  maxSizeBytes,
  intro,
  acceptHint,
  itemNoun,
  emptyBody,
}: StockLibraryProps): ReactElement {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const fetcher = useCallback(() => listFiles({ token }), [listFiles, token]);
  const { status, data, error, refreshing, reload, refresh } =
    useCatalogResource<StockLibraryFile[]>(fetcher);

  const items = useMemo<StockLibraryFile[]>(() => {
    const all = data ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (f) =>
        f.name.toLowerCase().includes(q) || f.file.toLowerCase().includes(q),
    );
  }, [data, query]);

  const runUpload = useCallback(
    async (file: LocalFile): Promise<void> => {
      setUploadError(null);
      setBanner(null);
      setProgress(0);
      setPhase("uploading");
      try {
        const result = await uploadFile(file, { token, onProgress: setProgress });
        setBanner(`Uploaded "${result.file}".`);
        reload();
      } catch (err) {
        setUploadError(describeError(err, "The upload failed. Please try again."));
      } finally {
        setPhase("idle");
      }
    },
    [uploadFile, token, reload],
  );

  const onPickAndUpload = useCallback(async (): Promise<void> => {
    setUploadError(null);
    setBanner(null);
    let picked: LocalFile | null;
    try {
      picked = await pickFile();
    } catch (err) {
      setUploadError(describeError(err, "Could not open the file picker."));
      return;
    }
    if (!picked) return;

    const ext = extensionOf(picked.name);
    if (!allowedExtensions.includes(ext)) {
      setUploadError(
        `"${picked.name}" is not a supported format. Allowed: ${allowedExtensions
          .join(", ")
          .toUpperCase()}.`,
      );
      return;
    }
    if (maxSizeBytes && picked.size > maxSizeBytes) {
      setUploadError(
        `"${picked.name}" is ${formatBytes(picked.size)} — over the ${formatBytes(
          maxSizeBytes,
        )} limit.`,
      );
      return;
    }

    Alert.alert(
      "Upload file",
      `Add "${picked.name}" (${formatBytes(picked.size)}) to the library?`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Upload", onPress: () => void runUpload(picked as LocalFile) },
      ],
    );
  }, [pickFile, allowedExtensions, maxSizeBytes, runUpload]);

  const onOpenDetail = useCallback(
    (file: StockLibraryFile): void => {
      Alert.alert(
        file.name,
        `Size: ${formatBytes(file.size)}\nReference: ${file.file}\n\nThis is the exact filename a render job uses to pull this ${itemNoun}.`,
        [{ text: "Done" }],
      );
    },
    [itemNoun],
  );

  const uploading = phase === "uploading";

  const renderItem = useCallback(
    (file: StockLibraryFile): ReactElement => (
      <Pressable
        style={styles.card}
        onPress={() => onOpenDetail(file)}
        accessibilityRole="button"
      >
        <View style={styles.info}>
          <Text style={styles.name} numberOfLines={1}>
            {file.name}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {formatBytes(file.size)} · {file.file}
          </Text>
        </View>
        <Text style={styles.detailHint}>Details</Text>
      </Pressable>
    ),
    [onOpenDetail],
  );

  const header = (
    <View>
      <View style={styles.uploadCard}>
        <Text style={styles.uploadTitle}>Add a file</Text>
        <Text style={styles.uploadHint}>{acceptHint}</Text>
        <Pressable
          style={[styles.uploadBtn, uploading && styles.uploadBtnDisabled]}
          onPress={() => void onPickAndUpload()}
          disabled={uploading}
          accessibilityRole="button"
        >
          {uploading ? (
            <View style={styles.uploadingRow}>
              <ActivityIndicator color={colors.bg} size="small" />
              <Text style={styles.uploadBtnText}>
                Uploading {Math.round(progress * 100)}%
              </Text>
            </View>
          ) : (
            <Text style={styles.uploadBtnText}>Choose file</Text>
          )}
        </Pressable>
        {banner ? <Text style={styles.successText}>{banner}</Text> : null}
        {uploadError ? <Text style={styles.errorText}>{uploadError}</Text> : null}
      </View>

      <TextInput
        style={styles.search}
        placeholder={`Search ${itemNoun}s…`}
        placeholderTextColor={colors.muted}
        value={query}
        onChangeText={setQuery}
        autoCapitalize="none"
        autoCorrect={false}
      />
    </View>
  );

  return (
    <CatalogList<StockLibraryFile>
      status={status}
      error={error}
      items={items}
      keyExtractor={(f) => f.file}
      renderItem={renderItem}
      onRetry={reload}
      refreshing={refreshing}
      onRefresh={refresh}
      intro={intro}
      header={header}
      emptyTitle={query ? "No matches" : `No ${itemNoun}s yet`}
      emptyBody={
        query
          ? "No files match your search. Try a different term."
          : emptyBody
      }
      loadingLabel="Loading library…"
    />
  );
}

const styles = StyleSheet.create({
  uploadCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
    gap: 8,
  },
  uploadTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  uploadHint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  uploadBtn: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 4,
  },
  uploadBtnDisabled: { opacity: 0.7 },
  uploadingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  uploadBtnText: { color: colors.bg, fontSize: 14, fontWeight: "700" },
  successText: { color: colors.success, fontSize: 13 },
  errorText: { color: colors.error, fontSize: 13 },
  search: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: colors.textPrimary,
    fontSize: 15,
    marginBottom: 14,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  info: { flex: 1, gap: 3 },
  name: { color: colors.textPrimary, fontSize: 15, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
  detailHint: { color: colors.accent, fontSize: 13, fontWeight: "600" },
});
