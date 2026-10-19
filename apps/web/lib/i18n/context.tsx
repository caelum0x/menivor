"use client";

import * as React from "react";
import {
  DEFAULT_LOCALE,
  LOCALE_COOKIE,
  LOCALE_COOKIE_MAX_AGE,
  type Locale,
} from "./config";
import { getDictionary } from "./dictionaries";
import { createTranslator, type Translator } from "./translator";

interface I18nContextValue {
  readonly locale: Locale;
  readonly t: Translator;
  readonly setLocale: (next: Locale) => void;
}

const I18nContext = React.createContext<I18nContextValue | null>(null);

/**
 * Persist the chosen locale in a cookie so server components pick it up on the
 * next render/navigation. Immutable string assembly — no cookie mutation state
 * is kept in memory.
 */
function persistLocale(locale: Locale): void {
  if (typeof document === "undefined") return;
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=${LOCALE_COOKIE_MAX_AGE}; samesite=lax`;
}

/**
 * Client i18n provider. Seeded by the server with the cookie-resolved
 * `initialLocale` so the first client render matches the server output (no
 * hydration mismatch). Switching locale updates client state instantly and
 * writes the cookie; a caller may additionally refresh the router so server
 * components re-render in the new locale.
 */
export function I18nProvider({
  initialLocale,
  children,
}: Readonly<{ initialLocale: Locale; children: React.ReactNode }>) {
  const [locale, setLocaleState] = React.useState<Locale>(initialLocale);

  const setLocale = React.useCallback((next: Locale) => {
    persistLocale(next);
    setLocaleState(next);
  }, []);

  const value = React.useMemo<I18nContextValue>(() => {
    const t = createTranslator(getDictionary(locale));
    return { locale, t, setLocale };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/**
 * Read the i18n context. Falls back to the default English translator when used
 * outside a provider, so a stray client component can never crash for lack of a
 * provider — it just renders English.
 */
export function useI18n(): I18nContextValue {
  const ctx = React.useContext(I18nContext);
  if (ctx) return ctx;
  return {
    locale: DEFAULT_LOCALE,
    t: createTranslator(getDictionary(DEFAULT_LOCALE)),
    setLocale: () => undefined,
  };
}

/** Convenience hook returning just the translate function. */
export function useTranslations(): Translator {
  return useI18n().t;
}
