"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { Audience, Gender } from "./api";

export const DEFAULT_AUDIENCE: Audience = { countries: ["US"], age_min: 18, age_max: 65, gender: "all" };

/** Parse "US, gb tr" into unique upper-case country codes (or numeric TikTok location ids). */
export function parseCountries(raw: string): string[] {
  const tokens = raw
    .split(/[\s,]+/)
    .map((t) => t.trim().toUpperCase())
    .filter((t) => /^[A-Z]{2}$/.test(t) || /^\d{3,12}$/.test(t));
  return Array.from(new Set(tokens)).slice(0, 25);
}

/** Audience basics: countries, age range and gender. */
export function AudienceFields({
  audience,
  countriesText,
  onCountriesText,
  onChange,
}: {
  audience: Audience;
  countriesText: string;
  onCountriesText: (text: string) => void;
  onChange: (next: Audience) => void;
}) {
  const clampAge = (value: string, fallback: number) => {
    const n = Number.parseInt(value, 10);
    return Number.isFinite(n) ? Math.min(65, Math.max(18, n)) : fallback;
  };
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-medium">Audience</legend>
      <div className="space-y-1">
        <Label htmlFor="ads-countries">Countries</Label>
        <Input
          id="ads-countries"
          value={countriesText}
          placeholder="US, GB, TR"
          onChange={(e) => {
            onCountriesText(e.target.value);
            onChange({ ...audience, countries: parseCountries(e.target.value) });
          }}
        />
        <p className="text-xs text-muted-foreground">Two-letter country codes, separated by commas.</p>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <Label htmlFor="ads-age-min">Min age</Label>
          <Input
            id="ads-age-min"
            type="number"
            min={18}
            max={65}
            value={audience.age_min}
            onChange={(e) => onChange({ ...audience, age_min: clampAge(e.target.value, 18) })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ads-age-max">Max age</Label>
          <Input
            id="ads-age-max"
            type="number"
            min={18}
            max={65}
            value={audience.age_max}
            onChange={(e) => onChange({ ...audience, age_max: clampAge(e.target.value, 65) })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="ads-gender">Gender</Label>
          <Select id="ads-gender" value={audience.gender} onChange={(e) => onChange({ ...audience, gender: e.target.value as Gender })}>
            <option value="all">All</option>
            <option value="female">Women</option>
            <option value="male">Men</option>
          </Select>
        </div>
      </div>
    </fieldset>
  );
}
