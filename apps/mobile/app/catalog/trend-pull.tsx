/**
 * Pull Trends — enqueue a ToS-gated trend scrape into the durable feed.
 *
 * The read/rank surfaces (Trends Feed, Trend Lab, diffusion forecast) can only
 * observe and score trends the pipeline already ingested; there was no way to
 * pull FRESH trends on demand. This screen wires the missing trigger:
 *
 *   POST /api/v1/trends/pull  — validate target (allowlist) + consent, debit the
 *                               pull cost, enqueue a worker scrape job.
 *
 * Because the scrape runs on the worker, the response only confirms the job was
 * accepted; we track every enqueued pull as a live row and poll GET /jobs/{id}
 * until it is terminal, then point the creator at the refreshed feed.
 *
 * The MANDATORY consent gate (`trend_scraping`, GDPR/ToS) is enforced here too:
 * we read the caller's consent trail and, if not granted, surface a grant action
 * (PUT /me/consent) with a confirmation before any pull can be started.
 *
 * NAV MANIFEST (routes for the integration agent to wire into navigation):
 *   { route: "/catalog/trend-pull", title: "Pull Trends" }
 * Deep-links out to:
 *   { route: "/trends-feed",        title: "Trends Feed" }
 *
 * Route: /catalog/trend-pull
 */

import type { ReactElement } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { ApiError, POLL_INTERVAL_MS } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import {
  getConsentTrail,
  latestConsents,
  recordConsent,
} from "@/lib/compliance";
import { getJob } from "@/lib/api";
import {
  JobState,
  isTerminalState,
  isFailedState,
  type JobStateValue,
} from "@/lib/types";
import {
  pullTrend,
  TREND_SCRAPING_CONSENT_KIND,
  type PullKind,
} from "@/lib/trends";

// ---------------------------------------------------------------------------
// Local model
// ---------------------------------------------------------------------------

/** A pull the creator started this session, plus its latest polled job state. */
interface PullJob {
  jobId: string;
  target: string;
  kind: PullKind;
  state: JobStateValue;
  progress: number;
  error?: string;
  correlationId?: string;
  submittedAt: number;
}

const KIND_OPTIONS: readonly { value: PullKind; label: string }[] = [
  { value: "hashtag", label: "Hashtag" },
  { value: "sound", label: "Sound" },
  { value: "trending", label: "For You" },
];

const MAX_POSTS_DEFAULT = 50;
const MAX_POSTS_MIN = 1;
const MAX_POSTS_MAX = 500;

// ---------------------------------------------------------------------------
// Presentation helpers
// ---------------------------------------------------------------------------

function stateLabel(state: JobStateValue): string {
  if (state === JobState.Complete) return "Complete";
  if (isFailedState(state)) return "Failed";
  return "Scraping";
}

function stateColor(state: JobStateValue): string {
  if (state === JobState.Complete) return colors.success;
  if (isFailedState(state)) return colors.error;
  return colors.accent;
}

function kindLabel(kind: PullKind): string {
  return KIND_OPTIONS.find((k) => k.value === kind)?.label ?? kind;
}

function targetSummary(job: PullJob): string {
  if (job.kind === "trending") return "For-You feed";
  return `#${job.target}`;
}

/** Map a failed pull to a creator-facing message (never leak raw internals). */
function pullErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const message = err.message || "";
    if (err.status === 402) {
      return "Not enough pull credits. Top up your balance to pull fresh trends.";
    }
    if (err.status === 403) {
      if (/consent/i.test(message)) {
        return "Trend scraping consent is required before you can pull.";
      }
      return "That target is not on the deployer's scraping allowlist. Try the For-You feed or an allowed tag.";
    }
    if (err.status === 503) {
      return "Trend pulling is not enabled on this deployment yet.";
    }
    if (message) return message;
  }
  return err instanceof Error ? err.message : "Failed to start the pull.";
}

function relativeTime(ts: number): string {
  const secs = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  return `${hours}h ago`;
}

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

export default function TrendPullScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  // Consent gate -----------------------------------------------------------
  const [consentStatus, setConsentStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [consentGranted, setConsentGranted] = useState(false);
  const [consentError, setConsentError] = useState("");
  const [grantBusy, setGrantBusy] = useState(false);

  const loadConsent = useCallback(async () => {
    setConsentStatus("loading");
    setConsentError("");
    try {
      const trail = await getConsentTrail({ token });
      const current = latestConsents(trail);
      setConsentGranted(current[TREND_SCRAPING_CONSENT_KIND] === true);
      setConsentStatus("ready");
    } catch (err) {
      setConsentError(
        err instanceof Error ? err.message : "Failed to check consent.",
      );
      setConsentStatus("error");
    }
  }, [token]);

  useEffect(() => {
    void loadConsent();
  }, [loadConsent]);

  const onGrantConsent = useCallback(() => {
    Alert.alert(
      "Allow trend scraping",
      "Grant consent to scrape public hashtags, sounds and the For-You feed to seed your trends feed. This is recorded against your account and can be withdrawn on the Privacy screen.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Grant",
          onPress: () => {
            void (async () => {
              setGrantBusy(true);
              setConsentError("");
              try {
                const record = await recordConsent(
                  TREND_SCRAPING_CONSENT_KIND,
                  true,
                  { token },
                );
                setConsentGranted(record.granted);
              } catch (err) {
                setConsentError(
                  err instanceof Error ? err.message : "Failed to grant consent.",
                );
              } finally {
                setGrantBusy(false);
              }
            })();
          },
        },
      ],
    );
  }, [token]);

  // Pull form --------------------------------------------------------------
  const [kind, setKind] = useState<PullKind>("hashtag");
  const [target, setTarget] = useState("");
  const [maxPostsText, setMaxPostsText] = useState(String(MAX_POSTS_DEFAULT));
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const trimmedTarget = target.trim().replace(/^#+/, "");
  const needsTarget = kind !== "trending";
  const targetError =
    needsTarget && trimmedTarget.length === 0
      ? "Enter a hashtag or sound to scrape."
      : "";

  const maxPosts = Number.parseInt(maxPostsText, 10);
  const maxPostsError =
    !Number.isFinite(maxPosts) ||
    maxPosts < MAX_POSTS_MIN ||
    maxPosts > MAX_POSTS_MAX
      ? `Sample size must be ${MAX_POSTS_MIN}–${MAX_POSTS_MAX}.`
      : "";

  const canSubmit =
    consentGranted &&
    !submitBusy &&
    (!needsTarget || trimmedTarget.length > 0) &&
    !maxPostsError;

  // Enqueued pulls ---------------------------------------------------------
  const [jobs, setJobs] = useState<PullJob[]>([]);
  const jobsRef = useRef<PullJob[]>([]);
  jobsRef.current = jobs;
  const [refreshing, setRefreshing] = useState(false);

  const pollActive = useCallback(async () => {
    const active = jobsRef.current.filter((j) => !isTerminalState(j.state));
    if (active.length === 0) return;
    await Promise.all(
      active.map(async (job) => {
        try {
          const snap = await getJob(job.jobId, { token });
          setJobs((prev) =>
            prev.map((p) =>
              p.jobId === job.jobId
                ? {
                    ...p,
                    state: snap.state,
                    progress:
                      typeof snap.progress === "number"
                        ? snap.progress
                        : p.progress,
                    error: snap.error ?? p.error,
                    correlationId: snap.correlation_id ?? p.correlationId,
                  }
                : p,
            ),
          );
        } catch {
          // Transient poll failure: keep the last known snapshot, retry next tick.
        }
      }),
    );
  }, [token]);

  const hasActive = jobs.some((j) => !isTerminalState(j.state));

  useEffect(() => {
    if (!hasActive) return;
    const id = setInterval(() => void pollActive(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [hasActive, pollActive]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void pollActive().finally(() => setRefreshing(false));
  }, [pollActive]);

  const doPull = useCallback(async () => {
    setSubmitBusy(true);
    setSubmitError("");
    try {
      const result = await pullTrend(
        { target: trimmedTarget, kind, max_posts: maxPosts },
        { token },
      );
      const next: PullJob = {
        jobId: result.job_id,
        target: result.target,
        kind,
        state: JobState.Processing,
        progress: 0,
        submittedAt: Date.now(),
      };
      setJobs((prev) => [next, ...prev]);
      if (needsTarget) setTarget("");
    } catch (err) {
      setSubmitError(pullErrorMessage(err));
    } finally {
      setSubmitBusy(false);
    }
  }, [trimmedTarget, kind, maxPosts, token, needsTarget]);

  const onSubmit = useCallback(() => {
    if (!canSubmit) return;
    const what =
      kind === "trending" ? "the For-You feed" : `#${trimmedTarget}`;
    Alert.alert(
      "Pull fresh trends",
      `Scrape ${what} (up to ${maxPosts} posts), score it and add it to your feed? This spends pull credits.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Pull", onPress: () => void doPull() },
      ],
    );
  }, [canSubmit, kind, trimmedTarget, maxPosts, doPull]);

  // Rendering --------------------------------------------------------------

  const renderConsentCard = (): ReactElement => {
    if (consentStatus === "loading") {
      return (
        <View style={styles.card}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.muted}>Checking scraping consent…</Text>
        </View>
      );
    }
    if (consentStatus === "error") {
      return (
        <View style={styles.card}>
          <Text style={styles.errorText}>{consentError}</Text>
          <Pressable
            style={styles.secondaryBtn}
            onPress={() => void loadConsent()}
            accessibilityRole="button"
          >
            <Text style={styles.secondaryBtnText}>Try again</Text>
          </Pressable>
        </View>
      );
    }
    if (consentGranted) {
      return (
        <View style={styles.consentGranted}>
          <View style={[styles.dot, { backgroundColor: colors.success }]} />
          <Text style={styles.consentGrantedText}>
            Trend scraping consent granted.
          </Text>
        </View>
      );
    }
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Consent required</Text>
        <Text style={styles.cardBody}>
          Pulling scrapes public platform data. You must grant trend-scraping
          consent before starting a pull. It is recorded against your account and
          can be withdrawn any time on the Privacy screen.
        </Text>
        {consentError ? (
          <Text style={styles.errorText}>{consentError}</Text>
        ) : null}
        <Pressable
          style={[styles.primaryBtn, grantBusy && styles.btnDisabled]}
          disabled={grantBusy}
          onPress={onGrantConsent}
          accessibilityRole="button"
        >
          <Text style={styles.primaryBtnText}>
            {grantBusy ? "Granting…" : "Grant consent"}
          </Text>
        </Pressable>
      </View>
    );
  };

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Ingest fresh trends on demand. Pick a source, start a ToS-gated scrape,
        and the pipeline scores it straight into your recommended feed.
      </Text>

      {renderConsentCard()}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Start a pull</Text>

        <Text style={styles.fieldLabel}>Source</Text>
        <View style={styles.segment}>
          {KIND_OPTIONS.map((opt) => {
            const active = opt.value === kind;
            return (
              <Pressable
                key={opt.value}
                onPress={() => setKind(opt.value)}
                style={[styles.segmentBtn, active && styles.segmentBtnActive]}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
              >
                <Text
                  style={[
                    styles.segmentText,
                    active && styles.segmentTextActive,
                  ]}
                >
                  {opt.label}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {needsTarget ? (
          <>
            <Text style={styles.fieldLabel}>
              {kind === "sound" ? "Sound" : "Hashtag"}
            </Text>
            <TextInput
              style={styles.input}
              value={target}
              onChangeText={setTarget}
              placeholder={kind === "sound" ? "original-sound-id" : "dance"}
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
              editable={!submitBusy}
            />
            {targetError ? (
              <Text style={styles.fieldError}>{targetError}</Text>
            ) : null}
          </>
        ) : (
          <Text style={styles.hint}>
            Pulls the platform For-You / trending feed. No target needed.
          </Text>
        )}

        <Text style={styles.fieldLabel}>Sample size (posts)</Text>
        <TextInput
          style={styles.input}
          value={maxPostsText}
          onChangeText={setMaxPostsText}
          placeholder={String(MAX_POSTS_DEFAULT)}
          placeholderTextColor={colors.muted}
          keyboardType="number-pad"
          editable={!submitBusy}
        />
        {maxPostsError ? (
          <Text style={styles.fieldError}>{maxPostsError}</Text>
        ) : null}

        {submitError ? (
          <Text style={styles.errorText}>{submitError}</Text>
        ) : null}

        <Pressable
          style={[styles.primaryBtn, !canSubmit && styles.btnDisabled]}
          disabled={!canSubmit}
          onPress={onSubmit}
          accessibilityRole="button"
          testID="start-pull"
        >
          <Text style={styles.primaryBtnText}>
            {submitBusy ? "Starting…" : "Pull fresh trends"}
          </Text>
        </Pressable>
        {!consentGranted && consentStatus === "ready" ? (
          <Text style={styles.hint}>Grant consent above to enable pulling.</Text>
        ) : null}
      </View>

      <View style={styles.listHeadRow}>
        <Text style={styles.sectionTitle}>Your pulls</Text>
        <Pressable
          onPress={() => router.push("/trends-feed")}
          accessibilityRole="button"
          hitSlop={8}
        >
          <Text style={styles.linkText}>View feed</Text>
        </Pressable>
      </View>
    </View>
  );

  const renderItem = useCallback(
    ({ item }: { item: PullJob }): ReactElement => {
      const done = item.state === JobState.Complete;
      const failed = isFailedState(item.state);
      const pct = Math.round(Math.max(0, Math.min(1, item.progress)) * 100);
      return (
        <View style={styles.jobCard}>
          <View style={styles.jobHead}>
            <Text style={styles.jobTarget} numberOfLines={1}>
              {targetSummary(item)}
            </Text>
            <View
              style={[
                styles.badge,
                { borderColor: stateColor(item.state) },
              ]}
            >
              <Text style={[styles.badgeText, { color: stateColor(item.state) }]}>
                {stateLabel(item.state)}
              </Text>
            </View>
          </View>
          <Text style={styles.jobMeta}>
            {kindLabel(item.kind)} · {relativeTime(item.submittedAt)}
            {!done && !failed ? ` · ${pct}%` : ""}
          </Text>
          {failed && item.error ? (
            <Text style={styles.jobError} numberOfLines={2}>
              {item.error}
            </Text>
          ) : null}
          {done ? (
            <Pressable
              style={styles.secondaryBtn}
              onPress={() => router.push("/trends-feed")}
              accessibilityRole="button"
            >
              <Text style={styles.secondaryBtnText}>See it in the feed</Text>
            </Pressable>
          ) : null}
          {item.correlationId ? (
            <Text style={styles.corr}>ref {item.correlationId}</Text>
          ) : null}
        </View>
      );
    },
    [router],
  );

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={jobs}
      keyExtractor={(j) => j.jobId}
      renderItem={renderItem}
      ListHeaderComponent={header}
      ListEmptyComponent={
        <View style={styles.emptyBox}>
          <Text style={styles.emptyTitle}>No pulls yet</Text>
          <Text style={styles.emptyBody}>
            Start a pull above to scrape and score fresh trends. Enqueued pulls
            appear here and update live; pull to refresh to re-check.
          </Text>
        </View>
      }
      ItemSeparatorComponent={() => <View style={styles.gap} />}
      ListFooterComponent={<View style={styles.footer} />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.accent}
          colors={[colors.accent]}
        />
      }
      testID="trend-pull-list"
    />
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16 },
  header: { gap: 12, marginBottom: 12 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 4,
  },
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 10,
  },
  cardTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: "700" },
  cardBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  muted: { color: colors.muted, fontSize: 13 },
  fieldLabel: {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 1,
    marginTop: 2,
  },
  input: {
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    color: colors.textPrimary,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
  },
  fieldError: { color: colors.error, fontSize: 12 },
  hint: { color: colors.muted, fontSize: 12, lineHeight: 17 },
  segment: { flexDirection: "row", gap: 8 },
  segmentBtn: {
    flex: 1,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  segmentBtnActive: { backgroundColor: colors.accent, borderColor: colors.accent },
  segmentText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  segmentTextActive: { color: colors.bg, fontWeight: "700" },
  primaryBtn: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 13,
    alignItems: "center",
    marginTop: 2,
  },
  primaryBtnText: { color: "#fff", fontSize: 15, fontWeight: "700" },
  btnDisabled: { opacity: 0.5 },
  secondaryBtn: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 9,
    paddingHorizontal: 14,
    alignItems: "center",
    alignSelf: "flex-start",
  },
  secondaryBtnText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  consentGranted: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  consentGrantedText: { color: colors.textSecondary, fontSize: 13, fontWeight: "600" },
  dot: { width: 8, height: 8, borderRadius: 4 },
  listHeadRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 4,
  },
  sectionTitle: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  linkText: { color: colors.accent, fontSize: 14, fontWeight: "700" },
  jobCard: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  jobHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  jobTarget: { color: colors.textPrimary, fontSize: 15, fontWeight: "700", flex: 1 },
  jobMeta: { color: colors.muted, fontSize: 12 },
  jobError: { color: colors.error, fontSize: 12, lineHeight: 17 },
  badge: {
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  badgeText: { fontSize: 11, fontWeight: "700" },
  corr: { color: colors.muted, fontSize: 11 },
  emptyBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 20,
    gap: 6,
  },
  emptyTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  emptyBody: { color: colors.textSecondary, fontSize: 13, lineHeight: 19 },
  errorText: { color: colors.error, fontSize: 13 },
  gap: { height: 12 },
  footer: { height: 32 },
});
