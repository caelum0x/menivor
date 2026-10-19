/**
 * HOOK PERFORMANCE — the creator's win-loop screen.
 *
 * Top: WINNING HOOKS, the caller's hooks ranked by a deterministic win_score
 * over the reels they've logged (empty until they log some). Bottom: LOG A
 * REEL — pick one of your finished reels and self-report its real-world outcome
 * (views/likes/comments/shares/saves + watch-through %). Logging is an
 * idempotent upsert (re-logging a reel updates its row), and a successful log
 * reloads the winning-hooks ranking so the leaderboard reflects it immediately.
 *
 * Everything is strictly caller-scoped: the auth token comes from the session
 * and is sent as `x-api-key` by the shared api client. No secrets live here.
 * The two sections own independent loading/error state so a failure in one
 * never blanks the other.
 */

import { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import {
  getJobPerformance,
  getWinningHooks,
  isAbortError,
  listJobs,
  logJobPerformance,
} from "@/lib/api";
import { useSession } from "@/src/shared/auth";
import {
  JobState,
  type Job,
  type JobPerformance,
  type LogPerformanceRequest,
  type WinningHook,
} from "@/lib/types";

import { Section, SectionState } from "@/components/me/Section";
import { describeError } from "@/components/me/errors";
import { useResource } from "@/components/me/use-resource";
import { colors } from "@/components/me/theme";
import { WinningHookCard } from "@/components/performance/WinningHookCard";
import { JobPicker } from "@/components/performance/JobPicker";
import { LogPerformanceForm } from "@/components/performance/LogPerformanceForm";

/** How many winning hooks to surface (backend clamps to 1..100). */
const WINNING_HOOKS_LIMIT = 20;

export default function PerformanceScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  // --- Winning hooks leaderboard -------------------------------------------
  const hooksFetcher = useCallback(
    () => getWinningHooks(WINNING_HOOKS_LIMIT, { token }),
    [token],
  );
  const hooks = useResource<WinningHook[]>(hooksFetcher);

  // --- Finished reels available to log -------------------------------------
  const jobsFetcher = useCallback(() => listJobs({ token }), [token]);
  const jobs = useResource<Job[]>(jobsFetcher);
  const completed = (jobs.data ?? []).filter(
    (j) => j.state === JobState.Complete,
  );

  // --- Selected reel + its existing (pre-fill) row -------------------------
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [existing, setExisting] = useState<JobPerformance | null>(null);
  const [logging, setLogging] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [logSuccess, setLogSuccess] = useState<string | null>(null);

  // Auto-select the first finished reel once the list loads.
  useEffect(() => {
    if (selectedJobId === null && completed.length > 0) {
      setSelectedJobId(completed[0].job_id);
    }
  }, [completed, selectedJobId]);

  // Load any previously-logged metrics for the selected reel to pre-fill the
  // form. A 404 (never logged) is expected and simply leaves the form blank.
  useEffect(() => {
    setLogError(null);
    setLogSuccess(null);
    if (!selectedJobId) {
      setExisting(null);
      return;
    }
    let active = true;
    setExisting(null);
    getJobPerformance(selectedJobId, { token })
      .then((row) => {
        if (active) setExisting(row);
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setExisting(null);
      });
    return () => {
      active = false;
    };
  }, [selectedJobId, token]);

  const onSelectJob = useCallback((jobId: string) => {
    setSelectedJobId(jobId);
  }, []);

  const onSubmit = useCallback(
    async (body: LogPerformanceRequest) => {
      if (!selectedJobId) return;
      setLogging(true);
      setLogError(null);
      setLogSuccess(null);
      try {
        const row = await logJobPerformance(selectedJobId, body, { token });
        setExisting(row);
        setLogSuccess("Saved. Your winning hooks are updated below.");
        hooks.reload();
      } catch (err) {
        setLogError(describeError(err, "Failed to log metrics."));
      } finally {
        setLogging(false);
      }
    },
    [selectedJobId, token, hooks],
  );

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.intro}>
        Log how your posted reels actually performed and Menivor learns which
        hooks convert. Winning hooks bubble to the top and bias Spark to suggest
        more like them.
      </Text>

      <Section
        title="LOG A REEL"
        action={null}
      >
        <SectionState
          status={jobs.status}
          error={jobs.error}
          onRetry={jobs.reload}
          loadingLabel="Loading your reels…"
        >
          <View style={styles.logBlock}>
            <JobPicker
              jobs={completed}
              selectedJobId={selectedJobId}
              onSelect={onSelectJob}
            />

            {selectedJobId ? (
              <LogPerformanceForm
                loading={logging}
                initial={existing}
                onSubmit={onSubmit}
              />
            ) : null}

            {logError ? <Text style={styles.error}>{logError}</Text> : null}
            {logSuccess ? (
              <Text style={styles.success}>{logSuccess}</Text>
            ) : null}
          </View>
        </SectionState>
      </Section>

      <View style={styles.divider} />

      <Section title="WINNING HOOKS">
        <SectionState
          status={hooks.status}
          error={hooks.error}
          onRetry={hooks.reload}
          loadingLabel="Loading winning hooks…"
        >
          {hooks.data && hooks.data.length > 0 ? (
            <View style={styles.hooksList}>
              {hooks.data.map((hook, i) => (
                <WinningHookCard
                  key={`${hook.hook || "hook"}-${i}`}
                  hook={hook}
                  rank={i + 1}
                />
              ))}
            </View>
          ) : (
            <Text style={styles.muted}>
              No winning hooks yet. Log a few reels above and your best-
              converting hooks will show up here.
            </Text>
          )}
        </SectionState>
      </Section>

      <View style={styles.spacer} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20, paddingTop: 24 },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 20,
  },
  logBlock: { gap: 16 },
  error: { color: colors.error, fontSize: 14 },
  success: { color: colors.success, fontSize: 14 },
  muted: { color: colors.muted, fontSize: 13, lineHeight: 19 },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 8 },
  hooksList: { gap: 12 },
  spacer: { height: 40 },
});
