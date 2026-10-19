"use client";

// Reel-create presentation component.

import { Select } from "@/components/ui/select";
import { CAMERA_MOTION_OPTIONS } from "@/components/wizard/types";
import type { CameraMotion } from "@/lib/types";
import { cn } from "@/lib/utils";

interface PolishSwitchProps {
  title: string;
  description: string;
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
}

/**
 * Keyboard-accessible `<button role="switch">` mirroring {@link AutoTightenToggle}
 * (and the brand `EnabledToggle`), so the editing-polish toggles need no
 * headless-UI dependency. Emits the new value upward; never mutates in place.
 */
function PolishSwitch({
  title,
  description,
  checked,
  onChange,
  disabled = false,
}: PolishSwitchProps) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-secondary/20 p-4">
      <div className="space-y-0.5">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={title}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          "disabled:cursor-not-allowed disabled:opacity-50",
          checked ? "bg-primary" : "bg-input",
        )}
      >
        <span
          className={cn(
            "inline-block size-5 rounded-full bg-background shadow transition-transform",
            checked ? "translate-x-[1.375rem]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

interface EditingPolishSectionProps {
  autoZoom: boolean;
  onAutoZoomChange: (enabled: boolean) => void;
  cameraMotion: CameraMotion;
  onCameraMotionChange: (motion: CameraMotion) => void;
  removeBg: boolean;
  onRemoveBgChange: (enabled: boolean) => void;
  disabled?: boolean;
}

/**
 * Review-step group for the three opt-in "editing polish" passes applied to the
 * SCREEN RECORDING / avatar before compose: scene-driven punch-in zoom
 * (`auto_zoom`), a virtual camera move (`camera_motion`), and neural background
 * matting of the avatar (`remove_bg`). Every pass is default-off and
 * degrade-safe on the backend; the voiceover + caption timeline is never
 * touched. Controls are fully controlled and never mutate state in place.
 */
export function EditingPolishSection({
  autoZoom,
  onAutoZoomChange,
  cameraMotion,
  onCameraMotionChange,
  removeBg,
  onRemoveBgChange,
  disabled = false,
}: EditingPolishSectionProps) {
  return (
    <div className="space-y-3">
      <PolishSwitch
        title="Auto-zoom"
        description="Add subtle punch-in zooms on scene changes for more dynamic, higher-retention pacing. Unchanged if nothing to zoom."
        checked={autoZoom}
        onChange={onAutoZoomChange}
        disabled={disabled}
      />

      <div className="rounded-lg border border-border bg-secondary/20 p-4">
        <div className="mb-2 space-y-0.5">
          <p className="text-sm font-medium">Camera motion</p>
          <p className="text-xs text-muted-foreground">
            Apply a gentle virtual camera move to the recording. Narration and
            captions stay in sync; choose “None” to leave the framing static.
          </p>
        </div>
        <Select
          aria-label="Camera motion"
          value={cameraMotion}
          disabled={disabled}
          onChange={(e) =>
            onCameraMotionChange(e.target.value as CameraMotion)
          }
        >
          {CAMERA_MOTION_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </div>

      <PolishSwitch
        title="Remove background"
        description="Neurally matte the presenter so their background is keyed out before compositing over your recording. Unchanged if matting is unavailable."
        checked={removeBg}
        onChange={onRemoveBgChange}
        disabled={disabled}
      />
    </div>
  );
}
