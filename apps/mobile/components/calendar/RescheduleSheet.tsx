import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { ApiError } from "@/lib/api";
import { reschedulePublish, type CalendarEntry } from "@/lib/calendar";

import { DateTimeField } from "@/components/schedule/DateTimeField";
import {
  defaultScheduleAt,
  toIsoUtc,
} from "@/components/schedule/datetime";

import { platformSummary } from "./format";
import { Icon } from "@/components/ui/Icon";

/**
 * "Reschedule publish" bottom sheet. The creator picks a new future LOCAL time
 * for a still-`pending` calendar entry; on submit the time is converted to an
 * ISO-8601 UTC instant and PATCHed to `/me/calendar/{id}`. On success the moved
 * entry is handed back to the caller. Reuses the schedule feature's dependency-
 * free `DateTimeField` + datetime helpers so the two flows never drift. Owns its
 * own loading + error state; no secrets here.
 */
export interface RescheduleSheetProps {
  visible: boolean;
  /** The still-pending entry being moved (null while the sheet is closed). */
  entry: CalendarEntry | null;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  onClose: () => void;
  /** Called with the moved entry after a successful submit. */
  onRescheduled: (result: CalendarEntry) => void;
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function RescheduleSheet({
  visible,
  entry,
  token,
  onClose,
  onRescheduled,
}: Readonly<RescheduleSheetProps>) {
  const [when, setWhen] = useState<Date | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed the picker from the entry's current time when parseable, else ~1h out.
  const initialDate = useMemo(() => {
    if (entry?.scheduled_at) {
      const current = new Date(entry.scheduled_at);
      if (!Number.isNaN(current.getTime()) && current.getTime() > Date.now()) {
        return current;
      }
    }
    return defaultScheduleAt();
    // Re-seed each time the sheet opens for a (possibly) different entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, entry?.id, entry?.scheduled_at]);

  // Reset time/error whenever the sheet is reopened.
  useEffect(() => {
    if (visible) {
      setWhen(null);
      setError(null);
      setSubmitting(false);
    }
  }, [visible]);

  const timeValid = when !== null && when.getTime() > Date.now();
  const canSubmit = timeValid && !submitting && entry !== null;

  const handleSubmit = useCallback(async () => {
    if (entry === null || when === null) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await reschedulePublish(entry.id, toIsoUtc(when), {
        token,
      });
      onRescheduled(result);
    } catch (err) {
      setError(describe(err, "Failed to reschedule publish."));
      setSubmitting(false);
    }
  }, [entry, when, token, onRescheduled]);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.handle} />
          <View style={styles.headerRow}>
            <Text style={styles.title}>Reschedule publish</Text>
            <Pressable
              onPress={onClose}
              accessibilityRole="button"
              accessibilityLabel="Close"
              hitSlop={12}
            >
              <Icon name="close" style={styles.close} />
            </Pressable>
          </View>
          <Text style={styles.subtitle}>
            {entry
              ? `Move this ${platformSummary(entry)} publish to a new time. We publish it in the background — you can move or cancel it any time before it goes out.`
              : "Pick a new time for this publish."}
          </Text>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
            keyboardShouldPersistTaps="handled"
          >
            <Text style={styles.fieldLabel}>New time</Text>
            <DateTimeField
              initialDate={initialDate}
              onChange={setWhen}
              disabled={submitting}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>

          <View style={styles.summaryRow}>
            <Text style={styles.summaryText}>
              {timeValid
                ? "Ready to move this publish"
                : "Pick a future time to reschedule"}
            </Text>
          </View>

          <Pressable
            style={[styles.primary, !canSubmit && styles.disabled]}
            onPress={handleSubmit}
            disabled={!canSubmit}
            accessibilityRole="button"
            accessibilityState={{ disabled: !canSubmit }}
          >
            {submitting ? (
              <ActivityIndicator color="#0f0f10" />
            ) : (
              <Text style={styles.primaryText}>Reschedule</Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: "#0f0f18",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingTop: 10,
    paddingBottom: 28,
    maxHeight: "90%",
  },
  handle: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#27272a",
    marginBottom: 12,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  close: { color: "#ece9e1", fontSize: 18, fontWeight: "700" },
  subtitle: { color: "#8b8b9b", fontSize: 13, marginTop: 6, lineHeight: 18 },
  scroll: { marginTop: 12 },
  scrollContent: { gap: 12, paddingBottom: 8 },
  fieldLabel: { color: "#ece9e1", fontSize: 15, fontWeight: "600" },
  error: { color: "#E0847F", fontSize: 14 },
  summaryRow: { marginTop: 12, marginBottom: 8 },
  summaryText: { color: "#ece9e1", fontSize: 13, fontWeight: "600" },
  primary: {
    backgroundColor: "#E6C76A",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
  },
  disabled: { opacity: 0.5 },
  primaryText: { color: "#0f0f10", fontSize: 16, fontWeight: "700" },
});
