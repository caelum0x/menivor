/**
 * Studio · Edit Script
 *
 * Nav manifest: { route: "/studio/scripts/[id]", title: "Edit script" }
 *
 * The edit / refine / hand-off surface for a saved script. Loads a script from
 * the device library by id (loading / error / not-found states), lets the
 * creator edit the subject + narration text and save changes, "refine" it by
 * re-running `POST /api/v1/scripts` with an instruction (the current draft is
 * fed to the model as the base, behind a confirmation since it overwrites),
 * hand the script to the reel-create flow ("Use in a reel" → prefilled Create),
 * or delete it behind a confirmation.
 */

import { useCallback, useRef, useState } from "react";
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import {
  MAX_PROMPT_LEN,
  MAX_SUBJECT_LEN,
  generateScript,
  languageLabel,
  scriptStatsLine,
  validateSubject,
} from "@/lib/scripts";
import {
  deleteSavedScript,
  getSavedScript,
  updateSavedScript,
  type SavedScript,
} from "@/src/shared/product/script-library";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { StudioScreen } from "@/components/studio/StudioScreen";
import { Button, TextField } from "@/components/ui";

function firstParam(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return value[0] ?? "";
  return value ?? "";
}

type SaveState = "idle" | "saving";

export default function EditScriptScreen() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const params = useLocalSearchParams<{ id?: string | string[] }>();
  const id = firstParam(params.id);

  const [record, setRecord] = useState<SavedScript | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [error, setError] = useState("");

  const [subject, setSubject] = useState("");
  const [script, setScript] = useState("");
  const [refineInstruction, setRefineInstruction] = useState("");

  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [refining, setRefining] = useState(false);
  const [actionError, setActionError] = useState("");

  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!id) {
      setError("This script could not be found.");
      setStatus("error");
      return;
    }
    setStatus("loading");
    try {
      const found = await getSavedScript(id);
      if (!found) {
        setError("This script has been deleted or could not be found.");
        setStatus("error");
        return;
      }
      setRecord(found);
      setSubject(found.subject);
      setScript(found.script);
      setStatus("ready");
      setError("");
    } catch (err) {
      setError(describeError(err, "Failed to load the script."));
      setStatus("error");
    }
  }, [id]);

  // Load once when the screen is focused. Subsequent focuses keep local edits.
  useFocusEffect(
    useCallback(() => {
      if (!record) void load();
    }, [record, load]),
  );

  const dirty =
    record !== null &&
    (subject.trim() !== record.subject || script.trim() !== record.script);

  const onSave = useCallback(async () => {
    if (!record) return;
    const validationError = validateSubject(subject);
    if (validationError) {
      setActionError(validationError);
      return;
    }
    setActionError("");
    setSaveState("saving");
    try {
      const updated = await updateSavedScript(record.id, {
        subject: subject.trim(),
        script: script.trim(),
      });
      if (updated) {
        setRecord(updated);
        setSubject(updated.subject);
        setScript(updated.script);
      }
    } catch (err) {
      setActionError(describeError(err, "Failed to save changes."));
    } finally {
      setSaveState("idle");
    }
  }, [record, subject, script]);

  const performRefine = useCallback(async () => {
    if (!record) return;
    setActionError("");
    setRefining(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const instruction = refineInstruction.trim();
    // Feed the current draft to the model as the base to rework, plus the
    // creator's instruction, via the freeform style prompt.
    const stylePrompt = [
      instruction || "Tighten and improve this script while keeping its intent.",
      "",
      "Rework this existing script:",
      script.trim(),
    ].join("\n");

    try {
      const result = await generateScript(
        {
          video_subject: subject.trim() || record.subject,
          video_language: record.language,
          paragraph_number: record.paragraphs,
          video_script_prompt: stylePrompt.slice(0, MAX_PROMPT_LEN),
        },
        { token, signal: controller.signal },
      );
      const text = result.video_script.trim();
      if (!text) {
        setActionError("The model returned an empty script. Try again.");
        return;
      }
      setScript(text);
      setRefineInstruction("");
    } catch (err) {
      setActionError(describeError(err, "Failed to refine the script."));
    } finally {
      setRefining(false);
    }
  }, [record, refineInstruction, script, subject, token]);

  const confirmRefine = useCallback(() => {
    Alert.alert(
      "Refine script",
      "This replaces the current script with a reworked version. You can save or discard the result afterwards.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Refine", onPress: () => void performRefine() },
      ],
    );
  }, [performRefine]);

  const onUseInReel = useCallback(() => {
    if (!record) return;
    router.push({
      pathname: "/(tabs)/create",
      params: {
        prefill: "1",
        subject: subject.trim() || record.subject,
        script: script.trim(),
        language: record.language,
      },
    });
  }, [record, subject, script, router]);

  const performDelete = useCallback(async () => {
    if (!record) return;
    try {
      await deleteSavedScript(record.id);
      router.replace("/studio/scripts");
    } catch (err) {
      setActionError(describeError(err, "Failed to delete the script."));
    }
  }, [record, router]);

  const confirmDelete = useCallback(() => {
    if (!record) return;
    Alert.alert(
      "Delete script",
      `Delete "${record.subject}"? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: () => void performDelete(),
        },
      ],
    );
  }, [record, performDelete]);

  const busy = saveState === "saving" || refining;

  return (
    <StudioScreen
      status={status}
      error={error}
      onRetry={() => void load()}
      loadingLabel="Loading the script…"
    >
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          style={styles.flex}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          {record ? (
            <View style={styles.metaRow}>
              <View style={styles.langBadge}>
                <Text style={styles.langText}>
                  {languageLabel(record.language)}
                </Text>
              </View>
              <Text style={styles.meta}>{scriptStatsLine(script)}</Text>
            </View>
          ) : null}

          <TextField
            label="Subject"
            required
            value={subject}
            onChangeText={setSubject}
            placeholder="What the script is about"
            multiline
            numberOfLines={2}
            maxLength={MAX_SUBJECT_LEN}
            editable={!busy}
          />

          <TextField
            label="Script"
            value={script}
            onChangeText={setScript}
            placeholder="Your narration script…"
            multiline
            numberOfLines={12}
            editable={!busy}
          />

          {actionError ? (
            <Text style={styles.error}>{actionError}</Text>
          ) : null}

          <Button
            label={dirty ? "Save changes" : "Saved"}
            onPress={() => void onSave()}
            loading={saveState === "saving"}
            disabled={busy || !dirty}
          />

          <Button
            label="Use in a reel"
            variant="secondary"
            onPress={onUseInReel}
            disabled={busy || !script.trim()}
          />

          <View style={styles.refineBlock}>
            <Text style={styles.sectionTitle}>REFINE</Text>
            <TextField
              value={refineInstruction}
              onChangeText={setRefineInstruction}
              placeholder="How to rework it, e.g. shorter, add a stronger hook"
              multiline
              numberOfLines={2}
              maxLength={MAX_PROMPT_LEN}
              editable={!busy}
            />
            <Button
              label="Refine with AI"
              variant="secondary"
              onPress={confirmRefine}
              loading={refining}
              disabled={busy || !script.trim()}
            />
          </View>

          <Button
            label="Delete script"
            variant="destructive"
            onPress={confirmDelete}
            disabled={busy}
          />
        </ScrollView>
      </KeyboardAvoidingView>
    </StudioScreen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 64, gap: 14 },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  langBadge: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  langText: { color: colors.textSecondary, fontSize: 11, fontWeight: "600" },
  meta: { color: colors.muted, fontSize: 12 },
  error: { color: colors.error, fontSize: 13 },
  sectionTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  refineBlock: {
    gap: 10,
    marginTop: 6,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 16,
  },
});
