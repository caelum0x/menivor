/**
 * PRESETS section of the Me tab. Lists the caller's saved presets (GET
 * /me/presets), creates new ones (POST /me/presets) and deletes them (DELETE
 * /me/presets/{id}) with optimistic list updates and a re-sync on failure.
 */

import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import {
  createPreset,
  deletePreset,
  listMyWorkspaces,
  listPresets,
} from "@/lib/api";
import type {
  Preset,
  PresetCreateRequest,
  Workspace,
} from "@/lib/types";

import { PresetCard } from "./PresetCard";
import { PresetCreateForm } from "./PresetCreateForm";
import { Section, SectionState } from "./Section";
import { colors } from "./theme";
import { useResource } from "./use-resource";

interface PresetsSectionProps {
  token: string | undefined;
}

export function PresetsSection({ token }: PresetsSectionProps) {
  const fetcher = useCallback(() => listPresets({ token }), [token]);
  const { status, data, error, reload, setData } = useResource<Preset[]>(fetcher);

  // Workspaces the caller can share a brand kit with. A failure here degrades
  // gracefully — the "Share to team" picker simply hides and presets stay
  // personal (never blocks the presets list or personal preset creation).
  const workspacesFetcher = useCallback(
    () => listMyWorkspaces({ token }).catch(() => [] as Workspace[]),
    [token],
  );
  const { data: workspacesData } = useResource<Workspace[]>(workspacesFetcher);
  const workspaces = workspacesData ?? [];

  const presets = data ?? [];

  const onCreate = useCallback(
    async (body: PresetCreateRequest) => {
      const created = await createPreset(body, { token });
      // Prepend the new preset (backend returns newest-first).
      setData((prev) => [created, ...(prev ?? [])]);
    },
    [token, setData],
  );

  const onDelete = useCallback(
    async (id: string) => {
      const previous = data;
      // Optimistically drop the row, then confirm with the backend.
      setData((prev) => (prev ?? []).filter((p) => p.id !== id));
      try {
        await deletePreset(id, { token });
      } catch (err) {
        // Roll back to the last known-good list on failure.
        setData(() => previous);
        throw err;
      }
    },
    [token, data, setData],
  );

  return (
    <Section title="PRESETS">
      <View style={styles.stack}>
        <PresetCreateForm onCreate={onCreate} workspaces={workspaces} />
        <SectionState status={status} error={error} onRetry={reload}>
          {presets.length === 0 ? (
            <Text style={styles.empty}>
              No presets yet. Save a favourite avatar / voice / layout combo to
              reuse on every new reel.
            </Text>
          ) : (
            <View style={styles.list}>
              {presets.map((preset) => (
                <PresetCard key={preset.id} preset={preset} onDelete={onDelete} />
              ))}
            </View>
          )}
        </SectionState>
      </View>
    </Section>
  );
}

const styles = StyleSheet.create({
  stack: { gap: 12 },
  list: { gap: 10 },
  empty: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 18,
    paddingVertical: 8,
  },
});
