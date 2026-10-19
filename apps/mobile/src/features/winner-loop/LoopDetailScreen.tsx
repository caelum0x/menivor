/**
 * One project's winner loop: status, "Check now", one-tap "Remake winner"
 * (with a confirmation for low-confidence winners), loop settings, why it
 * won, the ranked variants and the loop timeline across remake rounds.
 *
 * The native port of apps/web/app/insights/winners/[batchId]/page.tsx.
 */

import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { useRouter } from "expo-router";

import { Badge, Button, Icon } from "@/components/ui";
import { isAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { colors, kicker, radius, spacing, typeScale } from "@/src/shared/theme";

import { checkLoopNow, configureLoop, getLoop, remakeWinner } from "./api";
import { LoopSettingsCard } from "./components/LoopSettingsCard";
import { LoopTimeline } from "./components/LoopTimeline";
import { VariantRanking } from "./components/VariantRanking";
import { WhyItWon } from "./components/WhyItWon";
import {
  MODE_LABELS,
  errorMessageOf,
  formatWhen,
  isCollecting,
  relativeTime,
  remakeAction,
  remakeNotice,
  statusLabel,
} from "./format";
import type { LoopConfigInput, LoopDetail } from "./types";

type Action = "idle" | "saving" | "checking" | "remaking";

export interface LoopDetailScreenProps {
  readonly batchId: string;
}

export function LoopDetailScreen({ batchId }: LoopDetailScreenProps) {
  const router = useRouter();
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const [detail, setDetail] = useState<LoopDetail | null>(null);
  const [loadError, setLoadError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [action, setAction] = useState<Action>("idle");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [confirmLowConfidence, setConfirmLowConfidence] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setDetail(await getLoop(batchId, { token, signal }));
        setLoadError("");
      } catch (err) {
        if (isAbortError(err)) return;
        setLoadError(errorMessageOf(err, "Something went wrong loading this project."));
      } finally {
        setRefreshing(false);
      }
    },
    [batchId, token],
  );

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setConfirmLowConfidence(false);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const run = async (kind: Action, fn: () => Promise<void>) => {
    setAction(kind);
    setActionError("");
    setActionNotice("");
    try {
      await fn();
    } catch (err) {
      setActionError(errorMessageOf(err, "That did not work. Please try again."));
    } finally {
      setAction("idle");
    }
  };

  const save = (input: LoopConfigInput) =>
    void run("saving", async () => {
      setDetail(await configureLoop(batchId, input, { token }));
      setActionNotice(input.mode === "off" ? "Loop turned off." : "Loop settings saved.");
    });

  const checkNow = () =>
    void run("checking", async () => {
      setDetail(await checkLoopNow(batchId, { token }));
      setActionNotice("Numbers refreshed from the platforms.");
    });

  const remake = () =>
    void run("remaking", async () => {
      if (!detail) return;
      const next = remakeAction(detail, confirmLowConfidence);
      if (!next) return;
      if (next.needsConfirm) {
        setConfirmLowConfidence(true);
        return;
      }
      const result = await remakeWinner(batchId, !detail.conclusive, { token });
      setConfirmLowConfidence(false);
      setActionNotice(remakeNotice(result));
      await load();
    });

  const openBatch = (id: string) => router.push(`/insights/winners/${encodeURIComponent(id)}` as never);

  if (!detail) {
    return (
      <View style={[styles.container, styles.center]}>
        {loadError ? (
          <>
            <Text style={styles.strong}>Couldn&apos;t load this project</Text>
            <Text style={styles.muted}>{loadError}</Text>
            <Button label="Try again" variant="secondary" onPress={() => void load()} />
          </>
        ) : (
          <ActivityIndicator color={colors.accent} size="large" />
        )}
      </View>
    );
  }

  const hasWinner = Boolean(detail.winner_job_id);
  const remakeButton = remakeAction(detail, confirmLowConfidence);
  const busy = action !== "idle";

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            void load();
          }}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={styles.kicker}>Winner loop · round {detail.generation}</Text>
      <Text style={styles.title}>{detail.title}</Text>
      <View style={styles.row}>
        <Badge label={statusLabel(detail.status)} variant={detail.status === "winner_ready" ? "success" : "neutral"} />
        {detail.configured ? <Badge label={MODE_LABELS[detail.mode]} /> : null}
      </View>
      {detail.check_due_at && isCollecting(detail.status) ? (
        <Text style={styles.muted}>
          Next check {formatWhen(detail.check_due_at)} ({relativeTime(detail.check_due_at)})
        </Text>
      ) : null}

      <View style={styles.row}>
        {detail.configured ? (
          <Button
            label={action === "checking" ? "Reading numbers" : "Check now"}
            size="sm"
            variant="secondary"
            loading={action === "checking"}
            disabled={busy}
            onPress={checkNow}
          />
        ) : null}
        {remakeButton ? (
          <Button
            label={action === "remaking" ? "Starting remake" : remakeButton.label}
            size="sm"
            loading={action === "remaking"}
            disabled={busy}
            onPress={remake}
          />
        ) : null}
        {detail.remake_batch_id ? (
          <Button
            label="Open next round"
            size="sm"
            variant="secondary"
            onPress={() => openBatch(detail.remake_batch_id)}
          />
        ) : null}
      </View>

      {confirmLowConfidence ? (
        <View style={styles.notice}>
          <Text style={styles.body}>
            This winner is low-confidence ({detail.ranking_reason || "the numbers were close"}). Tap
            confirm to spend {detail.remake_cost_credits} credits remaking it anyway.
          </Text>
          <Button label="Not now" size="sm" variant="ghost" onPress={() => setConfirmLowConfidence(false)} />
        </View>
      ) : null}
      {detail.note ? (
        <View style={styles.notice}>
          <Icon name="information-circle-outline" size={16} color={colors.textSecondary} />
          <Text style={[styles.muted, styles.flex]}>{detail.note}</Text>
        </View>
      ) : null}
      {actionError ? (
        <Text style={styles.error} accessibilityRole="alert">
          {actionError}
        </Text>
      ) : null}
      {actionNotice ? <Text style={styles.success}>{actionNotice}</Text> : null}

      {detail.remake_hooks.length > 0 ? (
        <View style={styles.notice}>
          <View style={styles.flex}>
            <Text style={styles.strong}>New hooks in the next round</Text>
            {detail.remake_hooks.map((hook) => (
              <Text key={hook} style={styles.muted}>
                {"•"} {hook}
              </Text>
            ))}
          </View>
        </View>
      ) : null}

      <LoopSettingsCard
        detail={detail}
        saving={action === "saving"}
        onSave={save}
        onManageConnections={() => router.push("/connections/manage" as never)}
      />
      <WhyItWon explanation={detail.explanation} earlyRead={detail.early_read} hasWinner={hasWinner} />
      <VariantRanking
        variants={detail.variants}
        usesRetention={detail.uses_retention}
        rankingReason={detail.ranking_reason}
        onOpenReel={(jobId) => router.push(`/job/${encodeURIComponent(jobId)}` as never)}
      />
      <LoopTimeline items={detail.timeline} lineage={detail.lineage} onSelectBatch={openBatch} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.lg, gap: spacing.md, paddingBottom: 48 },
  center: { alignItems: "center", justifyContent: "center", gap: spacing.md, padding: spacing.xl },
  kicker,
  title: { color: colors.textPrimary, fontSize: typeScale.heading, fontWeight: "800" },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm },
  notice: {
    flexDirection: "row",
    alignItems: "flex-start",
    flexWrap: "wrap",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  flex: { flex: 1 },
  strong: { color: colors.textPrimary, fontSize: typeScale.body, fontWeight: "700" },
  body: { color: colors.textPrimary, fontSize: typeScale.caption, lineHeight: 19 },
  muted: { color: colors.textSecondary, fontSize: typeScale.caption, lineHeight: 19 },
  error: { color: colors.danger, fontSize: typeScale.caption, lineHeight: 19 },
  success: { color: colors.success, fontSize: typeScale.caption, lineHeight: 19 },
});
