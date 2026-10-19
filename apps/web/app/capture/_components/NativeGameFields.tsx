"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { NativePlatform, NativeStatus, NativeTargetInput } from "./api";

export interface NativeDraft {
  platform: NativePlatform;
  device: string;
  appId: string;
  deepLink: string;
  title: string;
  settle: number;
}

export const EMPTY_NATIVE: NativeDraft = {
  platform: "ios",
  device: "",
  appId: "",
  deepLink: "",
  title: "",
  settle: 4,
};

/** Validate the draft; returns an error message or the request body. */
export function nativeTarget(draft: NativeDraft, status: NativeStatus | null): string | NativeTargetInput {
  if (status && !status.enabled) return "Mobile game capture is not enabled on this server.";
  const device = draft.device.trim();
  if (draft.platform === "android" && !device) return "Enter the emulator's adb serial, for example emulator-5554.";
  const appId = draft.appId.trim();
  if (status?.app_ids.length && !appId) return "Pick the game to record.";
  const deepLink = draft.deepLink.trim();
  if (deepLink && !/^[a-z][a-z0-9+.-]*:\/\/\S+$/i.test(deepLink)) return "The deep link should look like mygame://play";
  return {
    platform: draft.platform,
    ...(device ? { device } : {}),
    ...(appId ? { app_id: appId } : {}),
    ...(deepLink ? { deep_link: deepLink } : {}),
    ...(draft.title.trim() ? { title: draft.title.trim() } : {}),
    settle_s: draft.settle,
  };
}

/** Simulator / emulator target for a native game capture. */
export function NativeGameFields({
  draft,
  onChange,
  status,
  disabled,
}: {
  draft: NativeDraft;
  onChange: (next: NativeDraft) => void;
  status: NativeStatus | null;
  disabled: boolean;
}) {
  const set = <K extends keyof NativeDraft>(key: K, value: NativeDraft[K]) => onChange({ ...draft, [key]: value });
  const allowlist = status?.app_ids ?? [];

  return (
    <div className="space-y-4">
      {status && !status.enabled ? (
        <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
          Mobile game capture is off on this server. The operator turns it on (capture_native_game) on a machine with
          an iOS Simulator or Android emulator running the game.
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="native-platform">Platform</Label>
          <Select
            id="native-platform"
            value={draft.platform}
            onChange={(e) => set("platform", e.target.value as NativePlatform)}
            disabled={disabled}
          >
            <option value="ios">iOS Simulator</option>
            <option value="android">Android emulator</option>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="native-device">{draft.platform === "ios" ? "Simulator (optional)" : "Emulator serial"}</Label>
          <Input
            id="native-device"
            placeholder={draft.platform === "ios" ? "booted, or a simulator UDID" : "emulator-5554"}
            value={draft.device}
            onChange={(e) => set("device", e.target.value)}
            disabled={disabled}
            autoComplete="off"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="native-app">{allowlist.length ? "Game" : "Bundle id or package (optional)"}</Label>
          {allowlist.length ? (
            <Select id="native-app" value={draft.appId} onChange={(e) => set("appId", e.target.value)} disabled={disabled}>
              <option value="">Choose a game</option>
              {allowlist.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </Select>
          ) : (
            <Input
              id="native-app"
              placeholder="com.example.game"
              value={draft.appId}
              onChange={(e) => set("appId", e.target.value)}
              disabled={disabled}
              autoComplete="off"
            />
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="native-title">Game name</Label>
          <Input
            id="native-title"
            placeholder="Used in the drafted ad script"
            value={draft.title}
            maxLength={80}
            onChange={(e) => set("title", e.target.value)}
            disabled={disabled}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="native-link">Deep link (optional)</Label>
        <Input
          id="native-link"
          placeholder="mygame://play?menivor_demo=1&seed=7"
          value={draft.deepLink}
          onChange={(e) => set("deepLink", e.target.value)}
          disabled={disabled}
          autoComplete="off"
        />
        <p className="text-xs text-muted-foreground">
          A link into the game&apos;s demo mode gives a self-playing run. Without a link, the game is launched by its
          id. With neither, whatever is on screen is recorded.
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor="native-settle">Wait after launch: {draft.settle}s</Label>
        <input
          id="native-settle"
          type="range"
          min={0}
          max={30}
          step={1}
          value={draft.settle}
          onChange={(e) => set("settle", Number(e.target.value))}
          className="w-full max-w-md accent-primary"
          disabled={disabled}
        />
      </div>
    </div>
  );
}
