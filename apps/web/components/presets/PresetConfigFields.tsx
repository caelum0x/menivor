"use client";

import * as React from "react";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  CAPTION_STYLE_OPTIONS,
  LANGUAGE_OPTIONS,
  LAYOUT_OPTIONS,
} from "@/components/wizard/types";
import type { PresetConfig } from "@/components/presets/preset-config";
import {
  avatarLabel,
  voiceLabel,
  type PresetCatalogs,
} from "@/components/presets/use-catalogs";

interface PresetConfigFieldsProps {
  value: Readonly<PresetConfig>;
  onChange: (patch: Readonly<Partial<PresetConfig>>) => void;
  catalogs: Readonly<PresetCatalogs>;
  disabled?: boolean;
}

/** An empty option renders as "no preference" — the field is optional. */
const ANY = "";

interface FieldProps {
  id: string;
  label: string;
  children: React.ReactNode;
}

function Field({ id, label, children }: Readonly<FieldProps>) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

/**
 * The optional per-field settings a brand kit captures: avatar, voice, layout,
 * caption style, music, and language. Every field is optional (a blank leading
 * option means "no preference"). Options come from the live catalogs, falling
 * back to the wizard's built-in lists for layout / caption / language so the
 * form is usable even if a catalog request failed.
 */
export function PresetConfigFields({
  value,
  onChange,
  catalogs,
  disabled = false,
}: PresetConfigFieldsProps) {
  const layoutOptions =
    catalogs.layouts.length > 0
      ? catalogs.layouts.map((l) => ({ value: String(l.id), label: l.name }))
      : LAYOUT_OPTIONS.map((l) => ({ value: l.value, label: l.title }));

  const captionOptions =
    catalogs.captionStyles.length > 0
      ? catalogs.captionStyles.map((c) => ({ value: c.id, label: c.name }))
      : CAPTION_STYLE_OPTIONS.map((c) => ({ value: c.value, label: c.title }));

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field id="preset-avatar" label="Avatar">
        <Select
          id="preset-avatar"
          disabled={disabled}
          value={value.avatar_id ?? ANY}
          onChange={(e) => onChange({ avatar_id: e.target.value || undefined })}
        >
          <option value={ANY}>No preference</option>
          {catalogs.avatars.map((a) => (
            <option key={a.avatar_id} value={a.avatar_id}>
              {avatarLabel(a)}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="preset-voice" label="Voice">
        <Select
          id="preset-voice"
          disabled={disabled}
          value={value.voice_id ?? ANY}
          onChange={(e) => {
            const voice_id = e.target.value || undefined;
            const match = catalogs.voices.find((v) => v.voice_id === voice_id);
            onChange({
              voice_id,
              voice_label: match ? voiceLabel(match) : undefined,
            });
          }}
        >
          <option value={ANY}>No preference</option>
          {catalogs.voices.map((v) => (
            <option key={v.voice_id} value={v.voice_id}>
              {voiceLabel(v)}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="preset-layout" label="Layout">
        <Select
          id="preset-layout"
          disabled={disabled}
          value={value.layout ?? ANY}
          onChange={(e) => onChange({ layout: e.target.value || undefined })}
        >
          <option value={ANY}>No preference</option>
          {layoutOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="preset-caption" label="Caption style">
        <Select
          id="preset-caption"
          disabled={disabled}
          value={value.caption_style ?? ANY}
          onChange={(e) =>
            onChange({ caption_style: e.target.value || undefined })
          }
        >
          <option value={ANY}>No preference</option>
          {captionOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="preset-music" label="Background music">
        <Select
          id="preset-music"
          disabled={disabled}
          value={value.music_id ?? ANY}
          onChange={(e) => onChange({ music_id: e.target.value || undefined })}
        >
          <option value={ANY}>No preference</option>
          {catalogs.music.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </Select>
      </Field>

      <Field id="preset-language" label="Language">
        <Select
          id="preset-language"
          disabled={disabled}
          value={value.language ?? ANY}
          onChange={(e) => onChange({ language: e.target.value || undefined })}
        >
          <option value={ANY}>No preference</option>
          {LANGUAGE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  );
}
