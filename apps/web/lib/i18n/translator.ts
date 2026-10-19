import { en } from "./dictionaries/en";
import type { Messages } from "./dictionaries/en";

/**
 * Dotted key paths into the message catalog, e.g. `"landing.heroTitle"`.
 * Derived from the English master so keys are checked at compile time.
 */
export type TranslationKey = PathsOf<Messages>;

type PathsOf<T> = {
  [K in keyof T & string]: T[K] extends string
    ? K
    : `${K}.${PathsOf<T[K]>}`;
}[keyof T & string];

/** Interpolation values substituted into `{placeholder}` slots. */
export type TranslationVars = Readonly<Record<string, string | number>>;

/** The translate function returned by {@link createTranslator}. */
export type Translator = (key: TranslationKey, vars?: TranslationVars) => string;

function resolve(source: unknown, key: string): string | undefined {
  let node: unknown = source;
  for (const segment of key.split(".")) {
    if (node && typeof node === "object" && segment in node) {
      node = (node as Record<string, unknown>)[segment];
    } else {
      return undefined;
    }
  }
  return typeof node === "string" ? node : undefined;
}

function interpolate(template: string, vars?: TranslationVars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

/**
 * Build a translator bound to a locale's catalog. Resolution order is:
 * active catalog → English fallback → the raw key. A missing translation can
 * therefore never render blank or throw — it degrades to English, then to the
 * key itself, so surfaces stay legible while a locale is still being filled in.
 */
export function createTranslator(messages: Messages): Translator {
  return (key, vars) => {
    const value = resolve(messages, key) ?? resolve(en, key) ?? key;
    return interpolate(value, vars);
  };
}
