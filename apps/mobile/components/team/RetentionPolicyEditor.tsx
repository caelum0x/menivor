/**
 * The data-retention policy editor for a single workspace. Reads the current
 * policy (GET /me/workspaces/{id}/retention) and the caller's effective
 * permissions (GET /me/permissions), then lets an owner/admin set two
 * independent windows — how long JOBS and ASSETS are kept before the periodic
 * sweep anonymizes aged rows — each with a "Keep forever" switch or a whole-day
 * count. Changes are validated client-side, previewed, and confirmed before the
 * audited PUT; a viewer / non-member sees a read-only view.
 *
 * This mirrors the web read/edit surface. Every authorization decision is made
 * server-side (RBAC `workspace.settings`); this screen only mirrors the returned
 * permissions to decide what to enable. Auth flows through the shared api client
 * as `x-api-key`; no secrets live here.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { Icon } from "@/components/ui/Icon";

import {
  getRetentionPolicy,
  setRetentionPolicy,
  type RetentionPolicy,
} from "@/lib/compliance";
import { getMyPermissions } from "@/lib/api";
import type { Permissions, Workspace } from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { describeError } from "@/components/me/errors";
import { colors } from "@/components/me/theme";
import { useResource } from "@/components/me/use-resource";

import { roleLabel } from "./roles";
import {
  daysToInput,
  formatTimestamp,
  formatWindow,
  parseDaysInput,
} from "./retention-format";

interface RetentionPolicyEditorProps {
  workspace: Workspace;
  token: string | undefined;
  onBack: () => void;
}

/** Per-dimension form state: keep-forever or a free-text whole-day count. */
interface FieldState {
  keepForever: boolean;
  text: string;
}

/** Seed a dimension's field state from a loaded retention window. */
function seedField(days: number | null): FieldState {
  return { keepForever: days === null, text: daysToInput(days) };
}

/** The effective value + validation error for a dimension's field state. */
function resolveField(field: FieldState): { value: number | null; error: string | null } {
  if (field.keepForever) return { value: null, error: null };
  return parseDaysInput(field.text);
}

export function RetentionPolicyEditor({
  workspace,
  token,
  onBack,
}: Readonly<RetentionPolicyEditorProps>) {
  const policyFetcher = useCallback(
    () => getRetentionPolicy(workspace.id, { token }),
    [workspace.id, token],
  );
  const { status, data, error, reload } =
    useResource<RetentionPolicy>(policyFetcher);

  const permissionsFetcher = useCallback(
    () => getMyPermissions(workspace.id, { token }),
    [workspace.id, token],
  );
  const { data: permissions } = useResource<Permissions>(permissionsFetcher);
  const canEdit = permissions?.permissions.includes("workspace.settings") ?? false;

  // Form state, seeded from the loaded policy and re-seeded whenever it changes
  // (initial load, reload, or after a successful save).
  const [jobs, setJobs] = useState<FieldState>({ keepForever: true, text: "" });
  const [assets, setAssets] = useState<FieldState>({ keepForever: true, text: "" });
  const [baseline, setBaseline] = useState<RetentionPolicy | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (!data) return;
    setJobs(seedField(data.jobs_retention_days));
    setAssets(seedField(data.assets_retention_days));
    setBaseline(data);
    setSaveError("");
    setSaveOk(false);
  }, [data]);

  const jobsResolved = useMemo(() => resolveField(jobs), [jobs]);
  const assetsResolved = useMemo(() => resolveField(assets), [assets]);

  const dirty = useMemo(() => {
    if (!baseline) return false;
    return (
      jobsResolved.value !== baseline.jobs_retention_days ||
      assetsResolved.value !== baseline.assets_retention_days
    );
  }, [baseline, jobsResolved.value, assetsResolved.value]);

  const hasError = jobsResolved.error !== null || assetsResolved.error !== null;
  const canSubmit = canEdit && dirty && !hasError && !saving;

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setSaving(true);
    setSaveError("");
    setSaveOk(false);
    try {
      const updated = await setRetentionPolicy(
        workspace.id,
        {
          jobs_retention_days: jobsResolved.value,
          assets_retention_days: assetsResolved.value,
        },
        { token },
      );
      setBaseline(updated);
      setJobs(seedField(updated.jobs_retention_days));
      setAssets(seedField(updated.assets_retention_days));
      setSaveOk(true);
    } catch (err: unknown) {
      setSaveError(describeError(err, "Failed to save the retention policy."));
    } finally {
      setSaving(false);
    }
  }, [canSubmit, workspace.id, jobsResolved.value, assetsResolved.value, token]);

  const confirmSave = useCallback(() => {
    if (!canSubmit) return;
    Alert.alert(
      "Update retention policy",
      `Jobs: ${formatWindow(jobsResolved.value)}\nAssets: ${formatWindow(
        assetsResolved.value,
      )}\n\nRows older than a window are anonymized by the periodic sweep. This is audited.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Save", style: "destructive", onPress: () => void submit() },
      ],
    );
  }, [canSubmit, jobsResolved.value, assetsResolved.value, submit]);

  return (
    <View style={styles.container}>
      <Pressable
        style={styles.back}
        onPress={onBack}
        accessibilityRole="button"
        accessibilityLabel="Back to workspaces"
      >
        <Icon name="chevron-back" style={styles.backText} />
        <Text style={styles.backText}>Workspaces</Text>
      </Pressable>

      <View style={styles.headerCard}>
        <Text style={styles.workspaceName} numberOfLines={1}>
          {workspace.name}
        </Text>
        <Text style={styles.role}>Your role: {roleLabel(workspace.my_role)}</Text>
      </View>

      <Section title="DATA RETENTION">
        <SectionState status={status} error={error} onRetry={reload}>
          <View style={styles.body}>
            <Text style={styles.intro}>
              Set how long this workspace keeps members' jobs and assets before the
              periodic sweep anonymizes aged rows. Leave a window on "Keep forever"
              to never sweep that data.
            </Text>

            {!canEdit ? (
              <View style={styles.readOnlyBanner}>
                <Text style={styles.readOnlyText}>
                  Read-only. Only a workspace owner or admin can change the
                  retention policy.
                </Text>
              </View>
            ) : null}

            <RetentionField
              label="Jobs"
              hint="Rendered reels and their generation history."
              field={jobs}
              resolvedError={jobsResolved.error}
              disabled={!canEdit || saving}
              onChange={setJobs}
            />
            <RetentionField
              label="Assets"
              hint="Uploaded and generated media (clips, images, audio)."
              field={assets}
              resolvedError={assetsResolved.error}
              disabled={!canEdit || saving}
              onChange={setAssets}
            />

            {baseline ? (
              <View style={styles.metaCard}>
                <MetaRow
                  label="Current jobs window"
                  value={formatWindow(baseline.jobs_retention_days)}
                />
                <MetaRow
                  label="Current assets window"
                  value={formatWindow(baseline.assets_retention_days)}
                />
                <MetaRow
                  label="Last updated"
                  value={formatTimestamp(baseline.updated_at)}
                />
              </View>
            ) : null}

            {saveError ? <Text style={styles.error}>{saveError}</Text> : null}
            {saveOk ? (
              <Text style={styles.success}>Retention policy saved.</Text>
            ) : null}

            {canEdit ? (
              <Pressable
                style={[styles.saveBtn, !canSubmit && styles.saveBtnDisabled]}
                onPress={confirmSave}
                disabled={!canSubmit}
                accessibilityRole="button"
                accessibilityLabel="Save retention policy"
                accessibilityState={{ disabled: !canSubmit }}
              >
                {saving ? (
                  <ActivityIndicator color={colors.bg} />
                ) : (
                  <Text style={styles.saveText}>
                    {dirty ? "Save changes" : "No changes"}
                  </Text>
                )}
              </Pressable>
            ) : null}
          </View>
        </SectionState>
      </Section>
    </View>
  );
}

interface RetentionFieldProps {
  label: string;
  hint: string;
  field: FieldState;
  resolvedError: string | null;
  disabled: boolean;
  onChange: (next: FieldState) => void;
}

/** One retention dimension: a keep-forever switch plus a whole-day input. */
function RetentionField({
  label,
  hint,
  field,
  resolvedError,
  disabled,
  onChange,
}: Readonly<RetentionFieldProps>) {
  return (
    <View style={styles.field}>
      <View style={styles.fieldHeader}>
        <View style={styles.fieldLabels}>
          <Text style={styles.fieldLabel}>{label}</Text>
          <Text style={styles.fieldHint}>{hint}</Text>
        </View>
      </View>

      <View style={styles.switchRow}>
        <Text style={styles.switchLabel}>Keep forever</Text>
        <Switch
          value={field.keepForever}
          disabled={disabled}
          onValueChange={(keepForever) =>
            onChange({ ...field, keepForever })
          }
          trackColor={{ false: colors.border, true: colors.accent }}
          thumbColor={colors.bg}
          accessibilityLabel={`${label}: keep forever`}
        />
      </View>

      {!field.keepForever ? (
        <View style={styles.inputRow}>
          <TextInput
            style={[styles.input, resolvedError ? styles.inputError : null]}
            value={field.text}
            onChangeText={(text) => onChange({ ...field, text })}
            editable={!disabled}
            keyboardType="number-pad"
            inputMode="numeric"
            placeholder="e.g. 30"
            placeholderTextColor={colors.muted}
            maxLength={6}
            accessibilityLabel={`${label}: retention days`}
          />
          <Text style={styles.inputUnit}>days</Text>
        </View>
      ) : null}

      {resolvedError ? <Text style={styles.error}>{resolvedError}</Text> : null}
    </View>
  );
}

function MetaRow({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 16 },
  back: { alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 2, paddingVertical: 4 },
  backText: { color: colors.accent, fontSize: 15, fontWeight: "600" },
  headerCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 6,
  },
  workspaceName: { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  role: { color: colors.muted, fontSize: 13 },
  body: { gap: 16 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  readOnlyBanner: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
  },
  readOnlyText: { color: colors.textSecondary, fontSize: 13, lineHeight: 18 },
  field: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  fieldHeader: { flexDirection: "row", alignItems: "flex-start" },
  fieldLabels: { flex: 1, gap: 4 },
  fieldLabel: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  fieldHint: { color: colors.muted, fontSize: 12, lineHeight: 16 },
  switchRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  switchLabel: { color: colors.textSecondary, fontSize: 14 },
  inputRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  input: {
    flex: 1,
    backgroundColor: colors.bg,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.textPrimary,
    fontSize: 16,
  },
  inputError: { borderColor: colors.error },
  inputUnit: { color: colors.muted, fontSize: 14 },
  metaCard: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  metaLabel: { color: colors.muted, fontSize: 13 },
  metaValue: { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },
  error: { color: colors.error, fontSize: 13, lineHeight: 18 },
  success: { color: colors.success, fontSize: 13, fontWeight: "600" },
  saveBtn: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 50,
  },
  saveBtnDisabled: { opacity: 0.45 },
  saveText: { color: colors.bg, fontSize: 16, fontWeight: "700" },
});
