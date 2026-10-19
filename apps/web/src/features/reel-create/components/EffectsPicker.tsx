"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";
import { Clapperboard, Sparkles } from "lucide-react";

import {
  listMotionPresets,
  listVfxPresets,
  type MotionPreset,
  type VfxPreset,
} from "@/lib/marketplace";

interface EffectsPickerProps {
  cameraMotion: string;
  effects: string[];
  onChange: (cameraMotion: string, effects: string[]) => void;
}

/**
 * Higgsfield-class camera + VFX selector for the reel wizard: a one-click camera
 * move plus a capped "Effects Mix" stack of VFX. Presets come from the server
 * catalog; the compose stage renders the selection.
 */
export function EffectsPicker({ cameraMotion, effects, onChange }: EffectsPickerProps) {
  const { getToken, isLoaded } = useAuth();
  const [motions, setMotions] = React.useState<MotionPreset[]>([]);
  const [vfx, setVfx] = React.useState<VfxPreset[]>([]);
  const [maxStack, setMaxStack] = React.useState(4);

  React.useEffect(() => {
    if (!isLoaded) return;
    let active = true;
    void (async () => {
      try {
        const token = (await getToken()) ?? undefined;
        const [m, v] = await Promise.all([
          listMotionPresets({ token }),
          listVfxPresets({ token }),
        ]);
        if (!active) return;
        setMotions(m);
        setVfx(v.vfx);
        setMaxStack(v.maxStack);
      } catch {
        if (active) {
          setMotions([]);
          setVfx([]);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [isLoaded, getToken]);

  const toggleEffect = (id: string) => {
    if (effects.includes(id)) {
      onChange(cameraMotion, effects.filter((e) => e !== id));
    } else if (effects.length < maxStack) {
      onChange(cameraMotion, [...effects, id]);
    }
  };

  if (motions.length === 0 && vfx.length === 0) return null;

  return (
    <div className="border-t border-border pt-4">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Clapperboard className="h-4 w-4 text-primary" aria-hidden /> Camera &amp; effects
        <span className="font-normal text-muted-foreground">(optional)</span>
      </h3>

      <label className="mb-3 grid gap-1 text-xs text-muted-foreground">
        Camera motion
        <select
          value={cameraMotion || "none"}
          onChange={(e) => onChange(e.target.value, effects)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        >
          {motions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>

      <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <Sparkles className="h-4 w-4 text-primary" aria-hidden />
        Effects Mix ({effects.length}/{maxStack})
      </div>
      <div className="flex flex-wrap gap-2">
        {vfx.map((v) => {
          const active = effects.includes(v.id);
          const disabled = !active && effects.length >= maxStack;
          return (
            <button
              key={v.id}
              type="button"
              disabled={disabled}
              title={v.description}
              onClick={() => toggleEffect(v.id)}
              className={`rounded-full border px-3 py-1 text-sm transition ${
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : disabled
                    ? "border-border text-muted-foreground/40"
                    : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {v.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
