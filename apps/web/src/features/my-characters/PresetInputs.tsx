"use client";

import * as React from "react";
import { useApiToken } from "@/lib/use-api-token";
import { listBrands, listMyCharacters, type BrandKit, type MyCharacter } from "./api";

export interface PresetInputsValue {
  readonly brandKitId: string;
  readonly characterId: string;
}

export interface PresetInputsProps {
  /** Characters apply to AI-video presets; brand kits to every preset. */
  readonly allowCharacter: boolean;
  readonly value: PresetInputsValue;
  readonly onChange: (next: PresetInputsValue) => void;
}

/** "Use my character / brand" for any preset. Hidden when the user has neither. */
export function PresetInputs({ allowCharacter, value, onChange }: PresetInputsProps) {
  const getApiToken = useApiToken();
  const [brands, setBrands] = React.useState<readonly BrandKit[]>([]);
  const [characters, setCharacters] = React.useState<readonly MyCharacter[]>([]);

  React.useEffect(() => {
    let live = true;
    (async () => {
      try {
        const token = await getApiToken();
        const [kits, mine] = await Promise.all([listBrands({ token }), allowCharacter ? listMyCharacters({ token }) : []]);
        if (!live) return;
        setBrands(kits);
        setCharacters(mine.filter((c) => c.kind !== "real_face" || c.consent?.verified));
      } catch {
        /* optional inputs: the preset still works without them */
      }
    })();
    return () => {
      live = false;
    };
  }, [allowCharacter, getApiToken]);

  if (brands.length === 0 && characters.length === 0) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {brands.length > 0 ? (
        <label className="block text-sm">
          <span className="font-medium">Brand kit</span>
          <select
            className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2"
            value={value.brandKitId}
            onChange={(e) => onChange({ ...value, brandKitId: e.target.value })}
          >
            <option value="">No brand kit</option>
            {brands.map((kit) => (
              <option key={kit.id} value={kit.id}>{kit.name}</option>
            ))}
          </select>
        </label>
      ) : null}
      {allowCharacter && characters.length > 0 ? (
        <label className="block text-sm">
          <span className="font-medium">Character</span>
          <select
            className="mt-1 w-full rounded-xl border border-border bg-background px-3 py-2"
            value={value.characterId}
            onChange={(e) => onChange({ ...value, characterId: e.target.value })}
          >
            <option value="">No character</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>
      ) : null}
    </div>
  );
}
