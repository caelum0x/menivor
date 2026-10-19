"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { REEL_STYLES, findStyle, styleCreateHref, type StyleId } from "@/lib/styles/catalog";

/** Anchor of the landing paste box (the gallery scrolls back to it). */
export const MAKE_ANCHOR = "make";

interface StylePickValue {
  readonly styleId: StyleId | null;
  readonly pick: (id: StyleId) => void;
}

const StylePickContext = React.createContext<StylePickValue | null>(null);

/** Shares the landing's picked style between the gallery and the paste box. */
export function StylePickProvider({
  initial = null,
  children,
}: Readonly<{ initial?: StyleId | null; children: React.ReactNode }>) {
  const [styleId, setStyleId] = React.useState<StyleId | null>(initial);
  const value = React.useMemo(() => ({ styleId, pick: setStyleId }), [styleId]);
  return <StylePickContext.Provider value={value}>{children}</StylePickContext.Provider>;
}

export function useStylePick(): StylePickValue | null {
  return React.useContext(StylePickContext);
}

/**
 * Inside the paste box form: the hidden `preset` field plus one-click style
 * chips. Renders nothing outside a provider (other pages reuse the box).
 */
export function StyleChips() {
  const pick = useStylePick();
  if (!pick) return null;
  return (
    <div className="flex flex-col gap-2">
      {pick.styleId ? <input type="hidden" name="preset" value={pick.styleId} /> : null}
      <div role="radiogroup" aria-label="Style" className="flex flex-wrap gap-1.5">
        {REEL_STYLES.map((style) => {
          const selected = pick.styleId === style.id;
          return (
            <button
              key={style.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => pick.pick(style.id)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                selected
                  ? "border-primary/70 bg-primary/15 text-foreground"
                  : "border-white/10 text-muted-foreground hover:border-primary/40 hover:text-foreground",
              )}
            >
              {style.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/**
 * "Use this style" on a gallery card: preselects the style in the paste box
 * and scrolls back to it. Without JavaScript it is a plain link into the
 * create box with the style preselected.
 */
export function UseStyleButton({
  styleId,
  className,
}: Readonly<{ styleId: StyleId; className?: string }>) {
  const pick = useStylePick();
  const style = findStyle(styleId);
  return (
    <a
      href={styleCreateHref(styleId)}
      onClick={(event) => {
        if (!pick) return;
        event.preventDefault();
        pick.pick(styleId);
        const box = document.getElementById(MAKE_ANCHOR);
        box?.scrollIntoView({ behavior: "smooth", block: "center" });
        box?.querySelector<HTMLInputElement>("input[name=q]")?.focus({ preventScroll: true });
      }}
      className={cn(
        "inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
      aria-label={`Use the ${style?.label ?? "selected"} style`}
    >
      Use this style
    </a>
  );
}
