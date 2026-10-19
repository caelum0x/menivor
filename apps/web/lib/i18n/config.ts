/**
 * Lightweight i18n configuration for the Menivor web UI.
 *
 * This is a zero-dependency messages layer (no next-intl / react-i18next):
 * a cookie selects the active locale, server components resolve it via
 * `next/headers`, and client components read it from a React context seeded by
 * the server. English is always the default and the fallback for any missing
 * key, so adding a locale can never break a surface — untranslated strings
 * degrade to English rather than to a raw key.
 */

/** Supported UI locales. English first — it is the default and fallback. */
export const LOCALES = ["en", "tr", "es"] as const;

export type Locale = (typeof LOCALES)[number];

/** Default/fallback locale. */
export const DEFAULT_LOCALE: Locale = "en";

/** Cookie that persists the visitor's chosen UI language. */
export const LOCALE_COOKIE = "menivor_locale";

/** One year, in seconds — the locale cookie's max-age. */
export const LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

/** Human-readable label shown in the language switcher, per locale. */
export const LOCALE_LABELS: Readonly<Record<Locale, string>> = {
  en: "English",
  tr: "Türkçe",
  es: "Español",
};

/** Narrow an untrusted string to a supported `Locale`, else the default. */
export function normalizeLocale(value: string | null | undefined): Locale {
  if (value && (LOCALES as readonly string[]).includes(value)) {
    return value as Locale;
  }
  return DEFAULT_LOCALE;
}

/** Type guard for a supported locale. */
export function isLocale(value: unknown): value is Locale {
  return (
    typeof value === "string" && (LOCALES as readonly string[]).includes(value)
  );
}
