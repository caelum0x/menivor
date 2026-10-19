/**
 * Live progress + results for a one-flow run: the screen the Create tab lands
 * on after starting three hook variants. Polls every variant's
 * `GET /jobs/{id}` until all are terminal, showing each variant's hook angle,
 * current pipeline stage and what the run actually cost. Finished variants
 * play inline and can be picked, published, scheduled or edited; failed ones
 * show that their credit was refunded automatically and can be retried.
 *
 * The native port of apps/web/src/features/create-compose/one-flow/
 * VariantResults.tsx.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  AppState,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { Badge, Button, Icon, type BadgeVariant } from "@/components/ui";
import { ApiError, POLL_INTERVAL_MS, getJob, isAbortError, retryJob } from "@/lib/api";
import { isTerminalState, type Job } from "@/lib/types";
import { useSession } from "@/src/shared/auth";
import { JobVideo, jobPosterUrl, jobResultUrl } from "@/src/shared/media";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

import {
  CREDITS_PER_REEL,
  currentStageLabel,
  describeRunCost,
  formatElapsed,
  hookStyleLabel,
  runCost,
  variantPhase,
  variantProgress,
  type VariantPhase,
} from "./plan";
import { loadPick, loadRun, savePick, type RunMeta } from "./run-store";
import { isRouteAvailable } from "@/src/shared/release/surface";

/** Direct posting to connected platforms (dev sessions; store builds export instead). */
const PUBLISHING = isRouteAvailable("/connections/publish");

export interface VariantResultsScreenProps {
  readonly jobIds: readonly string[];
}

const VARIANT_LETTERS = ["A", "B", "C"] as const;
/** Stop polling after ~20 minutes; the jobs keep running server-side. */
const MAX_POLL_MS = 20 * 60 * 1000;

interface VariantState {
  readonly job?: Job;
  readonly error?: string;
}

const PHASE_BADGE: Record<VariantPhase, { label: string; variant: BadgeVariant }> = {
  queued: { label: "Queued", variant: "neutral" },
  rendering: { label: "Rendering", variant: "accent" },
  ready: { label: "Ready", variant: "success" },
  failed: { label: "Failed", variant: "danger" },
};

function angleLabel(meta: RunMeta | null, jobId: string): string {
  return hookStyleLabel(meta?.variants.find((v) => v.jobId === jobId)?.angle);
}

function hookFor(meta: RunMeta | null, jobId: string, job?: Job): string {
  const planned = meta?.variants.find((v) => v.jobId === jobId)?.hook;
  const fromJob = typeof job?.hook === "string" ? job.hook.trim() : "";
  // The API falls back to the subject until the script stage has written the
  // real hook; prefer the planned hook (link mode) in that window.
  return planned || fromJob;
}

function pollErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.status === 404) return "This reel wasn't found on your account.";
  if (err instanceof Error) return err.message;
  return "Could not load this reel.";
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });

export function VariantResultsScreen({ jobIds }: VariantResultsScreenProps) {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [meta, setMeta] = useState<RunMeta | null>(null);
  const [variants, setVariants] = useState<Record<string, VariantState>>({});
  const [picked, setPicked] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [pollNonce, setPollNonce] = useState(0);
  const [timedOut, setTimedOut] = useState(false);
  const [retrying, setRetrying] = useState("");
  const startRef = useRef<number>(Date.now());
  const idsKey = jobIds.join(",");

  useEffect(() => {
    let active = true;
    const ids = idsKey ? idsKey.split(",") : [];
    void Promise.all([loadRun(ids), loadPick(ids)]).then(([run, pick]) => {
      if (!active) return;
      setMeta(run);
      if (run) startRef.current = run.startedAt;
      setPicked(pick);
    });
    return () => {
      active = false;
    };
  }, [idsKey]);

  const allTerminal =
    jobIds.length > 0 &&
    jobIds.every((id) => {
      const job = variants[id]?.job;
      return job ? isTerminalState(job.state) : false;
    });

  // Poll every variant until all are terminal (or unknown to this account).
  useEffect(() => {
    const ids = idsKey ? idsKey.split(",") : [];
    if (ids.length === 0) return;
    const controller = new AbortController();
    const pollStart = Date.now();
    setTimedOut(false);

    const tick = async (): Promise<boolean> => {
      const results = await Promise.all(
        ids.map(async (id): Promise<[string, VariantState]> => {
          try {
            return [id, { job: await getJob(id, { token, signal: controller.signal }) }];
          } catch (err) {
            if (isAbortError(err)) throw err;
            return [id, { error: pollErrorMessage(err) }];
          }
        }),
      );
      if (controller.signal.aborted) return true;
      setVariants((prev) => {
        const next = { ...prev };
        for (const [id, state] of results) {
          // Keep the last good snapshot through a transient poll error.
          next[id] = state.job ? state : { ...prev[id], error: state.error };
        }
        return next;
      });
      return results.every(([, state]) =>
        state.job ? isTerminalState(state.job.state) : Boolean(state.error?.includes("wasn't found")),
      );
    };

    void (async () => {
      while (!controller.signal.aborted) {
        let done = false;
        try {
          // Skip network while the app is backgrounded; resume on return.
          if (AppState.currentState === "active") done = await tick();
        } catch {
          // Network hiccup: try again next interval.
        }
        if (done || controller.signal.aborted) return;
        if (Date.now() - pollStart > MAX_POLL_MS) {
          setTimedOut(true);
          return;
        }
        await sleep(POLL_INTERVAL_MS, controller.signal);
      }
    })();

    return () => controller.abort();
  }, [idsKey, token, pollNonce]);

  // Elapsed-time readout while anything is still rendering.
  useEffect(() => {
    if (allTerminal) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [allTerminal]);

  const handlePick = useCallback(
    (id: string) => {
      setPicked(id);
      void savePick(jobIds, id);
    },
    [jobIds],
  );

  const handleRetry = useCallback(
    async (id: string) => {
      setRetrying(id);
      try {
        const job = await retryJob(id, { token });
        setVariants((prev) => ({ ...prev, [id]: { job } }));
        setPollNonce((n) => n + 1);
      } catch (err) {
        const message =
          err instanceof ApiError && err.status === 402
            ? `Retrying needs ${CREDITS_PER_REEL} credit and your balance is empty.`
            : err instanceof Error
              ? err.message
              : "Retry failed.";
        setVariants((prev) => ({ ...prev, [id]: { ...prev[id], error: message } }));
      } finally {
        setRetrying("");
      }
    },
    [token],
  );

  if (jobIds.length === 0) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.muted}>There are no reels to show here.</Text>
        <Button label="Make 3 reels" onPress={() => router.replace("/(tabs)/create" as never)} />
      </View>
    );
  }

  const phases = jobIds.map((id) => variantPhase(variants[id]?.job));
  const readyCount = phases.filter((phase) => phase === "ready").length;
  const loadedAll = jobIds.every((id) => variants[id]?.job);
  const cost = runCost(phases);
  const elapsed = formatElapsed(now - startRef.current);
  const pickedJob = picked ? variants[picked]?.job : undefined;
  const pickedLetter = VARIANT_LETTERS[jobIds.indexOf(picked)] ?? "";

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.kicker}>02 / Pick the winner</Text>
      <View style={styles.statusRow} accessibilityLiveRegion="polite">
        {allTerminal ? (
          <Icon name="checkmark-circle" size={18} color={colors.success} />
        ) : (
          <ActivityIndicator color={colors.accent} size="small" />
        )}
        <Text style={[styles.body, styles.flex]}>
          {allTerminal
            ? `${readyCount} of ${jobIds.length} reels ready.`
            : `Rendering ${jobIds.length} reels. ${readyCount} ready so far. ${elapsed}`}
        </Text>
      </View>
      {!allTerminal ? (
        <Text style={styles.muted}>
          You can leave this screen. Your reels keep rendering on the server and show up under
          Jobs when they finish.
        </Text>
      ) : null}
      {loadedAll ? (
        <View style={styles.costRow}>
          <Icon name="flash-outline" size={16} color={colors.textSecondary} />
          <Text style={[styles.muted, styles.flex]}>{describeRunCost(cost)}</Text>
        </View>
      ) : null}

      {meta?.notice ? (
        <View style={styles.notice}>
          <Icon name="alert-circle-outline" size={16} color={colors.accent} />
          <Text style={[styles.body, styles.flex]}>{meta.notice}</Text>
        </View>
      ) : null}

      {timedOut ? (
        <View style={styles.notice}>
          <Text style={[styles.muted, styles.flex]}>
            This is taking longer than usual. The renders are still running on the server.
          </Text>
          <Button label="Check again" variant="secondary" size="sm" onPress={() => setPollNonce((n) => n + 1)} />
        </View>
      ) : null}

      {pickedJob && variantPhase(pickedJob) === "ready" ? (
        <View style={[styles.notice, styles.pickedCard]}>
          <View style={styles.flex}>
            <Text style={styles.bodyStrong}>Your pick: variant {pickedLetter}.</Text>
            <Text style={styles.muted}>
              {PUBLISHING
                ? "Post it now, schedule it, or polish it in the editor first."
                : "Export it to your phone, or polish it in the editor first."}
            </Text>
          </View>
          <View style={styles.actions}>
            {PUBLISHING ? (
              <>
                <Button
                  label="Publish"
                  size="sm"
                  onPress={() =>
                    router.push(`/connections/publish?jobId=${encodeURIComponent(picked)}` as never)
                  }
                />
                <Button
                  label="Schedule"
                  size="sm"
                  variant="secondary"
                  onPress={() => router.push(`/job/${encodeURIComponent(picked)}` as never)}
                />
              </>
            ) : (
              <Button
                label="Export"
                size="sm"
                onPress={() => router.push(`/job/${encodeURIComponent(picked)}` as never)}
              />
            )}
          </View>
        </View>
      ) : null}

      {jobIds.map((id, index) => (
        <VariantCard
          key={id}
          letter={VARIANT_LETTERS[index] ?? String(index + 1)}
          jobId={id}
          state={variants[id]}
          angle={angleLabel(meta, id)}
          hook={hookFor(meta, id, variants[id]?.job)}
          picked={picked === id}
          retrying={retrying === id}
          onPick={() => handlePick(id)}
          onRetry={() => void handleRetry(id)}
          onOpen={(path) => router.push(path as never)}
        />
      ))}

      <View style={styles.footer}>
        {meta?.batchId && isRouteAvailable("/insights/winners/x") ? (
          <Button
            label="Track which hook wins"
            variant="secondary"
            onPress={() =>
              router.push(`/insights/winners/${encodeURIComponent(meta.batchId ?? "")}` as never)
            }
          />
        ) : null}
        <Button label="Make 3 more" variant="secondary" onPress={() => router.replace("/(tabs)/create" as never)} />
        <Button label="Go to Jobs" variant="ghost" onPress={() => router.push("/(tabs)/jobs" as never)} />
      </View>
    </ScrollView>
  );
}

interface VariantCardProps {
  readonly letter: string;
  readonly jobId: string;
  readonly state?: VariantState;
  readonly angle: string;
  readonly hook: string;
  readonly picked: boolean;
  readonly retrying: boolean;
  readonly onPick: () => void;
  readonly onRetry: () => void;
  readonly onOpen: (path: string) => void;
}

function VariantCard({
  letter,
  jobId,
  state,
  angle,
  hook,
  picked,
  retrying,
  onPick,
  onRetry,
  onOpen,
}: VariantCardProps) {
  const job = state?.job;
  const phase = variantPhase(job);
  const badge = PHASE_BADGE[phase];
  const resultUrl = job ? jobResultUrl(job) : undefined;
  const poster = job ? jobPosterUrl(job) : undefined;
  const progress = variantProgress(job);

  return (
    <View style={[styles.card, picked && styles.cardPicked]}>
      <View style={styles.cardHead}>
        <Text style={styles.cardTitle}>Variant {letter}</Text>
        <Badge label={picked ? "Picked" : badge.label} variant={picked ? "accent" : badge.variant} />
      </View>
      {angle ? <Text style={styles.angle}>{angle}</Text> : null}
      <Text style={styles.hook}>
        {hook ? `"${hook}"` : "The hook appears once the script is written."}
      </Text>

      {phase === "ready" && resultUrl ? (
        <JobVideo uri={resultUrl} posterUri={poster} />
      ) : (
        <View style={styles.placeholder}>
          {phase === "failed" ? (
            <Icon name="alert-circle-outline" size={24} color={colors.danger} />
          ) : (
            <ActivityIndicator color={colors.textSecondary} />
          )}
          <Text style={styles.muted}>{currentStageLabel(job)}</Text>
          {phase !== "failed" ? (
            <View
              style={styles.track}
              accessibilityRole="progressbar"
              accessibilityLabel={`Variant ${letter} progress`}
              accessibilityValue={{ min: 0, max: 100, now: progress }}
            >
              <View style={[styles.fill, { width: `${progress}%` }]} />
            </View>
          ) : null}
        </View>
      )}

      {state?.error ? <Text style={styles.errorText}>{state.error}</Text> : null}

      {phase === "failed" ? (
        <View style={styles.cardSection}>
          <Text style={styles.muted}>
            {job?.error ? `${job.error} ` : ""}The credit for this reel was refunded automatically.
          </Text>
          {job?.retry_eligible !== false ? (
            <Button
              label={`Try again (${CREDITS_PER_REEL} credit)`}
              variant="secondary"
              size="sm"
              loading={retrying}
              onPress={onRetry}
            />
          ) : null}
        </View>
      ) : null}

      {phase === "ready" ? (
        <View style={styles.cardSection}>
          <Button
            label={picked ? "Picked" : "Pick this one"}
            variant={picked ? "primary" : "secondary"}
            onPress={onPick}
            accessibilityState={{ selected: picked }}
          />
          <View style={styles.actions}>
            <Button
              label={PUBLISHING ? "Publish" : "Export"}
              size="sm"
              variant="secondary"
              onPress={() =>
                onOpen(
                  PUBLISHING
                    ? `/connections/publish?jobId=${encodeURIComponent(jobId)}`
                    : `/job/${encodeURIComponent(jobId)}`,
                )
              }
            />
            <Button
              label="Edit"
              size="sm"
              variant="secondary"
              onPress={() =>
                onOpen(
                  `/editor?jobId=${encodeURIComponent(jobId)}${
                    resultUrl ? `&url=${encodeURIComponent(resultUrl)}` : ""
                  }`,
                )
              }
            />
          </View>
        </View>
      ) : null}

      <Pressable onPress={() => onOpen(`/job/${encodeURIComponent(jobId)}`)} accessibilityRole="link" hitSlop={8}>
        <Text style={styles.link}>Full details, download and schedule</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  center: { alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xl },
  kicker,
  statusRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  costRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.sm },
  flex: { flex: 1 },
  body: { color: colors.textPrimary, fontSize: typeScale.body, lineHeight: 21 },
  bodyStrong: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  errorText: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 19 },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  pickedCard: { borderColor: colors.accent },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  card: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: spacing.sm,
  },
  cardPicked: { borderColor: colors.accent, borderWidth: 2 },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cardTitle: { color: colors.textPrimary, fontSize: typeScale.subheading, fontWeight: "700" },
  angle: { ...kicker, fontSize: typeScale.micro },
  hook: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "600", lineHeight: 21 },
  placeholder: {
    aspectRatio: 9 / 16,
    maxHeight: 360,
    alignSelf: "center",
    width: "100%",
    borderRadius: radius.md,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    padding: spacing.lg,
  },
  track: {
    width: "75%",
    height: 4,
    borderRadius: radius.pill,
    backgroundColor: colors.border,
    overflow: "hidden",
  },
  fill: { height: 4, backgroundColor: colors.accent },
  cardSection: { gap: spacing.sm },
  link: { color: colors.textSecondary, fontSize: typeScale.caption, textDecorationLine: "underline" },
  footer: {
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.lg,
    marginTop: spacing.sm,
  },
});
