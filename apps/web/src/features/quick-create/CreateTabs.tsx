"use client";

/**
 * /create tab switcher: the free narration→captions reel (default, unchanged)
 * and the metered AI-video generator (Wan 2.2 via Replicate). Client-side only
 * so switching never loses form state; the free tab stays the landing default.
 */

import * as React from "react";
import { Mic, Wand2 } from "lucide-react";
import { useTranslations } from "@/lib/i18n/context";
import type { TranslationKey } from "@/lib/i18n/translator";
import { QuickCreate } from "./QuickCreate";
import { AiVideoCreate } from "./AiVideoCreate";

type CreateTab = "narration" | "ai-video";

const TABS: ReadonlyArray<{
  id: CreateTab;
  labelKey: TranslationKey;
  hintKey: TranslationKey;
  icon: typeof Mic;
}> = [
  {
    id: "narration",
    labelKey: "create.tabNarrationLabel",
    hintKey: "create.tabNarrationHint",
    icon: Mic,
  },
  {
    id: "ai-video",
    labelKey: "create.tabAiVideoLabel",
    hintKey: "create.tabAiVideoHint",
    icon: Wand2,
  },
];

export function CreateTabs() {
  const [tab, setTab] = React.useState<CreateTab>("narration");
  const t = useTranslations();

  return (
    <div className="space-y-6">
      <div
        role="tablist"
        aria-label={t("create.tablistLabel")}
        className="grid gap-2 sm:grid-cols-2"
      >
        {TABS.map(({ id, labelKey, hintKey, icon: Icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              id={`create-tab-${id}`}
              aria-selected={active}
              aria-controls={`create-panel-${id}`}
              onClick={() => setTab(id)}
              className={
                active
                  ? "flex items-center gap-3 rounded-lg border border-primary bg-primary/5 px-4 py-3 text-left"
                  : "flex items-center gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:bg-muted"
              }
            >
              <Icon
                className={active ? "size-5 text-primary" : "size-5 text-muted-foreground"}
                aria-hidden
              />
              <span>
                <span className="block text-sm font-semibold">{t(labelKey)}</span>
                <span className="block text-xs text-muted-foreground">
                  {t(hintKey)}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`create-panel-${tab}`}
        aria-labelledby={`create-tab-${tab}`}
      >
        {tab === "narration" ? <QuickCreate /> : <AiVideoCreate />}
      </div>
    </div>
  );
}
