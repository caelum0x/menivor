/**
 * Studio · Generate Script
 *
 * Nav manifest: { route: "/studio/scripts/generate", title: "Generate script" }
 *
 * The generation form for the Script Studio. Collects a subject (required),
 * narration language, paragraph count (1..10) and an optional style prompt,
 * validates before calling `POST /api/v1/scripts`, then shows the generated
 * script in an editable field with a live word/duration stat. From there the
 * creator can regenerate, save it to the library (→ edit screen), or discard.
 */

import { useCallback, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useRouter } from "expo-router";

import {
  DEFAULT_PARAGRAPHS,
  MAX_PARAGRAPHS,
  MAX_PROMPT_LEN,
  MAX_SUBJECT_LEN,
  MIN_PARAGRAPHS,
  SCRIPT_LANGUAGES,
  clampParagraphs,
  generateScript,
  scriptStatsLine,
  validateSubject,
  type ScriptLanguage,
} from "@/lib/scripts";
import { saveScript } from "@/src/shared/product/script-library";
import { useSession } from "@/src/shared/auth";

import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import {
  Button,
  NumberField,
  SelectField,
  TextField,
  type SelectOption,
} from "@/components/ui";

const LANGUAGE_OPTIONS: readonly SelectOption<ScriptLanguage>[] =
  SCRIPT_LANGUAGES.map((l) => ({ value: l.value, label: l.label }));

type Phase = "editing" | "generating" | "saving";

export default function GenerateScriptScreen() {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [subject, setSubject] = useState("");
  const [language, setLanguage] = useState<ScriptLanguage>("auto");
  const [paragraphsText, setParagraphsText] = useState(
    String(DEFAULT_PARAGRAPHS),
  );
  const [prompt, setPrompt] = useState("");

  const [script, setScript] = useState("");
  const [phase, setPhase] = useState<Phase>("editing");
  const [subjectError, setSubjectError] = useState("");
  const [error, setError] = useState("");

  const abortRef = useRef<AbortController | null>(null);

  const paragraphs = clampParagraphs(Number(paragraphsText));
  const busy = phase !== "editing";

  const onGenerate = useCallback(async () => {
    const validationError = validateSubject(subject);
    if (validationError) {
      setSubjectError(validationError);
      return;
    }
    setSubjectError("");
    setError("");
    setPhase("generating");

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const result = await generateScript(
        {
          video_subject: subject,
          video_language: language,
          paragraph_number: paragraphs,
          video_script_prompt: prompt,
        },
        { token, signal: controller.signal },
      );
      const text = result.video_script.trim();
      if (!text) {
        setError("The model returned an empty script. Try again.");
        return;
      }
      setScript(text);
    } catch (err) {
      setError(describeError(err, "Failed to generate the script."));
    } finally {
      setPhase("editing");
    }
  }, [subject, language, paragraphs, prompt, token]);

  const onSave = useCallback(async () => {
    if (!script.trim()) return;
    setPhase("saving");
    setError("");
    try {
      const saved = await saveScript({
        subject: subject.trim(),
        language,
        paragraphs,
        prompt: prompt.trim(),
        script: script.trim(),
      });
      // Replace so Back from the editor returns to the library, not this form.
      router.replace(`/studio/scripts/${saved.id}`);
    } catch (err) {
      setError(describeError(err, "Failed to save the script."));
      setPhase("editing");
    }
  }, [script, subject, language, paragraphs, prompt, router]);

  const hasScript = script.trim().length > 0;

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        style={styles.flex}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.intro}>
          Describe the reel and we will write a narration script you can edit and
          reuse.
        </Text>

        <TextField
          label="Subject"
          required
          value={subject}
          onChangeText={(t) => {
            setSubject(t);
            if (subjectError) setSubjectError("");
          }}
          placeholder="e.g. 3 tips for editing your videos faster"
          error={subjectError}
          multiline
          numberOfLines={2}
          maxLength={MAX_SUBJECT_LEN}
          editable={!busy}
        />

        <SelectField<ScriptLanguage>
          label="Language"
          value={language}
          onChange={setLanguage}
          options={LANGUAGE_OPTIONS}
          disabled={busy}
        />

        <NumberField
          label="Paragraphs"
          value={paragraphsText}
          onChangeText={setParagraphsText}
          placeholder={String(DEFAULT_PARAGRAPHS)}
          helper={`How many paragraphs to write (${MIN_PARAGRAPHS}–${MAX_PARAGRAPHS}). Using ${paragraphs}.`}
          editable={!busy}
        />

        <TextField
          label="Style prompt (optional)"
          value={prompt}
          onChangeText={setPrompt}
          placeholder="e.g. punchy hook, casual tone, end with a call to action"
          multiline
          numberOfLines={3}
          maxLength={MAX_PROMPT_LEN}
          editable={!busy}
        />

        <Button
          label={hasScript ? "Regenerate" : "Generate script"}
          onPress={() => void onGenerate()}
          loading={phase === "generating"}
          disabled={busy}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {hasScript ? (
          <View style={styles.resultBlock}>
            <View style={styles.resultHead}>
              <Text style={styles.resultTitle}>SCRIPT</Text>
              <Text style={styles.stats}>{scriptStatsLine(script)}</Text>
            </View>
            <TextField
              value={script}
              onChangeText={setScript}
              placeholder="Your generated script…"
              multiline
              numberOfLines={12}
              editable={!busy}
            />
            <Button
              label="Save to library"
              onPress={() => void onSave()}
              loading={phase === "saving"}
              disabled={busy || !script.trim()}
            />
            <Button
              label="Discard"
              variant="ghost"
              onPress={() => setScript("")}
              disabled={busy}
            />
          </View>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 64, gap: 14 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  error: { color: colors.error, fontSize: 13 },
  resultBlock: {
    gap: 12,
    marginTop: 6,
    borderTopColor: colors.border,
    borderTopWidth: 1,
    paddingTop: 16,
  },
  resultHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  resultTitle: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  stats: { color: colors.muted, fontSize: 12 },
});
