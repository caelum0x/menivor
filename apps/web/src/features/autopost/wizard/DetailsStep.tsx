"use client";

import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import type { CreatorInfo, Visibility } from "../api";
import {
  VISIBILITY_LABEL,
  allowedVisibilities,
  consentText,
  interactionLocks,
  type BatchForm,
} from "../plan";

export interface TikTokCreator {
  accountId: string;
  info: CreatorInfo | null;
  error: string;
}

/**
 * Step 3: what the posts say and who sees them. Follows TikTok's posting
 * rules: the creator is shown by nickname, visibility has no default, every
 * interaction starts off, and commercial content is declared up front.
 */
export function DetailsStep({
  form,
  onChange,
  tiktok,
}: {
  form: BatchForm;
  onChange: (patch: Partial<BatchForm>) => void;
  tiktok: TikTokCreator[];
}) {
  const infos = tiktok.map((t) => t.info).filter((i): i is CreatorInfo => i !== null);
  const hasTikTok = tiktok.length > 0;
  const visibilities = allowedVisibilities(infos);
  const locks = interactionLocks(infos);

  React.useEffect(() => {
    if (form.visibility && !visibilities.includes(form.visibility)) onChange({ visibility: "" });
  }, [form.visibility, visibilities, onChange]);

  return (
    <div className="space-y-6">
      {hasTikTok ? (
        <section className="space-y-1 text-sm">
          <p className="font-medium">Posting to TikTok as</p>
          <ul className="text-muted-foreground">
            {tiktok.map((t) => (
              <li key={t.accountId}>{t.info ? t.info.nickname || t.info.username : t.error || "Checking"}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="space-y-1.5">
        <Label htmlFor="caption">Caption</Label>
        <Textarea
          id="caption"
          rows={3}
          maxLength={2200}
          value={form.caption}
          onChange={(e) => onChange({ caption: e.target.value })}
          placeholder="What should people know?"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="hashtags">Hashtags</Label>
        <Input
          id="hashtags"
          value={form.hashtags}
          onChange={(e) => onChange({ hashtags: e.target.value })}
          placeholder="skincare, morningroutine"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="visibility">Who can see the posts</Label>
        <Select
          id="visibility"
          value={form.visibility}
          onChange={(e) => onChange({ visibility: e.target.value as Visibility | "" })}
        >
          <option value="">Choose</option>
          {visibilities.map((v) => (
            <option key={v} value={v}>
              {VISIBILITY_LABEL[v]}
            </option>
          ))}
        </Select>
        {hasTikTok && infos.some((i) => !i.audited) ? (
          <p className="text-xs text-muted-foreground">
            Until TikTok approves this app, TikTok posts can only be visible to you.
          </p>
        ) : null}
      </div>

      {hasTikTok ? (
        <fieldset className="space-y-2 text-sm">
          <legend className="font-medium">On TikTok</legend>
          <label className="flex items-center gap-3">
            <input
              type="radio"
              name="tiktok-mode"
              checked={form.tiktokMode === "direct"}
              onChange={() => onChange({ tiktokMode: "direct" })}
            />
            Post directly
          </label>
          <label className="flex items-center gap-3">
            <input
              type="radio"
              name="tiktok-mode"
              checked={form.tiktokMode === "draft"}
              onChange={() => onChange({ tiktokMode: "draft" })}
            />
            Send to TikTok drafts to finish in the app
          </label>
          <div className="flex flex-wrap gap-4 pt-1">
            <Toggle label="Allow comments" checked={form.allowComments} locked={locks.comments}
              onChange={(v) => onChange({ allowComments: v })} />
            <Toggle label="Allow Duet" checked={form.allowDuet} locked={locks.duet}
              onChange={(v) => onChange({ allowDuet: v })} />
            <Toggle label="Allow Stitch" checked={form.allowStitch} locked={locks.stitch}
              onChange={(v) => onChange({ allowStitch: v })} />
          </div>
        </fieldset>
      ) : null}

      <fieldset className="space-y-2 text-sm">
        <legend className="font-medium">Promotes a brand, product or service</legend>
        <Toggle label="Yes, this is commercial content" checked={form.commercial}
          onChange={(v) => onChange({ commercial: v, yourBrand: v && form.yourBrand, brandedContent: v && form.brandedContent })} />
        {form.commercial ? (
          <div className="space-y-2 pl-6">
            <Toggle label="Your brand" checked={form.yourBrand} onChange={(v) => onChange({ yourBrand: v })} />
            <Toggle label="Branded content (a paid partnership)" checked={form.brandedContent}
              onChange={(v) => onChange({ brandedContent: v })} />
            <p className="text-xs text-muted-foreground">
              {form.brandedContent
                ? "Shown as \"Paid partnership\". Branded content cannot be private."
                : form.yourBrand
                  ? "Shown as \"Promotional content\"."
                  : "Choose at least one."}
            </p>
          </div>
        ) : null}
      </fieldset>

      <p className="rounded-md border border-white/10 px-3 py-2 text-xs text-muted-foreground">
        Every post is labelled as AI-generated: TikTok&apos;s AI-generated label, YouTube&apos;s
        altered or synthetic content setting, and a line in the Instagram caption.
      </p>

      <label className="flex items-start gap-3 text-sm">
        <input type="checkbox" checked={form.consent} onChange={(e) => onChange({ consent: e.target.checked })} />
        <span>{consentText(form.commercial && form.brandedContent, hasTikTok)}</span>
      </label>
    </div>
  );
}

function Toggle({
  label,
  checked,
  locked = false,
  onChange,
}: {
  label: string;
  checked: boolean;
  locked?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className={`flex items-center gap-2 ${locked ? "opacity-50" : ""}`}>
      <input
        type="checkbox"
        checked={checked && !locked}
        disabled={locked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
      {locked ? <span className="text-xs text-muted-foreground">(off for this account)</span> : null}
    </label>
  );
}
