"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StyleChips } from "@/components/marketing/styles/StylePick";
import { VARIANT_COUNT } from "@/src/features/create-compose/one-flow/plan";
import { isStoreLink } from "@/src/features/app-audit/api";
import { AppAuditRunner } from "@/components/marketing/app-audit/AppAuditRunner";
import { HeroLinkInput } from "./HeroLinkInput";

/**
 * The landing box: paste any link (site, app, social post or profile) or type
 * a topic, then sign up. Plain GET into
 * /sign-up (works before any JavaScript loads); the sign-up page carries `q`
 * through the card check into the create box, which starts the reels itself.
 * When the pasted link is an App Store/Play app, a free audit preview
 * (Menivor Growth phase 1) appears alongside the video flow below — it never
 * replaces the video-creation CTA above it.
 */
export function SignupBox({ note }: Readonly<{ note: string }>) {
  const [link, setLink] = useState("");
  return (
    <div className="w-full">
      <form
        id="make"
        action="/sign-up"
        method="get"
        className="glass flex w-full scroll-mt-24 flex-col gap-3 rounded-2xl p-3 sm:p-4"
      >
        <label htmlFor="hero-create-input" className="sr-only">
          Any link (your website, app, or a social post or profile) or a topic
        </label>
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-start">
          <HeroLinkInput value={link} onValueChange={setLink} />
          <Button type="submit" size="lg" data-copy-source="src/features/create-compose/one-flow/plan.ts">
            {/* copy-source: src/features/create-compose/one-flow/plan.ts VARIANT_COUNT */}
            Make {VARIANT_COUNT} reels <ArrowRight className="size-4" aria-hidden />
          </Button>
        </div>
        <StyleChips />
        <p className="px-1 text-sm text-muted-foreground">
          {note}{" "}
          <Link href="/creator-contract" className="underline underline-offset-4">
            Our Creator Contract
          </Link>
        </p>
      </form>
      {isStoreLink(link) ? (
        <div className="mt-3">
          <AppAuditRunner initialUrl={link} showInput={false} />
        </div>
      ) : null}
    </div>
  );
}
