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
import { useRouter } from "expo-router";

import { ApiError, getConnections, schedulePublish } from "@/lib/api";
import type { ScheduledPublish, YoutubePrivacyStatus } from "@/lib/types";

import { DateTimeField } from "./DateTimeField";
import { PlatformChips } from "./PlatformChips";
import { defaultScheduleAt, toIsoUtc } from "./datetime";
import {
  PLATFORM_OPTIONS,
  PRIVACY_OPTIONS,
  YOUTUBE_PLATFORM,
} from "./platforms";
import { Icon } from "@/components/ui/Icon";
import { isRouteAvailable } from "@/src/shared/release/surface";

/**
 * "Schedule publish" bottom sheet. From a finished reel, the creator multi-selects
 * target platforms and a future local time; on submit the time is converted to an
 * ISO-8601 UTC instant and POSTed to `/jobs/{id}/schedule`. A YouTube-privacy
 * selector appears only while `youtube_shorts` is chosen. Selection is held
 * immutably (a Set of platform ids). On success the created schedule is handed
 * back to the caller. Owns its own loading + error state; no secrets here.
 */
export interface ScheduleSheetProps {
  visible: boolean;
  /** The finished (complete) source job to schedule. */
  jobId: string;
  /** Signed-in user's API key (x-api-key), or undefined for the app key. */
  token?: string;
  onClose: () => void;
  /** Called with the created schedule after a successful submit. */
  onScheduled: (result: ScheduledPublish) => void;
}

function describe(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function ScheduleSheet({
  visible,
  jobId,
  token,
  onClose,
  onScheduled,
}: Readonly<ScheduleSheetProps>) {
  const router = useRouter();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [connectedProviders, setConnectedProviders] = useState<ReadonlySet<string>>(
    new Set(),
  );
  const [connectionsLoading, setConnectionsLoading] = useState(false);
  const [when, setWhen] = useState<Date | null>(null);
  const [privacy, setPrivacy] = useState<YoutubePrivacyStatus>("private");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A fresh default instant (~1h out) each time the sheet opens.
  const initialDate = useMemo(() => defaultScheduleAt(), [visible]);

  // Reset selection/time/error whenever the sheet is reopened.
  useEffect(() => {
    let active = true;
    if (visible) {
      setSelected(new Set());
      setWhen(null);
      setPrivacy("private");
      setError(null);
      setSubmitting(false);
      setConnectionsLoading(true);
      getConnections({ token })
        .then((connections) => {
          if (!active) return;
          setConnectedProviders(
            new Set(
              connections
                .filter((connection) => connection.status === "connected")
                .map((connection) => String(connection.provider)),
            ),
          );
        })
        .catch((err) => {
          if (!active) return;
          setConnectedProviders(new Set());
          setError(describe(err, "Failed to load connected accounts."));
        })
        .finally(() => {
          if (active) setConnectionsLoading(false);
        });
    }
    return () => {
      active = false;
    };
  }, [token, visible]);

  const availablePlatforms = useMemo(
    () =>
      PLATFORM_OPTIONS.filter((platform) =>
        connectedProviders.has(
          platform.id === YOUTUBE_PLATFORM ? "youtube" : platform.id,
        ),
      ),
    [connectedProviders],
  );

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectedCount = selected.size;
  const youtubeSelected = selected.has(YOUTUBE_PLATFORM);
  const timeValid = when !== null && when.getTime() > Date.now();
  const canSubmit =
    selectedCount > 0 && timeValid && !submitting && !connectionsLoading;

  const handleSubmit = useCallback(async () => {
    if (when === null || selected.size === 0) return;
    setSubmitting(true);
    setError(null);

    // Preserve canonical platform order for a stable, predictable request.
    const platforms = availablePlatforms.map((p) => p.id).filter((id) =>
      selected.has(id),
    );

    try {
      const result = await schedulePublish(
        jobId,
        {
          platforms,
          scheduled_at: toIsoUtc(when),
          ...(youtubeSelected ? { youtube_privacy_status: privacy } : {}),
        },
        { token },
      );
      onScheduled(result);
    } catch (err) {
      setError(describe(err, "Failed to schedule publish."));
      setSubmitting(false);
    }
  }, [availablePlatforms, jobId, selected, when, youtubeSelected, privacy, token, onScheduled]);

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
            <Text style={styles.title}>Schedule publish</Text>
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
            Auto-publish this finished reel to the platforms you pick at a future
            time. We publish it in the background — you can cancel any time before
            it goes out.
          </Text>

          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
            keyboardShouldPersistTaps="handled"
          >
            <Text style={styles.fieldLabel}>Platforms</Text>
            {connectionsLoading ? (
              <ActivityIndicator color="#E6C76A" />
            ) : availablePlatforms.length > 0 ? (
              <PlatformChips
                platforms={availablePlatforms}
                selected={selected}
                onToggle={toggle}
                disabled={submitting}
              />
            ) : (
              <Text style={styles.emptyConnections}>
                Connect TikTok, Instagram, or YouTube before scheduling.
              </Text>
            )}
            {isRouteAvailable("/connections/manage") ? (
              <Pressable
                style={styles.connectionLink}
                onPress={() => {
                  onClose();
                  router.push("/connections/manage");
                }}
                accessibilityRole="link"
              >
                <Text style={styles.connectionLinkText}>Manage connected accounts</Text>
              </Pressable>
            ) : null}

            {youtubeSelected ? (
              <>
                <Text style={styles.fieldLabel}>YouTube visibility</Text>
                <View style={styles.privacyRow}>
                  {PRIVACY_OPTIONS.map((option) => {
                    const active = privacy === option.id;
                    return (
                      <Pressable
                        key={option.id}
                        style={[
                          styles.privacyChip,
                          active && styles.privacyChipActive,
                          submitting && styles.disabled,
                        ]}
                        onPress={() => setPrivacy(option.id)}
                        disabled={submitting}
                        accessibilityRole="radio"
                        accessibilityState={{ selected: active }}
                        accessibilityLabel={`YouTube ${option.label}`}
                      >
                        <Text
                          style={[
                            styles.privacyText,
                            active && styles.privacyTextActive,
                          ]}
                        >
                          {option.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </>
            ) : null}

            <Text style={styles.fieldLabel}>When</Text>
            <DateTimeField
              initialDate={initialDate}
              onChange={setWhen}
              disabled={submitting}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}
          </ScrollView>

          <View style={styles.summaryRow}>
            <Text style={styles.summaryText}>
              {selectedCount === 0
                ? "Select at least one platform"
                : `${selectedCount} platform${
                    selectedCount === 1 ? "" : "s"
                  }${timeValid ? "" : " · pick a future time"}`}
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
              <Text style={styles.primaryText}>
                {selectedCount > 0
                  ? `Schedule ${selectedCount} platform${
                      selectedCount === 1 ? "" : "s"
                    }`
                  : "Schedule publish"}
              </Text>
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
  emptyConnections: { color: "#9b98aa", fontSize: 13, lineHeight: 19 },
  connectionLink: { alignSelf: "flex-start", paddingVertical: 10 },
  connectionLinkText: { color: "#E6C76A", fontSize: 13, fontWeight: "700" },
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
  privacyRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  privacyChip: {
    backgroundColor: "#0f0f10",
    borderColor: "#27272a",
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  privacyChipActive: { backgroundColor: "#E6C76A", borderColor: "#E6C76A" },
  privacyText: { color: "#ece9e1" },
  privacyTextActive: { color: "#ece9e1", fontWeight: "700" },
  error: { color: "#E0847F", fontSize: 14 },
  summaryRow: {
    marginTop: 12,
    marginBottom: 8,
  },
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
