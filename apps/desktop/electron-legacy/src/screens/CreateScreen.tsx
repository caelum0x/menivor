import { useCallback, useEffect, useRef, useState } from "react";

import { createJob, presignAndUpload, useJob } from "../lib/api";
import type { Job } from "../lib/types";
import { ConfigureStep } from "./ConfigureStep";
import { RecordStep } from "./RecordStep";
import type { CreateFormState } from "./reelParams";
import { DEFAULT_CREATE_FORM, buildJobBody } from "./reelParams";

interface CreateScreenProps {
  /** Navigate to the Library screen (from the result step). */
  onViewLibrary: () => void;
}

type Step = "record" | "configure";

/**
 * Create screen — the record → generate → result flow in one place:
 *  1. RECORD: capture a screen/window ({@link RecordStep}).
 *  2. CONFIGURE: review the clip and set the reel params + editing-polish toggles
 *     ({@link ConfigureStep}).
 *  3. GENERATE: upload the recording (presign → R2 PUT), create a job, and poll it
 *     to a terminal state via {@link useJob}.
 *  4. RESULT: preview + download the finished reel, or surface the failure.
 *
 * The desktop client only drives the backend pipeline; the render itself
 * (script → TTS → avatar → compose) happens server-side.
 */
export function CreateScreen({ onViewLibrary }: CreateScreenProps) {
  const [step, setStep] = useState<Step>("record");
  const [form, setForm] = useState<CreateFormState>(DEFAULT_CREATE_FORM);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const blobRef = useRef<Blob | null>(null);
  const previewUrlRef = useRef<string | null>(null);

  const jobState = useJob(jobId);

  // Keep a ref in sync so cleanup can revoke the latest object URL exactly once.
  useEffect(() => {
    previewUrlRef.current = previewUrl;
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    };
  }, []);

  const handleRecorded = useCallback((blob: Blob) => {
    blobRef.current = blob;
    const url = URL.createObjectURL(blob);
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return url;
    });
    setSubmitError(null);
    setJobId(null);
    setStep("configure");
  }, []);

  const reRecord = useCallback(() => {
    blobRef.current = null;
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setJobId(null);
    setSubmitError(null);
    setStep("record");
  }, []);

  const createAnother = useCallback(() => {
    blobRef.current = null;
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setJobId(null);
    setSubmitError(null);
    setForm(DEFAULT_CREATE_FORM);
    setStep("record");
  }, []);

  const generate = useCallback(async () => {
    const blob = blobRef.current;
    if (!blob) {
      setSubmitError("Record a screen capture before generating.");
      return;
    }
    if (!form.video_subject.trim()) {
      setSubmitError("Describe what the reel is about first.");
      return;
    }

    setSubmitError(null);
    setJobId(null);
    setUploading(true);
    try {
      const filename = `screen-${Date.now()}.webm`;
      const { key } = await presignAndUpload(blob, filename);
      const created = await createJob(buildJobBody(form, key));
      setJobId(created.job_id);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Failed to start the job.",
      );
    } finally {
      setUploading(false);
    }
  }, [form]);

  const job = jobState.job;
  const generating = uploading || (jobId !== null && jobState.polling);
  const done =
    jobId !== null &&
    jobState.isTerminal &&
    !jobState.isFailed &&
    Boolean(job?.result_url);
  const failed = jobId !== null && jobState.isFailed;

  if (step === "record") {
    return <RecordStep onRecorded={handleRecorded} />;
  }

  // step === "configure" — but the panel swaps to status/result once generating.
  if (!previewUrl) {
    // Defensive: no recording to configure — send the user back to capture.
    return <RecordStep onRecorded={handleRecorded} />;
  }

  if (done && job) {
    return (
      <ResultPanel
        job={job}
        onCreateAnother={createAnother}
        onViewLibrary={onViewLibrary}
      />
    );
  }

  if (generating) {
    return <StatusPanel job={job} uploading={uploading} />;
  }

  const configureError =
    submitError ?? (failed ? (job?.error ?? "The job failed.") : null);

  return (
    <ConfigureStep
      previewUrl={previewUrl}
      form={form}
      onChange={setForm}
      onReRecord={reRecord}
      onGenerate={() => void generate()}
      submitting={generating}
      error={configureError}
    />
  );
}

// ---------------------------------------------------------------------------
// Live status while the backend renders
// ---------------------------------------------------------------------------

function StatusPanel({
  job,
  uploading,
}: {
  job: Job | null;
  uploading: boolean;
}) {
  const pct = Math.round((job?.progress ?? 0) * 100);
  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Generating your reel</h1>
        <p className="view-sub">
          This can take a few minutes — the render runs on the backend.
        </p>
      </div>

      <div className="card panel">
        <div className="job-status">
          <span className="job-id">
            {uploading
              ? "Uploading recording…"
              : job
                ? `Job ${job.job_id}`
                : "Starting…"}
          </span>
          <span className="muted">{uploading ? "" : `${pct}%`}</span>
        </div>
        <div className="progress">
          <div
            className={uploading ? "progress-bar progress-bar--indeterminate" : "progress-bar"}
            style={uploading ? undefined : { width: `${pct}%` }}
          />
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Finished reel
// ---------------------------------------------------------------------------

function ResultPanel({
  job,
  onCreateAnother,
  onViewLibrary,
}: {
  job: Job;
  onCreateAnother: () => void;
  onViewLibrary: () => void;
}) {
  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Your reel is ready</h1>
        <p className="view-sub">Preview it, download it, or make another.</p>
      </div>

      <div className="card panel">
        {job.result_url && (
          <video className="preview" src={job.result_url} controls />
        )}
        <div className="panel-actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={onCreateAnother}
          >
            Create another
          </button>
          {job.result_url && (
            <a
              className="btn btn--accent"
              href={job.result_url}
              target="_blank"
              rel="noreferrer"
            >
              Open / download
            </a>
          )}
          <button type="button" className="btn btn--primary" onClick={onViewLibrary}>
            Go to library
          </button>
        </div>
      </div>
    </section>
  );
}
