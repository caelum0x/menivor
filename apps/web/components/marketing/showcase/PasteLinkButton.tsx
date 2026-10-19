"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { styleCreateHref, type StyleId } from "@/lib/styles/catalog";
import { MAKE_ANCHOR, useStylePick } from "@/components/marketing/styles/StylePick";

/**
 * The page's one action, "Paste a link": preselects the tile's style (when it
 * has one) and moves focus to the paste box. Without the box on the page (or
 * before JavaScript) it is a plain link into the create box.
 */
export function PasteLinkButton({
  styleId = null,
  className,
  icon,
  label = "Paste a link",
}: Readonly<{
  styleId?: StyleId | null;
  className?: string;
  icon?: React.ReactNode;
  label?: string;
}>) {
  const pick = useStylePick();
  const href = styleId ? styleCreateHref(styleId) : "/create";
  return (
    <a
      href={href}
      onClick={(event) => {
        const box = document.getElementById(MAKE_ANCHOR);
        if (!box) return;
        event.preventDefault();
        if (styleId && pick) pick.pick(styleId);
        box.scrollIntoView({ behavior: "smooth", block: "center" });
        box.querySelector<HTMLInputElement>("input[name=q]")?.focus({ preventScroll: true });
      }}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-full bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-[inset_0_-2px_0_rgba(0,0,0,0.22)] transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-black",
        className,
      )}
    >
      {icon}
      {label}
    </a>
  );
}
