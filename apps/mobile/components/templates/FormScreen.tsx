/**
 * FormScreen template — fields + validation + submit + busy state.
 *
 * Manages a generic form state map with typed fields. The caller provides
 * a fields definition array and the submit handler. Validation is done
 * via the `validate` callback before submission.
 *
 * Usage (a typical form screen becomes ~30-50 lines):
 * ```tsx
 * type Fields = { name: string; email: string };
 *
 * <FormScreen<Fields>
 *   title="Create Workspace"
 *   initialValues={{ name: "", email: "" }}
 *   validate={(values) => {
 *     const errors: Partial<Record<keyof Fields, string>> = {};
 *     if (!values.name.trim()) errors.name = "Name is required";
 *     return errors;
 *   }}
 *   onSubmit={async (values) => {
 *     await createWorkspace({ name: values.name });
 *   }}
 *   fields={(values, onChange, errors) => (
 *     <>
 *       <TextField label="Name" value={values.name} onChangeText={(v) => onChange("name", v)} error={errors.name} />
 *       <TextField label="Email" value={values.email} onChangeText={(v) => onChange("email", v)} error={errors.email} />
 *     </>
 *   )}
 *   submitLabel="Create"
 * />
 * ```
 */

import type { ReactNode } from "react";
import { useCallback, useState } from "react";
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors } from "@/components/me/theme";
import { spacing, typeScale, weight } from "@/src/shared/theme";
import { Button } from "../ui/Button";
import { ErrorState } from "../ui/ErrorState";

export interface FormScreenProps<T extends Record<string, string | boolean | number>> {
  title?: string;
  subtitle?: string;
  initialValues: Readonly<T>;
  validate?: (values: T) => Partial<Record<keyof T, string>>;
  /** Called on valid submit. Should throw on API errors. */
  onSubmit: (values: T) => Promise<void>;
  /** Renders form field components; receives values, onChange, and field errors. */
  fields: (
    values: T,
    onChange: <K extends keyof T>(key: K, value: T[K]) => void,
    errors: Partial<Record<keyof T, string>>,
  ) => ReactNode;
  submitLabel?: string;
  cancelLabel?: string;
  onCancel?: () => void;
  /** Success message shown after submit. */
  successMessage?: string;
  /** Called after a successful submit. */
  onSuccess?: () => void;
}

export function FormScreen<T extends Record<string, string | boolean | number>>({
  title,
  subtitle,
  initialValues,
  validate,
  onSubmit,
  fields,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  onCancel,
  successMessage,
  onSuccess,
}: FormScreenProps<T>): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const [values, setValues] = useState<T>(initialValues);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof T, string>>>({});
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const onChange = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    // Clear field error on change
    setFieldErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const handleSubmit = useCallback(async () => {
    if (busy) return;
    const errors = validate ? validate(values) : {};
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setBusy(true);
    setSubmitError("");
    try {
      await onSubmit(values);
      setDone(true);
      onSuccess?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setSubmitError(msg || "Submit failed.");
    } finally {
      setBusy(false);
    }
  }, [busy, validate, values, onSubmit, onSuccess]);

  if (done && successMessage) {
    return (
      <View style={[styles.successContainer, { paddingBottom: insets.bottom }]}>
        <Text style={styles.successText}>{successMessage}</Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingBottom: insets.bottom }]}>
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {title ? (
          <View style={styles.titleBlock}>
            <Text style={styles.title}>{title}</Text>
            {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
          </View>
        ) : null}

        <View style={styles.fieldsBlock}>
          {fields(values, onChange, fieldErrors)}
        </View>

        {submitError ? (
          <ErrorState message={submitError} />
        ) : null}
      </ScrollView>

      <View style={[styles.footer, { paddingBottom: insets.bottom ? spacing.sm : spacing.lg }]}>
        {onCancel ? (
          <Button
            label={cancelLabel}
            variant="ghost"
            onPress={onCancel}
            disabled={busy}
            style={styles.footerBtn}
          />
        ) : null}
        <Button
          label={submitLabel}
          variant="primary"
          onPress={handleSubmit}
          loading={busy}
          style={styles.footerBtn}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxl },
  titleBlock: { gap: spacing.xs },
  title: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
  },
  subtitle: { color: colors.textSecondary, fontSize: 13 },
  fieldsBlock: { gap: spacing.md },
  footer: {
    flexDirection: "row",
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.bg,
  },
  footerBtn: { flex: 1 },
  successContainer: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    backgroundColor: colors.bg,
  },
  successText: {
    color: colors.success,
    fontSize: 16,
    fontWeight: weight.bold,
    textAlign: "center",
  },
});
