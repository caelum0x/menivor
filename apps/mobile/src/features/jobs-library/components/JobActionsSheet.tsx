/**
 * Reel management sheet — rename, archive/restore, cancel (with credit refund)
 * and delete a reel the caller owns. Shared by the canonical library list
 * (long-press a card) and the job detail header ("Manage").
 *
 * Every action goes through the typed api client (PATCH /jobs/{id},
 * POST /jobs/{id}/cancel, DELETE /jobs/{id}). Destructive actions confirm
 * first; cancel reports the credits the backend released back to the wallet.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  ApiError,
  archiveJob,
  cancelJob,
  deleteJob,
  jobDisplayName,
  renameJob,
} from "@/lib/api";
import { isTerminalState, type Job } from "@/lib/types";
import { Icon, type IconName } from "@/components/ui/Icon";
import { colors, radius, spacing, typeScale } from "@/src/shared/theme";

const TITLE_MAX_LENGTH = 120;

export type JobActionOutcome =
  | { kind: "updated"; job: Job }
  | { kind: "deleted"; jobId: string };

interface JobActionsSheetProps {
  visible: boolean;
  job: Job | null;
  token: string | undefined;
  onClose: () => void;
  onDone: (outcome: JobActionOutcome) => void;
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "This reel no longer exists.";
    if (err.status === 409) return err.message || "The reel changed state. Refresh and try again.";
    return err.message;
  }
  return err instanceof Error ? err.message : fallback;
}

function confirm(title: string, message: string, cta: string): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "Keep", style: "cancel", onPress: () => resolve(false) },
      { text: cta, style: "destructive", onPress: () => resolve(true) },
    ]);
  });
}

function refundLine(credits: number | undefined): string {
  if (typeof credits !== "number" || credits <= 0) {
    return "No held credits needed refunding.";
  }
  return `${credits} credit${credits === 1 ? "" : "s"} returned to your balance.`;
}

export function JobActionsSheet({ visible, job, token, onClose, onDone }: JobActionsSheetProps) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState<null | "rename" | "archive" | "cancel" | "delete">(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!visible || !job) return;
    setTitle(typeof job.title === "string" ? job.title : "");
    setError(null);
    setBusy(null);
  }, [visible, job]);

  const onRename = useCallback(async () => {
    if (!job || busy) return;
    setBusy("rename");
    setError(null);
    try {
      const updated = await renameJob(job.job_id, title.slice(0, TITLE_MAX_LENGTH), { token });
      onDone({ kind: "updated", job: { ...job, ...updated } });
    } catch (err) {
      setError(describe(err, "Could not rename the reel."));
    } finally {
      setBusy(null);
    }
  }, [busy, job, onDone, title, token]);

  const onArchive = useCallback(async () => {
    if (!job || busy) return;
    const next = !job.archived;
    setBusy("archive");
    setError(null);
    try {
      const updated = await archiveJob(job.job_id, next, { token });
      onDone({ kind: "updated", job: { ...job, ...updated, archived: updated.archived ?? next } });
    } catch (err) {
      setError(describe(err, "Could not update the reel."));
    } finally {
      setBusy(null);
    }
  }, [busy, job, onDone, token]);

  const onCancel = useCallback(async () => {
    if (!job || busy) return;
    const ok = await confirm(
      "Cancel this reel?",
      "Rendering stops now. Credits held for unfinished stages are returned to your balance.",
      "Cancel reel",
    );
    if (!ok) return;
    setBusy("cancel");
    setError(null);
    try {
      const result = await cancelJob(job.job_id, { token });
      Alert.alert("Reel cancelled", refundLine(result.refunded_credits));
      onDone({ kind: "updated", job: { ...job, ...result, cancelled: true } });
    } catch (err) {
      setError(describe(err, "Could not cancel the reel."));
    } finally {
      setBusy(null);
    }
  }, [busy, job, onDone, token]);

  const onDelete = useCallback(async () => {
    if (!job || busy) return;
    const ok = await confirm(
      "Delete this reel?",
      "The reel and its rendered files are removed permanently. This cannot be undone.",
      "Delete",
    );
    if (!ok) return;
    setBusy("delete");
    setError(null);
    try {
      const result = await deleteJob(job.job_id, { token });
      if (typeof result?.refunded_credits === "number" && result.refunded_credits > 0) {
        Alert.alert("Reel deleted", refundLine(result.refunded_credits));
      }
      onDone({ kind: "deleted", jobId: job.job_id });
    } catch (err) {
      setError(describe(err, "Could not delete the reel."));
    } finally {
      setBusy(null);
    }
  }, [busy, job, onDone, token]);

  if (!job) return null;
  const inFlight = !isTerminalState(job.state) && !job.cancelled;
  const unchangedTitle = (job.title ?? "") === title.trim();

  const action = (
    key: NonNullable<typeof busy>,
    icon: IconName,
    label: string,
    onPress: () => void,
    danger = false,
  ) => (
    <Pressable
      key={key}
      style={[styles.action, busy !== null && busy !== key && styles.disabled]}
      onPress={onPress}
      disabled={busy !== null}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ busy: busy === key, disabled: busy !== null }}
    >
      {busy === key ? (
        <ActivityIndicator color={danger ? colors.danger : colors.accent} />
      ) : (
        <Icon name={icon} size={20} color={danger ? colors.danger : colors.textPrimary} />
      )}
      <Text style={[styles.actionText, danger && styles.dangerText]}>{label}</Text>
    </Pressable>
  );

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.backdrop}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable style={styles.dismiss} onPress={onClose} accessibilityLabel="Close" />
        <View style={styles.sheet}>
          <View style={styles.headerRow}>
            <Text style={styles.title} numberOfLines={1}>
              {jobDisplayName(job)}
            </Text>
            <Pressable onPress={onClose} hitSlop={12} accessibilityRole="button" accessibilityLabel="Close">
              <Icon name="close" size={22} color={colors.textSecondary} />
            </Pressable>
          </View>

          <Text style={styles.label}>Name</Text>
          <View style={styles.renameRow}>
            <TextInput
              style={styles.input}
              value={title}
              onChangeText={setTitle}
              placeholder={job.job_id}
              placeholderTextColor={colors.textFaint}
              maxLength={TITLE_MAX_LENGTH}
              returnKeyType="done"
              onSubmitEditing={() => void onRename()}
              accessibilityLabel="Reel name"
            />
            <Pressable
              style={[styles.save, (unchangedTitle || busy !== null) && styles.disabled]}
              onPress={() => void onRename()}
              disabled={unchangedTitle || busy !== null}
              accessibilityRole="button"
              accessibilityLabel="Save name"
            >
              {busy === "rename" ? (
                <ActivityIndicator color={colors.onAccent} />
              ) : (
                <Text style={styles.saveText}>Save</Text>
              )}
            </Pressable>
          </View>

          {action(
            "archive",
            job.archived ? "arrow-undo-outline" : "archive-outline",
            job.archived ? "Restore to library" : "Archive",
            () => void onArchive(),
          )}
          {inFlight
            ? action("cancel", "stop-circle-outline", "Cancel rendering and refund", () => void onCancel(), true)
            : null}
          {action("delete", "trash-outline", "Delete permanently", () => void onDelete(), true)}

          {error ? <Text style={styles.error}>{error}</Text> : null}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "flex-end" },
  dismiss: { flex: 1 },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xxl,
    gap: spacing.sm,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, marginBottom: spacing.sm },
  title: { flex: 1, color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  label: { color: colors.textSecondary, fontSize: typeScale.caption, fontWeight: "600" },
  renameRow: { flexDirection: "row", gap: spacing.sm, marginBottom: spacing.md },
  input: {
    flex: 1,
    backgroundColor: colors.input,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    color: colors.textPrimary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: typeScale.body,
  },
  save: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    alignItems: "center",
    justifyContent: "center",
    minWidth: 72,
  },
  saveText: { color: colors.onAccent, fontWeight: "700" },
  action: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
    borderTopColor: colors.border,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  actionText: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600" },
  dangerText: { color: colors.danger },
  disabled: { opacity: 0.5 },
  error: { color: colors.danger, fontSize: typeScale.caption, marginTop: spacing.sm },
});
