/**
 * CreateAvatarForm — turns a creator's selfie into a HeyGen talking-photo
 * avatar. Uploads the photo (SelfieUploader → R2 `image_key`), collects a
 * display name and an optional default narrator voice, then calls POST /avatars
 * (createAvatarFromPhoto). On success it hands the created avatar up to the
 * parent (which prepends it to the list) and resets the form.
 *
 * Owns its own submit lifecycle + error; the selfie upload lifecycle lives in
 * SelfieUploader.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { createAvatarFromPhoto } from "@/lib/api";
import type { CreateAvatarResult } from "@/lib/types";

import { AvatarVoicePicker } from "./AvatarVoicePicker";
import { SelfieUploader } from "./SelfieUploader";

interface CreateAvatarFormProps {
  token: string | undefined;
  /** Called with the created avatar preset after a successful POST /avatars. */
  onCreated: (avatar: CreateAvatarResult) => void;
}

export function CreateAvatarForm({ token, onCreated }: CreateAvatarFormProps) {
  const [imageKey, setImageKey] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [voiceName, setVoiceName] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !!imageKey && !submitting;

  const onUploaded = (key: string) => {
    setImageKey(key);
    setError(null);
  };

  const reset = () => {
    setImageKey(null);
    setDisplayName("");
    setVoiceName(null);
  };

  const onSubmit = async () => {
    if (!imageKey) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createAvatarFromPhoto(
        {
          image_key: imageKey,
          ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
          ...(voiceName ? { voice_name: voiceName } : {}),
        },
        { token },
      );
      onCreated(created);
      reset();
    } catch (err) {
      setError(describeError(err, "Failed to create the avatar."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.container}>
      <SelfieUploader
        token={token}
        hasImage={!!imageKey}
        onUploaded={onUploaded}
        disabled={submitting}
      />

      <Text style={styles.label}>Name</Text>
      <TextInput
        style={styles.input}
        value={displayName}
        onChangeText={setDisplayName}
        placeholder="e.g. My spokesperson"
        placeholderTextColor={colors.muted}
        editable={!submitting}
        maxLength={200}
      />

      <Text style={styles.label}>Default voice (optional)</Text>
      <AvatarVoicePicker
        token={token}
        value={voiceName}
        onSelect={setVoiceName}
        disabled={submitting}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={() => void onSubmit()}
        disabled={!canSubmit}
        accessibilityRole="button"
        accessibilityState={{ disabled: !canSubmit }}
      >
        {submitting ? (
          <ActivityIndicator color={colors.textPrimary} />
        ) : (
          <Text style={styles.buttonText}>Create avatar</Text>
        )}
      </Pressable>
      {!imageKey ? (
        <Text style={styles.meta}>Upload a photo above to continue.</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 10 },
  label: { color: colors.textSecondary, fontSize: 13, fontWeight: "600", marginTop: 4 },
  input: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  error: { color: colors.error, fontSize: 13 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: colors.textPrimary, fontWeight: "700", fontSize: 15 },
  meta: { color: colors.muted, fontSize: 12, textAlign: "center" },
});
