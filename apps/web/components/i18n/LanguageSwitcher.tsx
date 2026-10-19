"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Languages } from "lucide-react";
import { LOCALES, LOCALE_LABELS, isLocale, type Locale } from "@/lib/i18n/config";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";

/**
 * Language switcher: a compact native <select> so it works without extra
 * dependencies and stays keyboard/screen-reader accessible. Changing the value
 * updates the client locale instantly (via context) and refreshes the router so
 * server-rendered surfaces re-render in the chosen language.
 */
export function LanguageSwitcher({
  className,
}: Readonly<{ className?: string }>) {
  const { locale, setLocale, t } = useI18n();
  const router = useRouter();

  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    if (!isLocale(next) || next === locale) return;
    setLocale(next as Locale);
    router.refresh();
  };

  return (
    <label
      className={cn(
        "relative inline-flex items-center gap-1.5 text-muted-foreground",
        className,
      )}
    >
      <Languages className="size-4" aria-hidden />
      <span className="sr-only">{t("languageSwitcher.label")}</span>
      <select
        value={locale}
        onChange={handleChange}
        aria-label={t("languageSwitcher.label")}
        className="cursor-pointer rounded-md border border-border bg-background px-2 py-1 text-sm font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        {LOCALES.map((code) => (
          <option key={code} value={code}>
            {LOCALE_LABELS[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
