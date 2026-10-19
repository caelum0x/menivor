/**
 * Route: /studio/design/[id] — one design on mobile. Live preview of every
 * page, edit the title and every text layer, save, duplicate or delete, and
 * export: open the PNG pages that were exported, or hand off to the web editor
 * to render fresh PNGs (the phone has no pixel-exact renderer for the brand
 * fonts, and the server only accepts exact-size PNG pages).
 *
 * Backed by GET/PATCH/DELETE /design/docs/{id} and POST …/duplicate.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";

import { DesignPreview } from "@/components/design-studio/DesignPreview";
import { Button, Chip, ErrorState, TextField } from "@/components/ui";
import {
  MAX_TEXT_CHARS,
  MAX_TITLE_CHARS,
  SIZE_LABELS,
  canvasChanged,
  deleteDesign,
  duplicateDesign,
  exportIsCurrent,
  getDesign,
  openableExports,
  saveDesign,
  textLayers,
  webEditorUrl,
  withLayerText,
  type Canvas,
  type DesignDoc,
} from "@/lib/design-studio";
import { readableApiMessage } from "@/lib/social-inbox";
import { ApiError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This design no longer exists.";
    if (err.status === 503) return "Design Studio is unavailable right now.";
    return readableApiMessage(err.message, fallback);
  }
  return err instanceof Error ? err.message : fallback;
}

export default function DesignDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const designId = String(id ?? "");
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();
  const { width: screenWidth } = useWindowDimensions();
  const previewWidth = Math.min(screenWidth - spacing.lg * 2, 480);

  const [doc, setDoc] = useState<DesignDoc | null>(null);
  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [title, setTitle] = useState("");
  const [pageIndex, setPageIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "save" | "duplicate" | "delete">("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const adopt = useCallback((next: DesignDoc) => {
    setDoc(next);
    setCanvas(next.canvas);
    setTitle(next.title);
    setPageIndex((i) => Math.min(i, Math.max(0, next.canvas.pages.length - 1)));
  }, []);

  const load = useCallback(async () => {
    if (!designId) return;
    setError(null);
    try {
      adopt(await getDesign(designId, { token }));
    } catch (err) {
      setError(describe(err, "Could not load this design."));
    }
  }, [adopt, designId, token]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    load().finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [load]);

  const dirty = useMemo(
    () => Boolean(doc && canvas && (canvasChanged(doc.canvas, canvas) || title.trim() !== doc.title)),
    [canvas, doc, title],
  );
  const pageTexts = useMemo(
    () => (canvas ? textLayers(canvas).filter((ref) => ref.pageIndex === pageIndex) : []),
    [canvas, pageIndex],
  );

  const onSave = useCallback(async () => {
    if (!doc || !canvas) return;
    setBusy("save");
    setActionError(null);
    setNotice(null);
    try {
      const next = await saveDesign(
        doc.id,
        { title: title.trim().slice(0, MAX_TITLE_CHARS) || undefined, canvas },
        { token },
      );
      adopt(next);
      setNotice("Saved.");
    } catch (err) {
      setActionError(describe(err, "Could not save the design."));
    } finally {
      setBusy("");
    }
  }, [adopt, canvas, doc, title, token]);

  const onDuplicate = useCallback(async () => {
    if (!doc) return;
    setBusy("duplicate");
    setActionError(null);
    try {
      const copy = await duplicateDesign(doc.id, { token });
      router.replace({ pathname: "/studio/design/[id]", params: { id: copy.id } });
    } catch (err) {
      setActionError(describe(err, "Could not duplicate the design."));
    } finally {
      setBusy("");
    }
  }, [doc, router, token]);

  const onDelete = useCallback(() => {
    if (!doc) return;
    Alert.alert("Delete design?", `${doc.title} will be removed. Exported PNGs stay in your uploads.`, [
      { text: "Keep", style: "cancel" },
      {
        text: "Delete",
        style: "destructive",
        onPress: () => {
          setBusy("delete");
          deleteDesign(doc.id, { token })
            .then(() => router.back())
            .catch((err) => setActionError(describe(err, "Could not delete the design.")))
            .finally(() => setBusy(""));
        },
      },
    ]);
  }, [doc, router, token]);

  const open = useCallback(async (url: string) => {
    try {
      await Linking.openURL(url);
    } catch {
      setActionError("Could not open that link.");
    }
  }, []);

  if (loading && !doc) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Design" }} />
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!doc || !canvas) {
    return (
      <View style={styles.center}>
        <Stack.Screen options={{ title: "Design" }} />
        <ErrorState message={error ?? "Could not load this design."} onRetry={load} />
      </View>
    );
  }

  const page = canvas.pages[pageIndex];
  const exports = openableExports(doc);
  const current = exportIsCurrent(doc) && !dirty;

  return (
    <ScrollView style={styles.flex} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Stack.Screen options={{ title: doc.title || "Design" }} />
      <Text style={styles.faint}>
        {SIZE_LABELS[doc.size_preset] ?? doc.size_preset} · {doc.width}x{doc.height}
      </Text>

      {canvas.pages.length > 1 ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {canvas.pages.map((_, i) => (
            <Chip key={i} label={`Page ${i + 1}`} active={pageIndex === i} onPress={() => setPageIndex(i)} />
          ))}
        </ScrollView>
      ) : null}
      {page ? (
        <DesignPreview
          page={page}
          width={doc.width}
          height={doc.height}
          maxWidth={previewWidth}
          maxHeight={previewWidth * 1.5}
          token={token}
        />
      ) : null}
      <Text style={styles.faint}>Preview uses system fonts. Exported PNGs use your brand fonts.</Text>

      <Text style={styles.section}>Text</Text>
      <TextField label="Design name" value={title} onChangeText={setTitle} maxLength={MAX_TITLE_CHARS} />
      {pageTexts.length === 0 ? (
        <Text style={styles.faint}>This page has no text layers.</Text>
      ) : (
        pageTexts.map(({ layer }) => (
          <TextField
            key={layer.id}
            label={layer.name}
            value={layer.props.text}
            onChangeText={(text) => setCanvas((prev) => (prev ? withLayerText(prev, pageIndex, layer.id, text) : prev))}
            multiline={layer.props.text.length > 40}
            maxLength={MAX_TEXT_CHARS}
          />
        ))
      )}
      {actionError ? <Text style={styles.error}>{actionError}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}
      <View style={styles.row}>
        <Button label="Save" loading={busy === "save"} disabled={busy !== "" || !dirty} onPress={onSave} />
        {dirty ? (
          <Button
            label="Discard changes"
            variant="ghost"
            disabled={busy !== ""}
            onPress={() => {
              setCanvas(doc.canvas);
              setTitle(doc.title);
            }}
          />
        ) : null}
      </View>

      <Text style={styles.section}>Export</Text>
      {exports.length > 0 ? (
        <View style={styles.exportBox}>
          <Text style={styles.body}>
            {current
              ? "Your PNGs match this design. Open a page to save or share it."
              : "These PNGs are from an earlier version. Render them again after your edits."}
          </Text>
          <View style={styles.row}>
            {exports.map((e) => (
              <Button
                key={e.page}
                label={`Open PNG ${e.page}`}
                variant="secondary"
                size="sm"
                onPress={() => open(e.url)}
              />
            ))}
          </View>
        </View>
      ) : (
        <Text style={styles.body}>Not exported yet.</Text>
      )}
      {!current ? (
        <>
          <Text style={styles.faint}>
            PNG pages are rendered in the web editor so text uses your brand fonts at full resolution. Save here
            first, then open the design on the web and choose Export PNG.
          </Text>
          <Button
            label="Open in web editor"
            variant="secondary"
            size="sm"
            disabled={dirty}
            onPress={() => open(webEditorUrl(doc.id))}
          />
          {dirty ? <Text style={styles.faint}>Save your changes before exporting.</Text> : null}
        </>
      ) : null}

      <Text style={styles.section}>Manage</Text>
      <View style={styles.row}>
        <Button
          label="Duplicate"
          variant="secondary"
          size="sm"
          loading={busy === "duplicate"}
          disabled={busy !== ""}
          onPress={onDuplicate}
        />
        <Button
          label="Delete"
          variant="destructive"
          size="sm"
          loading={busy === "delete"}
          disabled={busy !== ""}
          onPress={onDelete}
        />
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.bg, padding: spacing.lg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxl },
  section: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700", marginTop: spacing.sm },
  chips: { gap: spacing.sm, paddingRight: spacing.lg },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  faint: { color: colors.textFaint, fontSize: typeScale.micro, lineHeight: 16 },
  body: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption },
  notice: { color: colors.success, fontSize: typeScale.caption },
  exportBox: {
    gap: spacing.sm,
    padding: spacing.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
  },
});
