"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { presignAndUpload } from "@/lib/api";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";
import {
  MAX_PHOTOS,
  MIN_PHOTOS,
  consentPhrase,
  createRealFace,
  listPassports,
  type MyCharacter,
  type Passport,
} from "./api";

export interface RealFaceFormProps {
  readonly onCreated: (character: MyCharacter) => void;
  /** Test seam: a recorder that returns the spoken consent as a file. */
  readonly record?: () => Promise<File>;
}

async function recordFromMicrophone(seconds = 8): Promise<File> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => chunks.push(event.data);
  const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
  recorder.start();
  await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
  recorder.stop();
  await done;
  stream.getTracks().forEach((track) => track.stop());
  const type = recorder.mimeType || "audio/webm";
  return new File(chunks, `consent.${type.includes("mp4") ? "m4a" : "webm"}`, { type });
}

/** Your own face only: 10-20 of your photos, the consent phrase in your voice, and your locked identity. */
export function RealFaceForm({ onCreated, record = recordFromMicrophone }: RealFaceFormProps) {
  const getApiToken = useApiToken();
  const [photos, setPhotos] = React.useState<File[]>([]);
  const [phrase, setPhrase] = React.useState<{ token: string; phrase: string } | null>(null);
  const [recording, setRecording] = React.useState<File | null>(null);
  const [passports, setPassports] = React.useState<readonly Passport[] | null>(null);
  const [passport, setPassport] = React.useState("");
  const [declared, setDeclared] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    (async () => {
      try {
        const token = await getApiToken();
        const list = await listPassports({ token });
        if (live) setPassports(list);
      } catch {
        if (live) setPassports([]);
      }
    })();
    return () => {
      live = false;
    };
  }, [getApiToken]);

  const countOk = photos.length >= MIN_PHOTOS && photos.length <= MAX_PHOTOS;
  const ready = countOk && phrase && recording && passport && declared;

  async function onPhrase() {
    setError("");
    try {
      const token = await getApiToken();
      const next = await consentPhrase({ token });
      setPhrase(next);
      setRecording(null);
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not get a phrase."));
    }
  }

  async function onRecord() {
    setError("");
    try {
      setRecording(await record());
    } catch {
      setError("Allow the microphone to record the phrase.");
    }
  }

  async function onCreate() {
    if (!ready || !phrase || !recording) return;
    setBusy(true);
    setError("");
    try {
      const token = await getApiToken();
      const keys: string[] = [];
      for (const photo of photos) keys.push((await presignAndUpload(photo, { token })).key);
      const recordingKey = (await presignAndUpload(recording, { token })).key;
      const [passportId, version] = passport.split("@");
      const character = await createRealFace(
        {
          name: "Me",
          reference_keys: keys,
          consent_token: phrase.token,
          recording_key: recordingKey,
          passport_id: passportId ?? "",
          passport_version: Number(version ?? 0),
          self_declared: declared,
        },
        { token },
      );
      onCreated(character);
    } catch (err) {
      setError(friendlyErrorMessage(err, "We could not create this character."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Only you, only with your consent. Face swaps and other people&apos;s faces are not possible here.
      </p>
      <label className="block text-sm">
        <span className="font-medium">{MIN_PHOTOS} to {MAX_PHOTOS} photos of yourself</span>
        <input
          type="file"
          accept="image/*"
          multiple
          className="mt-1 block w-full text-sm"
          aria-label="Photos of yourself"
          onChange={(e) => setPhotos(Array.from(e.target.files ?? []))}
        />
        <span className="text-xs text-muted-foreground" data-testid="photo-count">{photos.length} selected</span>
      </label>
      <div className="space-y-2">
        <Button type="button" variant="outline" onClick={onPhrase}>Get my consent phrase</Button>
        {phrase ? (
          <div className="space-y-2">
            <p className="rounded-xl border border-border p-3 text-sm" data-testid="consent-phrase">
              Read this aloud: <strong>{phrase.phrase}</strong>
            </p>
            <Button type="button" variant="outline" onClick={onRecord}>
              {recording ? "Record again" : "Record the phrase"}
            </Button>
            {recording ? <span className="ml-2 text-sm">Recorded</span> : null}
          </div>
        ) : null}
      </div>
      {passports === null ? null : passports.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="no-identity-lock">
          Your identity is not locked yet, so a character of yourself cannot be made.
        </p>
      ) : (
        <label className="block text-sm">
          <span className="font-medium">Your locked identity</span>
          <select
            className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2"
            value={passport}
            onChange={(e) => setPassport(e.target.value)}
          >
            <option value="">Pick one</option>
            {passports.map((p) => (
              <option key={`${p.passport_id}@${p.version}`} value={`${p.passport_id}@${p.version}`}>
                {p.kind} version {p.version}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
        These photos and this voice are mine.
      </label>
      <Button type="button" className="w-full" disabled={!ready || busy} onClick={onCreate}>
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null} Create my character
      </Button>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
