import { useCallback, useEffect, useRef, useState } from "react";

import { createJob, pollJob } from "../lib/api";
import type { Job, JobCreateRequest, Language, Layout, ReelForgeParams } from "../lib/types";
import { isFailedState, JobState } from "../lib/types";

interface GenerateViewProps {
  recordingKey: string | null;
  onGenerated: () => void;
}

const LAYOUTS: ReadonlyArray<{ value: Layout; label: string }> = [
  { value: "pip", label: "Picture-in-picture" },
  { value: "hook_intro", label: "Hook intro" },
  { value: "split", label: "Split screen" },
];

const LANGUAGES: ReadonlyArray<{ value: Language; label: string }> = [
  { value: "auto", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "tr", label: "Turkish" },
];

interface FormState {
  video_subject: string;
  layout: Layout;
  language: Language;
  caption_style: string;
  voice_name: string;
  avatar_id: string;
  target_duration_s: number;
}

const DEFAULT_FORM: FormState = {
  video_subject: "",
  layout: "pip",
  language: "auto",
  caption_style: "karaoke_yellow",
  voice_name: "",
  avatar_id: "",
  target_duration_s: 30,
};

/**
 * Generate view: configures the reel params for the uploaded recording, creates a
 * job, and polls it to completion. Renders live progress and, on success, the
 * result link. The heavy lifting (script → TTS → avatar → compose) all happens on
 * the backend — the desktop app only drives it.
 */
export function GenerateView({ recordingKey, onGenerated }: GenerateViewProps) {
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [job, setJob] = useState<Job | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const update = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const submit = useCallback(async () => {
    if (!recordingKey) return;
    if (!form.video_subject.trim()) {
      setError("Describe what the reel is about first.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setJob(null);

    const params: ReelForgeParams = {
      video_subject: form.video_subject.trim(),
      voice_name: form.voice_name.trim(),
      avatar_id: form.avatar_id.trim(),
      avatar_provider: "heygen",
      caption_style: form.caption_style,
      layout: form.layout,
      aspect: "9:16",
      language: form.language,
      target_duration_s: form.target_duration_s,
      platforms: ["tiktok"],
      screen_recording_key: recordingKey,
    };
    const body: JobCreateRequest = { params, tos_disclosure: true };

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const created = await createJob(body);
      setJob({ job_id: created.job_id, state: created.state, progress: created.progress });
      const final = await pollJob(
        created.job_id,
        (tick) => setJob(tick),
        { signal: controller.signal },
      );
      if (isFailedState(final.state)) {
        setError(final.error ?? "The job failed during rendering.");
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Failed to create the job.");
    } finally {
      setSubmitting(false);
      abortRef.current = null;
    }
  }, [form, recordingKey]);

  if (!recordingKey) {
    return (
      <section className="view">
        <div className="view-head">
          <h1 className="view-title">Generate a reel</h1>
        </div>
        <div className="card panel empty">
          <p className="muted">Record a screen capture first, then come back here to generate.</p>
        </div>
      </section>
    );
  }

  const done = job?.state === JobState.Complete;

  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Generate a reel</h1>
        <p className="view-sub">Your recording is ready. Configure the reel and generate.</p>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="card panel form">
        <label className="field">
          <span className="field-label">What is this reel about?</span>
          <textarea
            className="input textarea"
            rows={3}
            value={form.video_subject}
            placeholder="e.g. A 30-second walkthrough of our new onboarding flow"
            onChange={(e) => update("video_subject", e.target.value)}
          />
        </label>

        <div className="field-row">
          <label className="field">
            <span className="field-label">Layout</span>
            <select
              className="input"
              value={form.layout}
              onChange={(e) => update("layout", e.target.value as Layout)}
            >
              {LAYOUTS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Language</span>
            <select
              className="input"
              value={form.language}
              onChange={(e) => update("language", e.target.value as Language)}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span className="field-label">Target duration (s)</span>
            <input
              className="input"
              type="number"
              min={10}
              max={120}
              value={form.target_duration_s}
              onChange={(e) => update("target_duration_s", Number(e.target.value) || 30)}
            />
          </label>
        </div>

        <div className="field-row">
          <label className="field">
            <span className="field-label">Voice name</span>
            <input
              className="input"
              value={form.voice_name}
              placeholder="e.g. elevenlabs:Rachel"
              onChange={(e) => update("voice_name", e.target.value)}
            />
          </label>

          <label className="field">
            <span className="field-label">Avatar id</span>
            <input
              className="input"
              value={form.avatar_id}
              placeholder="HeyGen avatar id"
              onChange={(e) => update("avatar_id", e.target.value)}
            />
          </label>

          <label className="field">
            <span className="field-label">Caption style</span>
            <input
              className="input"
              value={form.caption_style}
              onChange={(e) => update("caption_style", e.target.value)}
            />
          </label>
        </div>

        <div className="panel-actions">
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void submit()}
            disabled={submitting}
          >
            {submitting ? "Generating…" : "Generate reel"}
          </button>
        </div>
      </div>

      {job && (
        <div className="card panel">
          <div className="job-status">
            <span className="job-id">Job {job.job_id}</span>
            <span className="muted">{Math.round((job.progress ?? 0) * 100)}%</span>
          </div>
          <div className="progress">
            <div
              className="progress-bar"
              style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
            />
          </div>

          {done && (
            <div className="panel-actions">
              {job.result_url && (
                <a
                  className="btn btn--accent"
                  href={job.result_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open result
                </a>
              )}
              <button type="button" className="btn btn--ghost" onClick={onGenerated}>
                Go to library
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
