/**
 * BrandManager — the brand watermark editor. Loads the caller's settings (GET
 * /me/brand), lets them upload/replace/remove a transparent PNG logo, pick the
 * overlay corner, adjust opacity, and toggle the watermark on/off, then persists
 * the changed fields (PUT /me/brand) as a partial update. A live preview shows
 * where the logo lands. Mirrors the Me tab's section pattern (load / error /
 * ready) and keeps a local editable draft seeded from the server response.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";

import { describeError } from "@/components/me/errors";
import { Section, SectionState } from "@/components/me/Section";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";
import { getBrand, updateBrand } from "@/lib/api";
import {
  DEFAULT_WATERMARK_ENABLED,
  DEFAULT_WATERMARK_OPACITY,
  DEFAULT_WATERMARK_POSITION,
  type Brand,
  type BrandUpdate,
  type WatermarkPosition,
} from "@/lib/types";

import { BrandPreview } from "./BrandPreview";
import { LogoUploader } from "./LogoUploader";
import { OpacitySlider } from "./OpacitySlider";
import { PositionSelector } from "./PositionSelector";

interface BrandManagerProps {
  token: string | undefined;
}

interface Draft {
  logoKey: string;
  /** Local URI of a just-picked logo, shown until the saved logo_url refreshes. */
  logoPreviewUri: string | null;
  position: WatermarkPosition | string;
  opacity: number;
  enabled: boolean;
}

function draftFromBrand(brand: Brand): Draft {
  return {
    logoKey: brand.logo_key ?? "",
    logoPreviewUri: null,
    position: brand.position ?? DEFAULT_WATERMARK_POSITION,
    opacity:
      typeof brand.opacity === "number" ? brand.opacity : DEFAULT_WATERMARK_OPACITY,
    enabled:
      typeof brand.enabled === "boolean" ? brand.enabled : DEFAULT_WATERMARK_ENABLED,
  };
}

/** Builds the partial update carrying only the fields that changed from server. */
function diff(server: Brand, draft: Draft): BrandUpdate {
  const body: BrandUpdate = {};
  if (draft.logoKey !== (server.logo_key ?? "")) body.logo_key = draft.logoKey;
  if (draft.position !== server.position) body.position = draft.position;
  if (draft.opacity !== server.opacity) body.opacity = draft.opacity;
  if (draft.enabled !== server.enabled) body.enabled = draft.enabled;
  return body;
}

export function BrandManager({ token }: BrandManagerProps) {
  const fetcher = useCallback(() => getBrand({ token }), [token]);
  const { status, data, error, reload, setData } = useResource<Brand>(fetcher);

  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState(false);

  // Seed / re-seed the editable draft whenever the server data changes.
  useEffect(() => {
    if (data) setDraft(draftFromBrand(data));
  }, [data]);

  const pending = useMemo(() => {
    if (!data || !draft) return {} as BrandUpdate;
    return diff(data, draft);
  }, [data, draft]);

  const isDirty = Object.keys(pending).length > 0;

  const patch = useCallback((next: Partial<Draft>) => {
    setSavedAt(false);
    setSaveError(null);
    setDraft((prev) => (prev ? { ...prev, ...next } : prev));
  }, []);

  const onUploaded = useCallback(
    (logoKey: string, previewUri: string) => {
      patch({ logoKey, logoPreviewUri: previewUri });
    },
    [patch],
  );

  const onRemove = useCallback(() => {
    patch({ logoKey: "", logoPreviewUri: null });
  }, [patch]);

  const onSave = useCallback(async () => {
    if (!data || !draft || !isDirty) return;
    setSaving(true);
    setSaveError(null);
    setSavedAt(false);
    try {
      const updated = await updateBrand(pending, { token });
      setData(() => updated);
      setDraft(draftFromBrand(updated));
      setSavedAt(true);
    } catch (err) {
      setSaveError(describeError(err, "Failed to save brand settings."));
    } finally {
      setSaving(false);
    }
  }, [data, draft, isDirty, pending, token, setData]);

  return (
    <View style={styles.container}>
      <SectionState status={status} error={error} onRetry={reload}>
        {draft ? (
          <View style={styles.body}>
            <View style={styles.previewRow}>
              <BrandPreview
                logoUrl={draft.logoPreviewUri ?? data?.logo_url}
                position={draft.position}
                opacity={draft.opacity}
                enabled={draft.enabled}
              />
              <View style={styles.enabledCard}>
                <View style={styles.enabledRow}>
                  <Text style={styles.enabledLabel}>Apply by default</Text>
                  <Switch
                    value={draft.enabled}
                    onValueChange={(enabled) => patch({ enabled })}
                    disabled={saving}
                    trackColor={{ false: colors.border, true: colors.primary }}
                    thumbColor={colors.textPrimary}
                  />
                </View>
                <Text style={styles.enabledHint}>
                  When on, your logo is overlaid on every new reel. Individual
                  jobs can still override or disable it.
                </Text>
              </View>
            </View>

            <Section title="LOGO">
              <LogoUploader
                token={token}
                currentLogoUrl={data?.logo_url}
                hasLogo={draft.logoKey.length > 0}
                onUploaded={onUploaded}
                onRemove={onRemove}
                disabled={saving}
              />
            </Section>

            <Section title="POSITION">
              <PositionSelector
                value={draft.position}
                onChange={(position) => patch({ position })}
                disabled={saving}
              />
            </Section>

            <Section title="OPACITY">
              <OpacitySlider
                value={draft.opacity}
                onChange={(opacity) => patch({ opacity })}
                disabled={saving}
              />
            </Section>

            {saveError ? <Text style={styles.error}>{saveError}</Text> : null}
            {savedAt && !isDirty ? (
              <Text style={styles.saved}>Saved</Text>
            ) : null}

            <Pressable
              style={[styles.button, (!isDirty || saving) && styles.buttonDisabled]}
              onPress={() => void onSave()}
              disabled={!isDirty || saving}
              accessibilityRole="button"
              accessibilityState={{ disabled: !isDirty || saving }}
            >
              {saving ? (
                <ActivityIndicator color={colors.textPrimary} />
              ) : (
                <Text style={styles.buttonText}>
                  {isDirty ? "Save changes" : "Saved"}
                </Text>
              )}
            </Pressable>
          </View>
        ) : null}
      </SectionState>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 4 },
  body: { gap: 8 },
  previewRow: { flexDirection: "row", gap: 14, marginBottom: 20, alignItems: "flex-start" },
  enabledCard: {
    flex: 1,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  enabledRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  enabledLabel: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  enabledHint: { color: colors.muted, fontSize: 12, lineHeight: 16 },
  error: { color: colors.error, fontSize: 13 },
  saved: { color: colors.success, fontSize: 13, fontWeight: "600" },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
});
