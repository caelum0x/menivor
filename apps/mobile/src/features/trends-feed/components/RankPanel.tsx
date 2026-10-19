/**
 * The candidate-scoring panel for the Trends Feed. A creator pastes observed
 * usage series ("id: 100,400,1200" per line); we score them against the REAL
 * backend (`POST /trends/rank`) and can persist the winners into the durable
 * recommended feed (`POST /trends/observe`). All numbers come from the pipeline
 * scorer — no client-side math (this replaces the old `trend-lab` screen).
 */

import * as React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import {
  observeTrends,
  parseTrendLines,
  rankTrends,
  type ScoredTrend,
} from "@/lib/trends";

import { TrendCard, type TrendCardData } from "./TrendCard";

const PLACEHOLDER =
  "dance_sound: 100,400,1200,3000\nold_meme: 99000,99100,99050,99000";

interface RankPanelProps {
  token?: string;
  /** Called after candidates are persisted, so the feed can refresh. */
  onObserved: () => void;
  onCompose: (trend: TrendCardData) => void;
}

function RankPanelBase({ token, onObserved, onCompose }: RankPanelProps) {
  const [text, setText] = React.useState("");
  const [ranked, setRanked] = React.useState<ScoredTrend[]>([]);
  const [scoring, setScoring] = React.useState(false);
  const [observing, setObserving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  const candidates = React.useMemo(() => parseTrendLines(text), [text]);
  const hasCandidates = candidates.length > 0;
  const busy = scoring || observing;

  const onScore = React.useCallback(async () => {
    if (!hasCandidates) {
      setError("Add at least one line like \"id: 100,400,1200\".");
      return;
    }
    setScoring(true);
    setError(null);
    setNotice(null);
    try {
      const res = await rankTrends(candidates, { token });
      setRanked(res.trends);
      if (res.trends.length === 0) setNotice("No trends scored.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to score trends.");
    } finally {
      setScoring(false);
    }
  }, [candidates, hasCandidates, token]);

  const onObserve = React.useCallback(async () => {
    if (!hasCandidates) {
      setError("Add at least one line like \"id: 100,400,1200\".");
      return;
    }
    setObserving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await observeTrends(candidates, { token });
      setNotice(
        `Saved ${res.observed.length} trend${
          res.observed.length === 1 ? "" : "s"
        } to the feed.`,
      );
      onObserved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save trends.");
    } finally {
      setObserving(false);
    }
  }, [candidates, hasCandidates, onObserved, token]);

  return (
    <View style={styles.panel}>
      <Text style={styles.heading}>Score your own candidates</Text>
      <Text style={styles.help}>
        Paste series as "id: count,count,…" (one per line). Scoring is done by the
        pipeline — build before the peak.
      </Text>

      <TextInput
        style={styles.textarea}
        multiline
        autoCapitalize="none"
        autoCorrect={false}
        placeholder={PLACEHOLDER}
        placeholderTextColor={colors.muted}
        value={text}
        onChangeText={(t) => {
          setText(t);
          if (error) setError(null);
        }}
        testID="rank-input"
      />
      <Text style={styles.count}>
        {candidates.length} candidate{candidates.length === 1 ? "" : "s"}
      </Text>

      <View style={styles.actions}>
        <Pressable
          style={[styles.btn, styles.btnPrimary, busy && styles.btnDisabled]}
          disabled={busy}
          accessibilityRole="button"
          onPress={() => void onScore()}
          testID="rank-score-btn"
        >
          {scoring ? (
            <ActivityIndicator color={colors.textPrimary} />
          ) : (
            <Text style={styles.btnText}>Score</Text>
          )}
        </Pressable>
        <Pressable
          style={[styles.btn, styles.btnGhost, busy && styles.btnDisabled]}
          disabled={busy}
          accessibilityRole="button"
          onPress={() => void onObserve()}
          testID="rank-observe-btn"
        >
          {observing ? (
            <ActivityIndicator color={colors.accent} />
          ) : (
            <Text style={[styles.btnText, styles.btnGhostText]}>
              Save to feed
            </Text>
          )}
        </Pressable>
      </View>

      {error ? (
        <Text style={styles.error} testID="rank-error">
          {error}
        </Text>
      ) : null}
      {notice ? (
        <Text style={styles.notice} testID="rank-notice">
          {notice}
        </Text>
      ) : null}

      {ranked.length > 0 ? (
        <View style={styles.results}>
          {ranked.map((t) => (
            <TrendCard key={t.trend_id} trend={t} onCompose={onCompose} />
          ))}
        </View>
      ) : null}
    </View>
  );
}

export const RankPanel = React.memo(RankPanelBase);

const styles = StyleSheet.create({
  panel: {
    gap: 8,
    paddingVertical: 4,
  },
  heading: {
    color: colors.textPrimary,
    fontSize: 17,
    fontWeight: "700",
  },
  help: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 18,
  },
  textarea: {
    minHeight: 96,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    color: colors.textPrimary,
    backgroundColor: colors.card,
    fontSize: 14,
    textAlignVertical: "top",
  },
  count: {
    color: colors.muted,
    fontSize: 12,
  },
  actions: {
    flexDirection: "row",
    gap: 10,
  },
  btn: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  btnPrimary: {
    backgroundColor: colors.primary,
  },
  btnGhost: {
    borderColor: colors.accent,
    borderWidth: 1,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnText: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "700",
  },
  btnGhostText: {
    color: colors.accent,
  },
  error: {
    color: colors.error,
    fontSize: 13,
  },
  notice: {
    color: colors.success,
    fontSize: 13,
  },
  results: {
    gap: 12,
    marginTop: 8,
  },
});
