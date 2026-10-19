/**
 * One Ad Studio project: rename, edit or rewrite the ad angles, build a
 * render batch (with a credit estimate), and review the rendered ads with
 * polling, retry, avatar-reel start and caption export.
 *
 * The native port of apps/web/src/features/ad-studio/ProjectView.tsx +
 * ExportPanel.tsx over the same `/v1/ad-studio/*` API.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  RefreshControl,
  ScrollView,
  Share,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { Button, TextField } from "@/components/ui";
import { POLL_INTERVAL_MS } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import {
  captionsSheet,
  createVariants,
  deleteAdProject,
  deleteVariant,
  editableAngles,
  exportAdProject,
  forgetAvatarReelKey,
  getAdProject,
  isActive,
  regenerateAngles,
  retryVariant,
  startAvatarReel,
  updateAdProject,
  type AdAngle,
  type ProjectDetail,
  type VariantsInput,
} from "./api";
import { AnglesEditor } from "./components/AnglesEditor";
import { BatchBuilder } from "./components/BatchBuilder";
import { ProductCard } from "./components/ProductCard";
import { VariantGrid, type VariantActions } from "./components/VariantGrid";

type Busy = "" | "angles" | "regen" | "title" | "delete" | "export";

function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Try again.";
}

export interface ProjectScreenProps {
  readonly projectId: string;
}

export function ProjectScreen({ projectId }: ProjectScreenProps) {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [angles, setAngles] = useState<AdAngle[]>([]);
  const [anglesDirty, setAnglesDirty] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<Busy>("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = anglesDirty;

  const load = useCallback(async () => {
    try {
      const data = await getAdProject(projectId, { token });
      setProject(data);
      setTitle((current) => current || data.title);
      // Keep unsaved angle edits through a background poll.
      if (!dirtyRef.current) setAngles(data.angles);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  }, [projectId, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const polling = project?.variants.some((v) => isActive(v.status)) ?? false;
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => {
      if (AppState.currentState === "active") void load();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [polling, load]);

  const guarded = async (kind: Busy, fn: () => Promise<void>) => {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  };

  const saveAngles = () =>
    guarded("angles", async () => {
      await updateAdProject(projectId, { angles: editableAngles(angles) }, { token });
      setAnglesDirty(false);
      dirtyRef.current = false;
      await load();
      setNotice("Angles saved.");
    });

  const regenerate = () =>
    guarded("regen", async () => {
      const data = await regenerateAngles(projectId, { use_llm: true }, { token });
      setAngles(data.angles);
      setAnglesDirty(false);
      dirtyRef.current = false;
      await load();
      setNotice("Angles rewritten.");
    });

  const rename = () =>
    guarded("title", async () => {
      await updateAdProject(projectId, { title: title.trim() }, { token });
      await load();
      setNotice("Project renamed.");
    });

  const remove = () => {
    Alert.alert(
      "Delete this ad project?",
      "Rendered videos stay in your uploads library.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () =>
            void guarded("delete", async () => {
              await deleteAdProject(projectId, { token });
              router.back();
            }),
        },
      ],
    );
  };

  const shareCaptions = () =>
    guarded("export", async () => {
      const manifest = await exportAdProject(projectId, { token });
      if (manifest.items.length === 0) {
        setNotice("No finished ads to export yet.");
        return;
      }
      await Share.share({ title: `${manifest.title}: post captions`, message: captionsSheet(manifest) });
      if (manifest.pending > 0) {
        setNotice(`${manifest.pending} ad${manifest.pending === 1 ? " is" : "s are"} still rendering and not in this export.`);
      }
    });

  const submitBatch = async (input: VariantsInput) => {
    if (anglesDirty) throw new Error("Save your angle edits before rendering.");
    await createVariants(projectId, input, { token });
    await load();
  };

  const actions: VariantActions = {
    onRetry: async (ad) => {
      await forgetAvatarReelKey(ad.id);
      await retryVariant(projectId, ad.id, { token }).catch((err: unknown) => setError(errorMessage(err)));
      await load();
    },
    onDelete: async (ad) => {
      await deleteVariant(projectId, ad.id, { token }).catch((err: unknown) => setError(errorMessage(err)));
      await load();
    },
    onStartAvatar: async (ad) => {
      await startAvatarReel(projectId, ad, { token }).catch((err: unknown) => setError(errorMessage(err)));
      await load();
    },
  };

  if (!project) {
    return (
      <View style={[styles.container, styles.center]}>
        {error ? (
          <>
            <Text style={styles.error}>{error}</Text>
            <Button label="Try again" variant="secondary" onPress={() => void load()} />
          </>
        ) : (
          <ActivityIndicator color={colors.accent} size="large" />
        )}
      </View>
    );
  }

  const readyCount = project.variants.filter((v) => v.status === "done").length;
  const disabled = busy !== "";

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void load();
          }}
          tintColor={colors.accent}
        />
      }
    >
      <TextField label="Project title" value={title} onChangeText={setTitle} maxLength={200} editable={!disabled} />
      <View style={styles.row}>
        <Button
          label="Rename"
          size="sm"
          variant="secondary"
          loading={busy === "title"}
          disabled={disabled || !title.trim() || title.trim() === project.title}
          onPress={() => void rename()}
        />
        <Button label="Delete project" size="sm" variant="destructive" disabled={disabled} onPress={remove} />
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.success}>{notice}</Text> : null}

      <ProductCard
        product={project.product}
        images={project.images.map((image) => image.url).filter((u): u is string => Boolean(u))}
      />

      <Text style={styles.sectionTitle}>Ad angles</Text>
      <AnglesEditor
        angles={angles}
        onChange={(next) => {
          setAngles(next);
          setAnglesDirty(true);
        }}
        disabled={disabled}
      />
      <View style={styles.row}>
        <Button
          label="Save angles"
          size="sm"
          loading={busy === "angles"}
          disabled={disabled || !anglesDirty}
          onPress={() => void saveAngles()}
        />
        <Button
          label="Rewrite with AI"
          size="sm"
          variant="secondary"
          loading={busy === "regen"}
          disabled={disabled}
          onPress={() => void regenerate()}
        />
      </View>
      <Text style={styles.muted}>
        Rewriting replaces the saved angles. Ads already rendered keep the copy they were made with.
      </Text>

      <Text style={styles.sectionTitle}>Render ads</Text>
      <BatchBuilder
        angles={project.angles}
        hasImages={project.images.length > 0}
        token={token}
        onSubmit={submitBatch}
      />

      <Text style={styles.sectionTitle}>Ads</Text>
      <View style={styles.exportCard}>
        <Text style={styles.body}>
          {readyCount} finished ad{readyCount === 1 ? "" : "s"}. Videos are also saved to your
          uploads library.
        </Text>
        <Button
          label="Share post captions"
          size="sm"
          variant="secondary"
          loading={busy === "export"}
          disabled={disabled || readyCount === 0}
          onPress={() => void shareCaptions()}
        />
      </View>
      <VariantGrid variants={project.variants} actions={actions} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  center: { alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xl },
  row: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.subheading,
    fontWeight: "700",
    marginTop: spacing.md,
  },
  exportCard: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 19 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 19 },
  success: { color: colors.success, fontSize: typeScale.caption },
});
