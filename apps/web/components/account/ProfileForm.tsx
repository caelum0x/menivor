"use client";

import * as React from "react";
import { CheckCircle2, Loader2, Save } from "lucide-react";
import type { CreatorProfile, ProfileUpdateRequest } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export interface ProfileFormProps {
  profile: CreatorProfile | null;
  saving: boolean;
  saveError: string;
  onSave: (body: ProfileUpdateRequest) => Promise<CreatorProfile | null>;
}

const HANDLE_PATTERN = /^[a-z0-9]+(?:[-_][a-z0-9]+)*$/;

/** Client-side mirror of the server's handle shape rule (3-64 chars). */
function validateHandle(handle: string): string | null {
  if (handle.length === 0) return null; // optional
  if (handle.length < 3 || handle.length > 64) {
    return "Handle must be 3-64 characters.";
  }
  if (!HANDLE_PATTERN.test(handle)) {
    return "Use lowercase letters, numbers, and single - or _ separators.";
  }
  return null;
}

/**
 * Edit form for the caller's public creator identity (handle / display name /
 * bio). Validates the handle shape client-side before submitting, shows a
 * saved confirmation, and surfaces server errors (e.g. a taken handle). Only
 * fields the user actually changes are sent so a blank input never clobbers a
 * stored value.
 */
export function ProfileForm({
  profile,
  saving,
  saveError,
  onSave,
}: Readonly<ProfileFormProps>) {
  const [handle, setHandle] = React.useState(profile?.handle ?? "");
  const [displayName, setDisplayName] = React.useState(
    profile?.display_name ?? "",
  );
  const [bio, setBio] = React.useState(profile?.bio ?? "");
  const [saved, setSaved] = React.useState(false);

  // Re-seed the form when the underlying profile is (re)loaded.
  React.useEffect(() => {
    setHandle(profile?.handle ?? "");
    setDisplayName(profile?.display_name ?? "");
    setBio(profile?.bio ?? "");
  }, [profile]);

  const trimmedHandle = handle.trim().toLowerCase();
  const handleError = validateHandle(trimmedHandle);

  const dirty =
    trimmedHandle !== (profile?.handle ?? "") ||
    displayName.trim() !== (profile?.display_name ?? "") ||
    bio.trim() !== (profile?.bio ?? "");

  const canSubmit = dirty && !handleError && !saving;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) return;
    setSaved(false);
    const body: ProfileUpdateRequest = {
      display_name: displayName,
      bio,
    };
    if (trimmedHandle) body.handle = trimmedHandle;
    const result = await onSave(body);
    if (result) setSaved(true);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="profile-handle">Handle</Label>
        <Input
          id="profile-handle"
          value={handle}
          onChange={(e) => {
            setHandle(e.target.value);
            setSaved(false);
          }}
          placeholder="jane-makes-reels"
          maxLength={64}
          autoComplete="off"
          aria-invalid={handleError ? true : undefined}
          aria-describedby="profile-handle-help"
        />
        <p id="profile-handle-help" className="text-xs text-muted-foreground">
          {handleError ? (
            <span className="text-destructive">{handleError}</span>
          ) : (
            "Your public URL slug. Lowercase letters, numbers, - and _."
          )}
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="profile-display-name">Display name</Label>
        <Input
          id="profile-display-name"
          value={displayName}
          onChange={(e) => {
            setDisplayName(e.target.value);
            setSaved(false);
          }}
          placeholder="Jane Doe"
          maxLength={200}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="profile-bio">Bio</Label>
        <Textarea
          id="profile-bio"
          value={bio}
          onChange={(e) => {
            setBio(e.target.value);
            setSaved(false);
          }}
          placeholder="A short tagline for your creator profile."
          maxLength={2000}
          rows={4}
        />
        <p className="text-right text-xs text-muted-foreground">
          {bio.length}/2000
        </p>
      </div>

      {saveError && (
        <p className="text-sm text-destructive" role="alert">
          {saveError}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!canSubmit}>
          {saving ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <Save className="size-4" aria-hidden />
          )}
          {saving ? "Saving…" : "Save profile"}
        </Button>
        {saved && !dirty && (
          <span className="inline-flex items-center gap-1.5 text-sm text-success">
            <CheckCircle2 className="size-4" aria-hidden /> Saved
          </span>
        )}
      </div>
    </form>
  );
}
