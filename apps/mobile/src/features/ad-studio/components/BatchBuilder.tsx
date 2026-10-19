/**
 * Pick angles x formats x aspect ratios (+ avatar and voice for UGC ads) and
 * queue the batch, with a live count and a reel-credit estimate before
 * anything is spent.
 */

import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { Button, Chip, SelectField } from "@/components/ui";
import { listAvatars, listVoices } from "@/lib/api";
import { avatarSelectId, type Avatar, type Voice } from "@/lib/types";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

import {
  AD_ASPECTS,
  AD_FORMATS,
  describeBatch,
  estimateBatch,
  toggleIn,
  type AdAngle,
  type AdAspect,
  type AdFormat,
  type VariantsInput,
} from "../api";

export interface BatchBuilderProps {
  readonly angles: readonly AdAngle[];
  readonly hasImages: boolean;
  readonly token: string | undefined;
  readonly onSubmit: (input: VariantsInput) => Promise<void>;
}

function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
}

export function BatchBuilder({ angles, hasImages, token, onSubmit }: BatchBuilderProps) {
  const [angleIds, setAngleIds] = useState<string[]>(() => angles.slice(0, 3).map((a) => a.id));
  const [formats, setFormats] = useState<AdFormat[]>(["showcase"]);
  const [aspects, setAspects] = useState<AdAspect[]>(["9:16"]);
  const [avatars, setAvatars] = useState<Avatar[] | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [avatarId, setAvatarId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const wantsAvatar = formats.includes("ugc_avatar");

  // Drop selections for angles that no longer exist (after a rewrite).
  useEffect(() => {
    setAngleIds((current) => {
      const kept = current.filter((id) => angles.some((a) => a.id === id));
      return kept.length > 0 ? kept : angles.slice(0, 3).map((a) => a.id);
    });
  }, [angles]);

  useEffect(() => {
    if (!wantsAvatar || avatars !== null) return;
    const controller = new AbortController();
    const options = { token, signal: controller.signal };
    Promise.all([listAvatars(options), listVoices(options).catch(() => [] as Voice[])])
      .then(([a, v]) => {
        const usable = a.filter((avatar) => avatar.is_active !== false && avatarSelectId(avatar));
        setAvatars(usable);
        setVoices(v);
        const first = usable[0];
        if (first) setAvatarId((current) => current || avatarSelectId(first));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setAvatars([]);
        setError(errorText(err));
      });
    return () => controller.abort();
  }, [wantsAvatar, avatars, token]);

  const estimate = estimateBatch(angleIds.length, formats, aspects.length);
  const invalid =
    !hasImages || estimate.total === 0 || estimate.overLimit || (wantsAvatar && !avatarId);

  const submit = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await onSubmit({
        angle_ids: angleIds,
        formats,
        aspects,
        ...(wantsAvatar ? { avatar_id: avatarId, ...(voiceId ? { voice_id: voiceId } : {}) } : {}),
      });
      setNotice(`${estimate.total} ad${estimate.total === 1 ? "" : "s"} queued. They appear below as they render.`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <Text style={styles.label}>Angles</Text>
      <View style={styles.chips}>
        {angles.map((angle) => (
          <Chip
            key={angle.id}
            label={angle.label}
            active={angleIds.includes(angle.id)}
            onPress={() => setAngleIds(toggleIn(angleIds, angle.id))}
          />
        ))}
      </View>

      <Text style={styles.label}>Formats</Text>
      <View style={styles.formats}>
        {AD_FORMATS.map((format) => {
          const selected = formats.includes(format.id);
          return (
            <View key={format.id} style={[styles.format, selected && styles.formatSelected]}>
              <Chip
                label={format.label}
                active={selected}
                onPress={() => setFormats(toggleIn(formats, format.id))}
              />
              <Text style={styles.muted}>{format.detail}</Text>
            </View>
          );
        })}
      </View>

      <Text style={styles.label}>Aspect ratios</Text>
      <View style={styles.chips}>
        {AD_ASPECTS.map((aspect) => (
          <Chip
            key={aspect.id}
            label={aspect.label}
            active={aspects.includes(aspect.id)}
            onPress={() => setAspects(toggleIn(aspects, aspect.id))}
          />
        ))}
      </View>

      {wantsAvatar ? (
        <View style={styles.avatarBlock}>
          {avatars === null ? <Text style={styles.muted}>Loading avatars...</Text> : null}
          {avatars?.length === 0 ? (
            <Text style={styles.muted}>No avatars are available on this server yet.</Text>
          ) : null}
          {avatars && avatars.length > 0 ? (
            <SelectField
              label="Avatar"
              value={avatarId}
              onChange={setAvatarId}
              options={avatars.map((a) => ({
                value: avatarSelectId(a),
                label: a.display_name || a.name || avatarSelectId(a),
              }))}
            />
          ) : null}
          {avatars && avatars.length > 0 ? (
            <SelectField
              label="Voice"
              value={voiceId}
              onChange={setVoiceId}
              options={[
                { value: "", label: "Avatar default voice" },
                ...voices
                  .filter((v) => v.voice_id)
                  .map((v) => ({ value: v.voice_id, label: v.name || v.voice_id })),
              ]}
            />
          ) : null}
        </View>
      ) : null}

      <View style={styles.estimate}>
        <Text style={styles.body}>{describeBatch(estimate)}</Text>
        {!hasImages ? (
          <Text style={styles.muted}>This project has no product images to render from.</Text>
        ) : null}
        {estimate.credits > 0 ? (
          <Text style={styles.muted}>
            Avatar reels start one at a time from each ad below, and a failed render refunds its
            credit automatically.
          </Text>
        ) : null}
      </View>

      <Button
        label={`Render ${estimate.total} ad${estimate.total === 1 ? "" : "s"}`}
        loading={busy}
        disabled={invalid}
        onPress={() => void submit()}
      />
      {notice ? <Text style={styles.success}>{notice}</Text> : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  label: { color: colors.textPrimary, fontSize: typeScale.caption, fontWeight: "700", marginTop: spacing.xs },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  formats: { gap: spacing.sm },
  format: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm,
    gap: spacing.xs,
  },
  formatSelected: { borderColor: colors.accent },
  avatarBlock: { gap: spacing.xs },
  estimate: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    padding: spacing.sm,
    gap: spacing.xs,
  },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, fontWeight: "600", lineHeight: 19 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  success: { color: colors.success, fontSize: typeScale.caption },
  error: { color: colors.danger, fontSize: typeScale.caption },
});
