import type { Locale } from "../config";
import { DEFAULT_LOCALE } from "../config";
import { en, type Messages } from "./en";
import { tr } from "./tr";
import { es } from "./es";

/**
 * All bundled catalogs. Small enough to ship together (no async chunk loading),
 * which keeps both server resolution and instant client-side switching simple.
 */
const DICTIONARIES: Readonly<Record<Locale, Messages>> = {
  en,
  tr,
  es,
};

/** The message catalog for a locale, falling back to English. */
export function getDictionary(locale: Locale): Messages {
  return DICTIONARIES[locale] ?? DICTIONARIES[DEFAULT_LOCALE];
}

export { en };
export type { Messages };
