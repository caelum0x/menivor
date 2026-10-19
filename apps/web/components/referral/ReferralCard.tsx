"use client";

import * as React from "react";
import { Coins, Gift, Users } from "lucide-react";
import type { Referral } from "@/lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CopyButton } from "./CopyButton";

interface ReferralCardProps {
  readonly referral: Referral;
  /**
   * Fully-qualified shareable sign-up link embedding the referral code. Empty
   * until the browser origin resolves on the client (avoids SSR mismatch).
   */
  readonly shareUrl: string;
}

/**
 * Displays the caller's referral code, a shareable invite link, and lifetime
 * stats (people referred + credits earned), each with copy-to-clipboard.
 */
export function ReferralCard({ referral, shareUrl }: ReferralCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Gift className="size-5 text-primary" aria-hidden />
          Invite friends, earn credits
        </CardTitle>
        <CardDescription>
          Share your code or link. When a friend signs up and redeems it, you
          both get bonus render credits.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="referral-code">Your referral code</Label>
          <div className="flex items-center gap-2">
            <Input
              id="referral-code"
              readOnly
              value={referral.code}
              onFocus={(e) => e.currentTarget.select()}
              className="font-mono tracking-wide"
            />
            <CopyButton value={referral.code} label="Copy code" />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="referral-link">Shareable link</Label>
          <div className="flex items-center gap-2">
            <Input
              id="referral-link"
              readOnly
              value={shareUrl}
              onFocus={(e) => e.currentTarget.select()}
              className="truncate"
            />
            <CopyButton value={shareUrl} label="Copy link" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Stat
            icon={<Users className="size-4 text-primary" aria-hidden />}
            label="Friends referred"
            value={referral.referred_count}
          />
          <Stat
            icon={<Coins className="size-4 text-accent" aria-hidden />}
            label="Credits earned"
            value={referral.credits_earned}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  icon,
  label,
  value,
}: Readonly<{ icon: React.ReactNode; label: string; value: number }>) {
  return (
    <div className="rounded-lg border border-border bg-secondary/30 p-4">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
