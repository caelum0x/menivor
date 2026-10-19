"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE } from "@/src/shared/api/base";

/** Mirrors the response of POST /legal/content-credentials (M7.1). */
export type CredentialsResult = {
  present: boolean;
  valid: boolean;
  trusted: boolean;
  ai_generated: boolean;
  made_with_menivor: boolean;
  content_id: string | null;
  signer?: string | null;
  verdict: string;
};

type Phase =
  | { status: "idle" }
  | { status: "checking"; name: string }
  | { status: "done"; name: string; result: CredentialsResult }
  | { status: "error"; message: string };

const MAX_MB = 200;
const GENERIC_ERROR = "We could not check this file. Try again.";

function errorMessage(status: number, message: unknown): string {
  if (status === 429) return "Too many checks from here. Try again in an hour.";
  if (status === 413) return `The video is larger than ${MAX_MB} MB.`;
  const text = String(message || "").replace(/^[^:]*:\s*/, "");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) + "." : GENERIC_ERROR;
}

export function CredentialsCheck() {
  const [phase, setPhase] = React.useState<Phase>({ status: "idle" });

  const check = async (file: File) => {
    if (file.size > MAX_MB * 1024 * 1024) {
      setPhase({ status: "error", message: `The video is larger than ${MAX_MB} MB.` });
      return;
    }
    setPhase({ status: "checking", name: file.name });
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${API_BASE}/legal/content-credentials`, { method: "POST", body });
      const payload = (await response.json().catch(() => ({}))) as {
        data?: CredentialsResult;
        message?: string;
      };
      if (!response.ok || !payload.data) {
        setPhase({ status: "error", message: errorMessage(response.status, payload.message) });
        return;
      }
      setPhase({ status: "done", name: file.name, result: payload.data });
    } catch {
      setPhase({ status: "error", message: GENERIC_ERROR });
    }
  };

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="credentials-file">MP4 video</Label>
        <Input
          id="credentials-file"
          type="file"
          accept="video/mp4,video/quicktime"
          disabled={phase.status === "checking"}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void check(file);
          }}
        />
      </div>
      {phase.status === "checking" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Checking {phase.name}...
        </p>
      ) : null}
      {phase.status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          {phase.message}
        </p>
      ) : null}
      {phase.status === "done" ? <ResultCard name={phase.name} result={phase.result} /> : null}
    </div>
  );
}

function ResultCard({ name, result }: { name: string; result: CredentialsResult }) {
  const rows: Array<[string, string]> = result.present
    ? [
        ["Signature", result.valid ? "Valid" : "Does not match the file"],
        ["Signer", result.signer || "Unknown"],
        ["Signer on the C2PA trust list", result.trusted ? "Yes" : "No"],
        ["Marked as AI-generated", result.ai_generated ? "Yes" : "No"],
      ]
    : [];
  if (result.content_id) rows.push(["Content id", result.content_id]);
  return (
    <div role="status" className="rounded-lg border border-border p-6">
      <p className="text-sm text-muted-foreground">{name}</p>
      <p className="mt-1 font-medium">{result.verdict}</p>
      {rows.length ? (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {rows.map(([label, value]) => (
            <React.Fragment key={label}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="font-mono break-all">{value}</dd>
            </React.Fragment>
          ))}
        </dl>
      ) : null}
    </div>
  );
}
