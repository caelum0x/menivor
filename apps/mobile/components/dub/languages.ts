import { DUB_LANGUAGE_CODES, type DubLanguage } from "@/lib/types";

/**
 * Display metadata for the bundled-font dubbing languages. Used both as the
 * offline fallback catalog and to fill in names the backend may omit.
 */
const LANGUAGE_META: Record<string, { name: string; native_name: string }> = {
  en: { name: "English", native_name: "English" },
  tr: { name: "Turkish", native_name: "Türkçe" },
  es: { name: "Spanish", native_name: "Español" },
  fr: { name: "French", native_name: "Français" },
  de: { name: "German", native_name: "Deutsch" },
  pt: { name: "Portuguese", native_name: "Português" },
  it: { name: "Italian", native_name: "Italiano" },
};

/** Local fallback catalog used when GET /dub/languages is unavailable. */
export const FALLBACK_DUB_LANGUAGES: readonly DubLanguage[] =
  DUB_LANGUAGE_CODES.map((code) => ({ code, ...LANGUAGE_META[code] }));

/** Fills in display names for a backend language that omitted them. */
export function withDisplayNames(lang: DubLanguage): DubLanguage {
  const meta = LANGUAGE_META[lang.code];
  return {
    ...lang,
    name: lang.name || meta?.name || lang.code,
    native_name:
      lang.native_name || meta?.native_name || lang.name || lang.code,
  };
}
