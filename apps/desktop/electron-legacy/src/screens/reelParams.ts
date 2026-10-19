/**
 * Create-flow form model + job-body builder for the desktop Create screen.
 *
 * The desktop app does not reimplement the render pipeline — it only assembles the
 * `POST /jobs` payload from a small form and hands it to {@link createJob}. This
 * module keeps that shape in one place so the screen component stays declarative.
 *
 * The four EDITING-POLISH toggles (`auto_tighten`, `auto_zoom`, `camera_motion`,
 * `remove_bg`) are additive, opt-in, TOP-LEVEL `JobCreateRequest` fields (never
 * inside `params`). They are declared locally here as a widening of
 * `JobCreateRequest` so the screen stays self-contained without editing the shared
 * `lib/types` domain module.
 */

import type {
  JobCreateRequest,
  Language,
  Layout,
  ReelForgeParams,
} from "../lib/types";

// ---------------------------------------------------------------------------
// Editing-polish (opt-in, degrade-safe backend passes)
// ---------------------------------------------------------------------------

/** Virtual-camera motion presets ("none" disables the pass). */
export type CameraMotion =
  | "none"
  | "ken_burns"
  | "push_in"
  | "pull_out"
  | "whip_pan";

/** The additive editing-polish fields sent alongside a job create request. */
export interface PolishFields {
  auto_tighten?: boolean;
  auto_zoom?: boolean;
  camera_motion?: CameraMotion;
  remove_bg?: boolean;
}

/** `JobCreateRequest` widened with the additive editing-polish fields. */
export type JobCreateBody = JobCreateRequest & PolishFields;

/** The four polish toggles as a single form-friendly value object. */
export interface PolishState {
  auto_tighten: boolean;
  auto_zoom: boolean;
  camera_motion: CameraMotion;
  remove_bg: boolean;
}

// ---------------------------------------------------------------------------
// Picker option tables
// ---------------------------------------------------------------------------

export const LAYOUTS: ReadonlyArray<{ value: Layout; label: string }> = [
  { value: "pip", label: "Picture-in-picture" },
  { value: "hook_intro", label: "Hook intro" },
  { value: "split", label: "Split screen" },
];

export const LANGUAGES: ReadonlyArray<{ value: Language; label: string }> = [
  { value: "auto", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "tr", label: "Turkish" },
];

export const CAMERA_MOTIONS: ReadonlyArray<{
  value: CameraMotion;
  label: string;
}> = [
  { value: "none", label: "None" },
  { value: "ken_burns", label: "Ken Burns" },
  { value: "push_in", label: "Push in" },
  { value: "pull_out", label: "Pull out" },
  { value: "whip_pan", label: "Whip pan" },
];

/** A single editing-polish boolean toggle, for rendering the toggle grid. */
export const POLISH_TOGGLES: ReadonlyArray<{
  key: "auto_tighten" | "auto_zoom" | "remove_bg";
  label: string;
  hint: string;
}> = [
  {
    key: "auto_tighten",
    label: "Auto-tighten",
    hint: "Trim silent gaps and static stretches for a tighter pace.",
  },
  {
    key: "auto_zoom",
    label: "Auto-zoom",
    hint: "Add subtle punch-in zooms on scene changes.",
  },
  {
    key: "remove_bg",
    label: "Remove background",
    hint: "Matte the presenter so it composites cleanly over your screen.",
  },
];

// ---------------------------------------------------------------------------
// Form model
// ---------------------------------------------------------------------------

/** Declarative state for the Create screen's configuration form. */
export interface CreateFormState {
  video_subject: string;
  layout: Layout;
  language: Language;
  caption_style: string;
  voice_name: string;
  avatar_id: string;
  target_duration_s: number;
  polish: PolishState;
}

/** Sensible starting values for a fresh reel. */
export const DEFAULT_CREATE_FORM: CreateFormState = {
  video_subject: "",
  layout: "pip",
  language: "auto",
  caption_style: "karaoke_yellow",
  voice_name: "",
  avatar_id: "",
  target_duration_s: 30,
  polish: {
    auto_tighten: false,
    auto_zoom: false,
    camera_motion: "none",
    remove_bg: false,
  },
};

/** Bounds mirrored from the wizard so the number input stays in a sane range. */
export const DURATION_MIN_S = 10;
export const DURATION_MAX_S = 120;

/**
 * Assemble the `POST /jobs` body from the form and the uploaded recording's R2
 * key. Only enabled polish toggles are attached (so the payload stays minimal and
 * the backend defaults apply otherwise).
 */
export function buildJobBody(
  form: CreateFormState,
  screenRecordingKey: string,
): JobCreateBody {
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
    screen_recording_key: screenRecordingKey,
  };

  const body: JobCreateBody = { params, tos_disclosure: true };
  if (form.polish.auto_tighten) body.auto_tighten = true;
  if (form.polish.auto_zoom) body.auto_zoom = true;
  if (form.polish.remove_bg) body.remove_bg = true;
  if (form.polish.camera_motion !== "none") {
    body.camera_motion = form.polish.camera_motion;
  }
  return body;
}
