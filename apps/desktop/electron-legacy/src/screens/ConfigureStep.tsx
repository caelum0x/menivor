import type { CameraMotion, CreateFormState, PolishState } from "./reelParams";
import {
  CAMERA_MOTIONS,
  DURATION_MAX_S,
  DURATION_MIN_S,
  LANGUAGES,
  LAYOUTS,
  POLISH_TOGGLES,
} from "./reelParams";
import type { Language, Layout } from "../lib/types";

interface ConfigureStepProps {
  /** Object URL of the just-recorded clip, for the review player. */
  previewUrl: string;
  form: CreateFormState;
  /** Immutable form update. */
  onChange: (next: CreateFormState) => void;
  /** Discard the recording and go back to capture. */
  onReRecord: () => void;
  /** Kick off upload → create job → poll. */
  onGenerate: () => void;
  submitting: boolean;
  error: string | null;
}

/**
 * Configure step: review the recorded clip, then set the reel's prompt, language,
 * layout, duration, voice/avatar, caption style, and the opt-in editing-polish
 * toggles (auto-tighten / auto-zoom / camera motion / remove background) before
 * generating. Purely declarative — all state lives in the parent Create screen.
 */
export function ConfigureStep({
  previewUrl,
  form,
  onChange,
  onReRecord,
  onGenerate,
  submitting,
  error,
}: ConfigureStepProps) {
  const update = <K extends keyof CreateFormState>(
    key: K,
    value: CreateFormState[K],
  ) => onChange({ ...form, [key]: value });

  const updatePolish = <K extends keyof PolishState>(
    key: K,
    value: PolishState[K],
  ) => onChange({ ...form, polish: { ...form.polish, [key]: value } });

  return (
    <section className="view">
      <div className="view-head">
        <h1 className="view-title">Configure your reel</h1>
        <p className="view-sub">
          Review the recording, then set how the reel should look and sound.
        </p>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="card panel">
        <video className="preview" src={previewUrl} controls />
        <div className="panel-actions">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={onReRecord}
            disabled={submitting}
          >
            Re-record
          </button>
        </div>
      </div>

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
              min={DURATION_MIN_S}
              max={DURATION_MAX_S}
              value={form.target_duration_s}
              onChange={(e) =>
                update("target_duration_s", Number(e.target.value) || 30)
              }
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
      </div>

      <div className="card panel form">
        <div className="polish-head">
          <span className="field-label">Editing polish</span>
          <p className="muted small">
            Optional, degrade-safe passes applied to the screen recording before
            compose.
          </p>
        </div>

        <div className="toggle-grid">
          {POLISH_TOGGLES.map((t) => (
            <label key={t.key} className="toggle">
              <input
                type="checkbox"
                checked={form.polish[t.key]}
                onChange={(e) => updatePolish(t.key, e.target.checked)}
              />
              <span className="toggle-body">
                <span className="toggle-label">{t.label}</span>
                <span className="toggle-hint muted">{t.hint}</span>
              </span>
            </label>
          ))}
        </div>

        <label className="field">
          <span className="field-label">Camera motion</span>
          <select
            className="input"
            value={form.polish.camera_motion}
            onChange={(e) =>
              updatePolish("camera_motion", e.target.value as CameraMotion)
            }
          >
            {CAMERA_MOTIONS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="panel-actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={onGenerate}
          disabled={submitting}
        >
          {submitting ? "Generating…" : "Generate reel"}
        </button>
      </div>
    </section>
  );
}
