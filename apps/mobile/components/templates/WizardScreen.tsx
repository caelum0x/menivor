/**
 * WizardScreen template — multi-step form with progress indicator, back/next.
 *
 * The caller provides an ordered array of steps; each step has a title and
 * a render function. The wizard manages step index, progress display, and
 * calls `onComplete` when the final step's Next is pressed.
 *
 * Usage (a typical wizard screen becomes ~40-60 lines):
 * ```tsx
 * <WizardScreen
 *   steps={[
 *     {
 *       title: "Choose Avatar",
 *       render: (ctx) => (
 *         <AvatarPicker
 *           value={ctx.values.avatarId}
 *           onChange={(id) => ctx.set("avatarId", id)}
 *         />
 *       ),
 *     },
 *     {
 *       title: "Set Voice",
 *       render: (ctx) => <VoicePickerForm ctx={ctx} />,
 *     },
 *   ]}
 *   initialValues={{ avatarId: "", voiceId: "" }}
 *   onComplete={async (values) => { await createJob(values); }}
 *   completeLabel="Generate"
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
import { radius, spacing, typeScale, weight } from "@/src/shared/theme";
import { Button } from "../ui/Button";
import { ErrorState } from "../ui/ErrorState";

export interface WizardContext<T extends Record<string, unknown>> {
  values: T;
  set: <K extends keyof T>(key: K, value: T[K]) => void;
  step: number;
  totalSteps: number;
  errors: Partial<Record<keyof T, string>>;
}

export interface WizardStep<T extends Record<string, unknown>> {
  title: string;
  subtitle?: string;
  render: (ctx: WizardContext<T>) => ReactNode;
  /** Per-step validation. Return error map; empty = valid. */
  validate?: (values: T) => Partial<Record<keyof T, string>>;
}

export interface WizardScreenProps<T extends Record<string, unknown>> {
  steps: readonly WizardStep<T>[];
  initialValues: Readonly<T>;
  /** Called when the user presses Next on the last step. Should throw on error. */
  onComplete: (values: T) => Promise<void>;
  /** Label on the final step's Next button. */
  completeLabel?: string;
  /** Called when the user cancels (e.g. presses back on step 0). */
  onCancel?: () => void;
  /** Called after successful completion. */
  onSuccess?: () => void;
}

export function WizardScreen<T extends Record<string, unknown>>({
  steps,
  initialValues,
  onComplete,
  completeLabel = "Finish",
  onCancel,
  onSuccess,
}: WizardScreenProps<T>): React.JSX.Element {
  const insets = useSafeAreaInsets();
  const [step, setStep] = useState(0);
  const [values, setValues] = useState<T>(initialValues as T);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof T, string>>>({});
  const [submitError, setSubmitError] = useState("");
  const [busy, setBusy] = useState(false);

  const totalSteps = steps.length;
  const isLast = step === totalSteps - 1;
  const currentStep = steps[step];

  const set = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setFieldErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const ctx: WizardContext<T> = {
    values,
    set,
    step,
    totalSteps,
    errors: fieldErrors,
  };

  const handleNext = useCallback(async () => {
    if (busy || !currentStep) return;
    const errors = currentStep.validate ? currentStep.validate(values) : {};
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});

    if (isLast) {
      setBusy(true);
      setSubmitError("");
      try {
        await onComplete(values);
        onSuccess?.();
      } catch (err: unknown) {
        setSubmitError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        setBusy(false);
      }
    } else {
      setStep((s) => s + 1);
    }
  }, [busy, currentStep, isLast, onComplete, onSuccess, values]);

  const handleBack = useCallback(() => {
    if (step === 0) {
      onCancel?.();
    } else {
      setStep((s) => s - 1);
      setFieldErrors({});
      setSubmitError("");
    }
  }, [step, onCancel]);

  if (!currentStep) return <View />;

  return (
    <View style={[styles.container, { paddingBottom: insets.bottom }]}>
      {/* Progress */}
      <View style={styles.progressBar}>
        {Array.from({ length: totalSteps }).map((_, i) => (
          <View
            key={i}
            style={[
              styles.progressDot,
              i <= step && styles.progressDotActive,
            ]}
          />
        ))}
      </View>

      {/* Step header */}
      <View style={styles.stepHeader}>
        <Text style={styles.stepCount}>
          {`Step ${step + 1} of ${totalSteps}`}
        </Text>
        <Text style={styles.stepTitle}>{currentStep.title}</Text>
        {currentStep.subtitle ? (
          <Text style={styles.stepSubtitle}>{currentStep.subtitle}</Text>
        ) : null}
      </View>

      {/* Step content */}
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {currentStep.render(ctx)}
        {submitError ? (
          <ErrorState message={submitError} style={styles.submitError} />
        ) : null}
      </ScrollView>

      {/* Navigation footer */}
      <View style={[styles.footer, { paddingBottom: insets.bottom ? spacing.sm : spacing.lg }]}>
        <Button
          label={step === 0 ? "Cancel" : "Back"}
          variant="ghost"
          onPress={handleBack}
          disabled={busy}
          style={styles.footerBtn}
        />
        <Button
          label={isLast ? completeLabel : "Next"}
          variant="primary"
          onPress={handleNext}
          loading={busy}
          style={styles.footerBtn}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },

  progressBar: {
    flexDirection: "row",
    gap: spacing.xs,
    padding: spacing.md,
    paddingBottom: spacing.sm,
  },
  progressDot: {
    flex: 1,
    height: 3,
    borderRadius: radius.pill,
    backgroundColor: colors.border,
  },
  progressDotActive: { backgroundColor: colors.accent },

  stepHeader: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 4,
  },
  stepCount: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: weight.bold,
    letterSpacing: 1,
    textTransform: "uppercase",
  },
  stepTitle: {
    color: colors.textPrimary,
    fontSize: typeScale.heading,
    fontWeight: weight.black,
  },
  stepSubtitle: { color: colors.textSecondary, fontSize: 13 },

  content: {
    padding: spacing.lg,
    gap: spacing.md,
    paddingBottom: spacing.xxl,
  },
  submitError: { marginTop: spacing.sm },

  footer: {
    flexDirection: "row",
    gap: spacing.sm,
    padding: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.bg,
  },
  footerBtn: { flex: 1 },
});
