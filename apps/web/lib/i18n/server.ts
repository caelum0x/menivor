import { cookies } from "next/headers";
import { LOCALE_COOKIE, normalizeLocale, type Locale } from "./config";
import { getDictionary, type Messages } from "./dictionaries";
import { createTranslator, type Translator } from "./translator";

/**
 * Server-side i18n helpers for React Server Components.
 *
 * The active locale lives in a cookie so it survives navigation and is readable
 * on both the server (here) and the client (the `I18nProvider` seed). These are
 * async because `cookies()` is async in the Next.js App Router.
 */

/** The visitor's active locale from the cookie, defaulting to English. */
export async function getLocale(): Promise<Locale> {
  const store = await cookies();
  return normalizeLocale(store.get(LOCALE_COOKIE)?.value);
}

/** The message catalog for the active locale. */
export async function getMessages(): Promise<Messages> {
  return getDictionary(await getLocale());
}

/** A translator bound to the active locale, for use in server components. */
export async function getTranslations(): Promise<Translator> {
  return createTranslator(await getMessages());
}
