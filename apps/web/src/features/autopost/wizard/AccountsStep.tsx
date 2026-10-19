"use client";

import * as React from "react";
import Link from "next/link";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { Account } from "../api";
import { PROVIDER_LABEL, type BatchForm } from "../plan";

/** Step 2: which accounts, how to spread the videos, and when to start. */
export function AccountsStep({
  accounts,
  form,
  onChange,
}: {
  accounts: Account[];
  form: BatchForm;
  onChange: (patch: Partial<BatchForm>) => void;
}) {
  if (accounts.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No connected accounts yet.{" "}
        <Link href="/autopost/accounts" className="text-primary underline-offset-4 hover:underline">
          Connect an account
        </Link>{" "}
        first.
      </p>
    );
  }
  const toggle = (id: string) =>
    onChange({
      accountIds: form.accountIds.includes(id)
        ? form.accountIds.filter((x) => x !== id)
        : [...form.accountIds, id],
    });

  return (
    <div className="space-y-6">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Accounts</legend>
        {accounts.map((a) => (
          <label key={a.id} className="flex items-center gap-3 rounded-md border border-white/10 px-3 py-2 text-sm">
            <input type="checkbox" checked={form.accountIds.includes(a.id)} onChange={() => toggle(a.id)} />
            <span className="flex-1">
              {a.display_name || a.handle}{" "}
              <span className="text-muted-foreground">· {PROVIDER_LABEL[a.provider]}</span>
            </span>
            <span className="text-xs text-muted-foreground">{a.daily_cap} a day</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">How to share the videos</legend>
        <label className="flex items-start gap-3 text-sm">
          <input
            type="radio"
            name="mode"
            checked={form.mode === "spread"}
            onChange={() => onChange({ mode: "spread" })}
          />
          <span>
            Spread them out
            <span className="block text-xs text-muted-foreground">
              Each video goes to one account, taking turns so no account goes over its pace.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm">
          <input
            type="radio"
            name="mode"
            checked={form.mode === "every"}
            onChange={() => onChange({ mode: "every" })}
          />
          <span>
            Every video on every account
            <span className="block text-xs text-muted-foreground">
              Use this for accounts that serve different audiences, like regions or languages.
            </span>
          </span>
        </label>
      </fieldset>

      <div className="space-y-1.5">
        <Label htmlFor="start-at">Start</Label>
        <Input
          id="start-at"
          type="datetime-local"
          value={form.startAt}
          onChange={(e) => onChange({ startAt: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">Leave empty to start now.</p>
      </div>
    </div>
  );
}
