/**
 * MarketplaceScreen — the ClipMarket campaign board. Brands launch pay-per-view
 * campaigns and moderate their lifecycle; clippers submit clips. Every action is
 * a REAL typed call against `apps/api`:
 * - GET  /clipmarket/campaigns              → {@link listCampaigns}
 * - POST /clipmarket/campaigns              → {@link createCampaign}
 * - POST /clipmarket/campaigns/{id}/status  → {@link setCampaignStatus}
 * - POST /clipmarket/campaigns/{id}/submit  → {@link submitClip} (idempotent)
 *
 * The auth token comes from the session and is sent as `x-api-key` by the shared
 * client. Money is rendered from server micros via `formatUsdMicros`. Owns its
 * own loading / error / empty / busy state; in-flight loads are abortable.
 */

import * as React from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { colors } from "@/components/me/theme";
import { ApiError, isAbortError, makeAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import {
  createCampaign,
  listCampaigns,
  newSubmitIdempotencyKey,
  setCampaignStatus,
  submitClip,
  type Campaign,
  type CampaignStatus,
  type CreateCampaignBody,
} from "@/lib/clipmarket";

import { CampaignCard } from "./components/CampaignCard";
import { CreateCampaignForm } from "./components/CreateCampaignForm";
import { SubmitClipSheet } from "./components/SubmitClipSheet";

type Phase = "loading" | "ready" | "error";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return fallback;
}

export function MarketplaceScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;

  const [campaigns, setCampaigns] = React.useState<Campaign[]>([]);
  const [phase, setPhase] = React.useState<Phase>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const [creating, setCreating] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const [target, setTarget] = React.useState<Campaign | null>(null);
  const [submitBusy, setSubmitBusy] = React.useState(false);
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  const inFlight = React.useRef<AbortController | null>(null);

  const load = React.useCallback(
    async (mode: "initial" | "refresh") => {
      inFlight.current?.abort(makeAbortError());
      const controller = new AbortController();
      inFlight.current = controller;

      if (mode === "refresh") setRefreshing(true);
      else setPhase("loading");
      setError(null);

      try {
        const res = await listCampaigns({ token, signal: controller.signal });
        if (controller.signal.aborted) return;
        setCampaigns(res.campaigns);
        setPhase("ready");
      } catch (err) {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(errorMessage(err, "Failed to load campaigns."));
        setPhase("error");
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  React.useEffect(() => {
    void load("initial");
    return () => inFlight.current?.abort(makeAbortError());
  }, [load]);

  const onCreate = React.useCallback(
    async (body: CreateCampaignBody) => {
      setCreating(true);
      setError(null);
      try {
        await createCampaign(body, { token });
        await load("refresh");
      } catch (err) {
        setError(errorMessage(err, "Failed to create campaign."));
      } finally {
        setCreating(false);
      }
    },
    [token, load],
  );

  const onSetStatus = React.useCallback(
    async (campaign: Campaign, status: CampaignStatus) => {
      setBusyId(campaign.id);
      setError(null);
      try {
        const updated = await setCampaignStatus(campaign.id, { status }, { token });
        setCampaigns((prev) =>
          prev.map((c) => (c.id === updated.id ? updated : c)),
        );
      } catch (err) {
        setError(errorMessage(err, "Failed to update campaign."));
      } finally {
        setBusyId(null);
      }
    },
    [token],
  );

  const onConfirmSubmit = React.useCallback(
    async (clipUrl: string) => {
      if (!target) return;
      setSubmitBusy(true);
      setSubmitError(null);
      try {
        await submitClip(
          target.id,
          { clip_url: clipUrl },
          newSubmitIdempotencyKey(),
          { token },
        );
        setTarget(null);
        await load("refresh");
      } catch (err) {
        setSubmitError(errorMessage(err, "Failed to submit clip."));
      } finally {
        setSubmitBusy(false);
      }
    },
    [target, token, load],
  );

  const renderItem = React.useCallback(
    ({ item }: { item: Campaign }) => (
      <CampaignCard
        campaign={item}
        busy={busyId === item.id}
        onSetStatus={onSetStatus}
        onSubmitClip={setTarget}
      />
    ),
    [busyId, onSetStatus],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Pay creators per view. Launch a campaign, moderate it, and let clippers
        submit — verified views settle to payouts.
      </Text>
      <CreateCampaignForm submitting={creating} onSubmit={onCreate} />
      <Text style={styles.sectionTitle}>Active campaigns</Text>
    </View>
  );

  const empty = (() => {
    if (phase === "loading" && !refreshing) {
      return (
        <View style={styles.state}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.stateText}>Loading campaigns…</Text>
        </View>
      );
    }
    if (phase === "error") {
      return (
        <View style={styles.state}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable
            style={styles.retry}
            accessibilityRole="button"
            onPress={() => void load("initial")}
            testID="market-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          No active campaigns yet — launch your first one above.
        </Text>
      </View>
    );
  })();

  return (
    <>
      <FlatList
        style={styles.container}
        contentContainerStyle={styles.content}
        data={campaigns}
        keyExtractor={(c) => c.id}
        renderItem={renderItem}
        ListHeaderComponent={header}
        ListEmptyComponent={empty}
        ItemSeparatorComponent={() => <View style={styles.gap} />}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load("refresh")}
            tintColor={colors.primary}
          />
        }
        testID="marketplace-list"
      />
      <SubmitClipSheet
        campaign={target}
        submitting={submitBusy}
        error={submitError}
        onSubmit={(url) => void onConfirmSubmit(url)}
        onClose={() => {
          if (!submitBusy) setTarget(null);
        }}
      />
    </>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40 },
  header: { gap: 12, marginBottom: 12 },
  intro: { color: colors.textSecondary, fontSize: 14, lineHeight: 20 },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "800",
    marginTop: 4,
  },
  gap: { height: 12 },
  state: { alignItems: "center", gap: 12, paddingVertical: 32 },
  stateText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  errorText: { color: colors.error, fontSize: 14, textAlign: "center" },
  retry: {
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  retryText: { color: colors.primary, fontSize: 14, fontWeight: "700" },
});
