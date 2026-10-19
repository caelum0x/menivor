/** Per-project loop setting: mode, auto-publish platforms, spend cap and window. */

import { useEffect, useState } from "react";
import { Text, View } from "react-native";

import { Button, Chip, NumberField, Segmented, SelectField, ToggleField } from "@/components/ui";
import { colors, radius, spacing } from "@/src/shared/theme";

import { parseLoopSettings, platformLabel } from "../format";
import {
  LOOP_PLATFORMS,
  type LoopConfigInput,
  type LoopDetail,
  type LoopMode,
  type LoopPlatform,
} from "../types";
import { sectionStyles as s } from "./styles";

const MODE_HINTS: Record<LoopMode, string> = {
  off: "Nothing is posted or remade.",
  manual: "Posts and measures automatically; you tap Remake winner.",
  auto: "Remakes a clear winner automatically, within your spend cap.",
};

const WINDOW_OPTIONS = ["24", "48", "72", "96", "168"] as const;

export interface LoopSettingsCardProps {
  readonly detail: LoopDetail;
  readonly saving: boolean;
  readonly onSave: (input: LoopConfigInput) => void;
  readonly onManageConnections: () => void;
}

function initialCap(detail: LoopDetail): string {
  return String(detail.configured ? detail.spend_cap_credits : detail.remake_cost_credits * 2);
}

export function LoopSettingsCard({ detail, saving, onSave, onManageConnections }: LoopSettingsCardProps) {
  const [mode, setMode] = useState<LoopMode>(detail.configured ? detail.mode : "manual");
  const [platforms, setPlatforms] = useState<LoopPlatform[]>(detail.platforms);
  const [cap, setCap] = useState(initialCap(detail));
  const [windowHours, setWindowHours] = useState(String(detail.check_after_hours ?? 48));
  const [minViews, setMinViews] = useState(String(detail.min_views ?? 100));

  useEffect(() => {
    setMode(detail.configured ? detail.mode : "manual");
    setPlatforms(detail.platforms);
    setCap(initialCap(detail));
    setWindowHours(String(detail.check_after_hours ?? 48));
    setMinViews(String(detail.min_views ?? 100));
  }, [detail]);

  const parsed = parseLoopSettings({ cap, minViews });
  const valid = parsed.cap !== null && parsed.minViews !== null;
  const spentPct =
    detail.spend_cap_credits > 0 ? Math.min(100, (detail.spent_credits / detail.spend_cap_credits) * 100) : 0;

  const togglePlatform = (platform: LoopPlatform, on: boolean) =>
    setPlatforms((current) =>
      on ? (current.includes(platform) ? current : [...current, platform]) : current.filter((p) => p !== platform),
    );

  const submit = () => {
    if (parsed.cap === null || parsed.minViews === null) return;
    onSave({
      mode,
      platforms: mode === "off" ? [] : platforms,
      spend_cap_credits: parsed.cap,
      check_after_hours: Number(windowHours),
      min_views: parsed.minViews,
    });
  };

  return (
    <View style={s.card}>
      <Text style={s.title}>Loop settings</Text>
      <Segmented<LoopMode>
        items={[
          { id: "off", label: "Off" },
          { id: "manual", label: "Manual" },
          { id: "auto", label: "Auto" },
        ]}
        value={mode}
        onChange={setMode}
        disabled={saving}
      />
      <Text style={s.micro}>{MODE_HINTS[mode]}</Text>

      {mode !== "off" ? (
        <View style={{ gap: spacing.xs }}>
          <Text style={s.label}>Auto-publish to</Text>
          {!detail.publishing_enabled ? (
            <Text style={[s.micro, { backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: spacing.sm }]}>
              Direct publishing is not enabled yet. Leave these off, post the variants yourself and
              log their results on each reel; the loop ranks them from those numbers.
            </Text>
          ) : null}
          {LOOP_PLATFORMS.map((platform) => (
            <ToggleField
              key={platform}
              label={platformLabel(platform)}
              value={platforms.includes(platform)}
              onValueChange={(on) => togglePlatform(platform, on)}
              disabled={!detail.publishing_enabled || saving}
            />
          ))}
          <Text style={s.micro}>
            Uses your connected accounts. Variants are posted at spaced times so they do not
            compete with each other. Reading results needs analytics permission on each account.
          </Text>
          <Chip label="Manage connections" onPress={onManageConnections} />
        </View>
      ) : null}

      <NumberField
        label="Spend cap (credits)"
        value={cap}
        onChangeText={setCap}
        error={parsed.cap === null ? "Enter a whole number from 0 to 1000." : undefined}
      />
      <SelectField
        label="Read results after"
        value={windowHours}
        onChange={setWindowHours}
        options={WINDOW_OPTIONS.map((h) => ({ value: h, label: h === "168" ? "7 days" : `${h} hours` }))}
        disabled={saving}
      />
      <NumberField
        label="Min views per variant"
        value={minViews}
        onChangeText={setMinViews}
        error={parsed.minViews === null ? "Enter a whole number from 0 to 100000." : undefined}
      />

      <View style={{ gap: spacing.xs }}>
        <View style={[s.row, { justifyContent: "space-between" }]}>
          <Text style={s.micro}>
            {detail.spent_credits} of {detail.spend_cap_credits} credits spent on remakes
          </Text>
          <Text style={s.micro}>{detail.remake_cost_credits} credits per remake</Text>
        </View>
        <View
          style={{ height: 4, borderRadius: radius.pill, backgroundColor: colors.border, overflow: "hidden" }}
          accessibilityRole="progressbar"
          accessibilityLabel="Remake spend against cap"
          accessibilityValue={{ min: 0, max: 100, now: Math.round(spentPct) }}
        >
          <View style={{ height: 4, width: `${spentPct}%`, backgroundColor: colors.accent }} />
        </View>
      </View>

      <Button
        label={saving ? "Saving" : detail.configured ? "Save settings" : "Start loop"}
        loading={saving}
        disabled={!valid}
        onPress={submit}
      />
    </View>
  );
}
