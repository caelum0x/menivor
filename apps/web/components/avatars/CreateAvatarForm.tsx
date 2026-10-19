"use client";

import * as React from "react";
import { AlertCircle, Loader2, Sparkles } from "lucide-react";
import type { Avatar } from "@/lib/types";
import { ApiError, createAvatarFromPhoto, presignAndUpload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { useApiToken } from "@/lib/use-api-token";
import { customAvatarToAvatar } from "@/components/avatars/avatar-utils";
import {
  SelfieInput,
  type SelfiePhoto,
} from "@/components/avatars/SelfieInput";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

interface CreateAvatarFormProps {
  /** Called with the newly created avatar so the parent can prepend it. */
  onCreated: (avatar: Avatar) => void;
}

const NAME_MAX = 200;

type Phase =
  | { status: "idle" }
  | { status: "uploading"; progress: number }
  | { status: "creating" }
  | { status: "error"; message: string };

/**
 * CUSTOM AVATAR FROM A PHOTO creation form: name the avatar and pick a selfie.
 * On submit it presigns + uploads the image, then calls POST /avatars to mint a
 * HeyGen talking-photo avatar and reports the new avatar up. All fields reset
 * after a successful create. State is immutable — inputs are controlled.
 */
export function CreateAvatarForm({ onCreated }: CreateAvatarFormProps) {
  const getApiToken = useApiToken();

  const [name, setName] = React.useState("");
  const [photo, setPhoto] = React.useState<SelfiePhoto | null>(null);
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const busy = phase.status === "uploading" || phase.status === "creating";
  const canSubmit = !busy && name.trim().length > 0 && photo !== null;

  const reset = React.useCallback(() => {
    setName("");
    setPhoto(null);
    setPhase({ status: "idle" });
  }, []);

  const handleSubmit = React.useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!photo || name.trim().length === 0) return;

      setPhase({ status: "uploading", progress: 0 });
      try {
        const token = await getApiToken();
        const { key } = await presignAndUpload(photo.file, {
          token,
          onProgress: (fraction) =>
            setPhase({
              status: "uploading",
              progress: Math.round(fraction * 100),
            }),
        });

        setPhase({ status: "creating" });
        const created = await createAvatarFromPhoto(
          { image_key: key, display_name: name.trim() },
          { token },
        );

        onCreated(customAvatarToAvatar(created));
        reset();
      } catch (err) {
        const message =
          friendlyErrorMessage(err, "Could not create your avatar. Please try again.");
        setPhase({ status: "error", message });
      }
    },
    [getApiToken, name, onCreated, photo, reset],
  );

  return (
    <Card>
      <CardContent className="p-6">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="avatar-name">Avatar name</Label>
            <Input
              id="avatar-name"
              value={name}
              maxLength={NAME_MAX}
              placeholder="e.g. My Avatar"
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              required
            />
          </div>

          <div className="space-y-2">
            <Label>Selfie photo</Label>
            <SelfieInput value={photo} onChange={setPhoto} disabled={busy} />
            <p className="text-xs text-muted-foreground">
              Only upload a photo of yourself, or one you are authorized to use.
            </p>
          </div>

          {phase.status === "uploading" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Uploading photo… {phase.progress}%
              </p>
              <Progress value={phase.progress} />
            </div>
          )}

          {phase.status === "error" && (
            <p
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              {phase.message}
            </p>
          )}

          <Button type="submit" disabled={!canSubmit} className="w-full">
            {busy ? (
              <>
                <Loader2 className="animate-spin" />
                {phase.status === "creating"
                  ? "Creating avatar…"
                  : "Uploading…"}
              </>
            ) : (
              <>
                <Sparkles /> Create avatar from photo
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
