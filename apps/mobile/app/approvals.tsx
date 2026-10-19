/**
 * Approvals: the unified queue of reply drafts, held posts, ad budget changes
 * and publish requests waiting on the owner. Approve (optionally with edited
 * text), reject, and leave a comment that is stored as the decision note. At
 * parity with the web /approvals page, using the same API:
 *
 *   GET  /approvals?status=&source=&limit=&offset=
 *   POST /approvals/{id}/approve | /reject   (via: "mobile")
 *   GET  /approvals/settings, PUT /approvals/settings
 *
 * Post-scheduling items follow the publishing launch gate. No emoji.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  Switch,
  Text,
  View,
} from "react-native";
import { Stack } from "expo-router";

import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { ActionButton } from "@/components/approvals/Button";
import { ui } from "@/components/approvals/styles";
import { LaunchStatusBanner } from "@/components/launch/LaunchStatusBanner";
import { colors } from "@/components/me/theme";
import {
  APPROVAL_SOURCES,
  SOURCE_LABELS,
  applyDecision,
  getApprovalSettings,
  listApprovals,
  updateApprovalSettings,
  type ApprovalFeedSettings,
  type ApprovalItem,
  type ApprovalList,
  type ApprovalSource,
  type AutoSource,
  type StatusFilter,
} from "@/lib/approvals";
import { readableApiError } from "@/lib/readable-error";
import { useSession } from "@/src/shared/auth";
import { useLaunchStatus } from "@/src/shared/hooks";

const PAGE_SIZE = 25;

function AutoSources({ token, onChanged }: Readonly<{ token?: string; onChanged: () => void }>) {
  const [settings, setSettings] = useState<ApprovalFeedSettings | null>(null);
  const [saving, setSaving] = useState<AutoSource | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getApprovalSettings({ token })
      .then((next) => active && setSettings(next))
      .catch((err: unknown) => active && setError(readableApiError(err, "Couldn't load auto-source settings.")));
    return () => {
      active = false;
    };
  }, [token]);

  const toggle = async (key: AutoSource, value: boolean) => {
    setSaving(key);
    setError("");
    try {
      setSettings(await updateApprovalSettings({ [key]: value }, { token }));
      onChanged();
    } catch (err) {
      setError(readableApiError(err, "Couldn't save that setting."));
    } finally {
      setSaving("");
    }
  };

  if (!settings && !error) return null;
  return (
    <View style={ui.card}>
      <Text style={ui.kicker}>Also ask me about</Text>
      {settings
        ? (Object.keys(settings.auto_sources) as AutoSource[]).map((key) => (
            <View key={key} style={[ui.row, { justifyContent: "space-between" }]}>
              <Text style={[ui.body, { flex: 1 }]}>{settings.labels[key] ?? SOURCE_LABELS[key]}</Text>
              <Switch
                value={settings.auto_sources[key]}
                disabled={saving !== ""}
                onValueChange={(value) => void toggle(key, value)}
                trackColor={{ true: colors.accent, false: colors.border }}
                accessibilityLabel={settings.labels[key] ?? SOURCE_LABELS[key]}
              />
            </View>
          ))
        : null}
      <Text style={ui.muted}>Off by default. When on, new items from that source wait here before posting.</Text>
      {error ? <Text style={ui.error}>{error}</Text> : null}
    </View>
  );
}

export default function ApprovalsScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const launch = useLaunchStatus(token);
  const publishingOpen = launch.status ? launch.status.features.publishing : launch.loading ? null : false;

  const [status, setStatus] = useState<StatusFilter>("pending");
  const [source, setSource] = useState<ApprovalSource | "">("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ApprovalList | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listApprovals({ status, source, offset, limit: PAGE_SIZE }, { token })
      .then((next) => {
        if (!active) return;
        setData(next);
        setError("");
      })
      .catch((err: unknown) => {
        if (active) setError(readableApiError(err, "Couldn't load your approvals. Try again."));
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        setRefreshing(false);
      });
    return () => {
      active = false;
    };
  }, [token, status, source, offset, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const onRefresh = useCallback(() => {
    setRefreshing(true);
    reload();
    launch.refresh();
  }, [reload, launch]);

  const onDecided = useCallback(
    (next: ApprovalItem) => setData((prev) => (prev ? applyDecision(prev, next, status) : prev)),
    [status],
  );

  const changeFilter = (nextStatus: StatusFilter, nextSource: ApprovalSource | "") => {
    setStatus(nextStatus);
    setSource(nextSource);
    setOffset(0);
  };

  const chip = (label: string, selected: boolean, onPress: () => void, key: string) => (
    <Pressable
      key={key}
      onPress={onPress}
      style={[ui.chip, selected && ui.chipOn]}
      accessibilityRole="button"
      accessibilityState={{ selected }}
    >
      <Text style={[ui.chipText, selected && ui.chipTextOn]}>{label}</Text>
    </Pressable>
  );

  return (
    <ScrollView
      style={ui.screen}
      contentContainerStyle={ui.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
    >
      <Stack.Screen options={{ title: "Approvals" }} />
      <Text style={ui.intro}>
        Reply drafts, held posts, budget changes and publish requests wait here before anything is sent or spent.
      </Text>
      <LaunchStatusBanner status={launch.status} gate="publishing" />

      <View style={ui.row}>
        {chip(`Pending${data ? ` (${data.pending_count})` : ""}`, status === "pending", () => changeFilter("pending", source), "pending")}
        {chip("History", status === "all", () => changeFilter("all", source), "all")}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={ui.row}>
        {chip("All sources", source === "", () => changeFilter(status, ""), "src-all")}
        {APPROVAL_SOURCES.map((key) => {
          const count = data?.pending_by_source[key];
          return chip(
            `${SOURCE_LABELS[key]}${count ? ` (${count})` : ""}`,
            source === key,
            () => changeFilter(status, key),
            `src-${key}`,
          );
        })}
      </ScrollView>

      <AutoSources token={token} onChanged={reload} />

      {data?.unavailable_sources.length ? (
        <Text style={ui.muted}>
          Could not refresh: {data.unavailable_sources.join(", ")}. Showing what was already queued.
        </Text>
      ) : null}
      {error ? (
        <View style={ui.card}>
          <Text style={ui.error}>{error}</Text>
          <ActionButton label="Try again" variant="ghost" onPress={reload} />
        </View>
      ) : null}

      {loading && !data ? (
        <View style={ui.center}>
          <ActivityIndicator color={colors.accent} />
          <Text style={ui.muted}>Loading approvals</Text>
        </View>
      ) : data && data.items.length === 0 ? (
        <View style={ui.empty}>
          <Text style={ui.muted}>
            {status === "pending"
              ? "Nothing is waiting on you. Reply drafts, held posts and budget changes show up here before anything is sent or spent."
              : "No decisions recorded yet."}
          </Text>
        </View>
      ) : data ? (
        data.items.map((item) => (
          <ApprovalCard
            key={item.id}
            item={item}
            token={token}
            publishingOpen={publishingOpen}
            onDecided={onDecided}
          />
        ))
      ) : null}

      {data && data.total > PAGE_SIZE ? (
        <View style={[ui.row, { justifyContent: "space-between" }]}>
          <ActionButton
            label="Previous"
            variant="ghost"
            disabled={offset === 0 || loading}
            onPress={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          />
          <Text style={ui.muted}>
            {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
          </Text>
          <ActionButton
            label="Next"
            variant="ghost"
            disabled={offset + PAGE_SIZE >= data.total || loading}
            onPress={() => setOffset(offset + PAGE_SIZE)}
          />
        </View>
      ) : null}
    </ScrollView>
  );
}
