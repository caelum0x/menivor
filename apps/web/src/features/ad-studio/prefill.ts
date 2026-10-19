/**
 * Ad Studio deep-link prefill (Rally -> Menivor bridge).
 *
 * `/ad-studio?url=<product site>&offer=<offer>&audience=<audience>&source=rally`
 * pre-fills the product link and carries the campaign's offer and audience into
 * the form. Nothing is fetched or generated until the user presses the button.
 */

export type PrefillSource = "rally" | "";

export interface AdStudioPrefill {
  url: string;
  offer: string;
  audience: string;
  source: PrefillSource;
}

export const EMPTY_PREFILL: AdStudioPrefill = { url: "", offer: "", audience: "", source: "" };

const MAX_TEXT = 400;

type RawParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string {
  const raw = Array.isArray(value) ? value[0] : value;
  return typeof raw === "string" ? raw : "";
}

function cleanText(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT);
}

/** Only an absolute http(s) URL is accepted; anything else is dropped. */
function cleanUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 2048) return "";
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : "";
  } catch {
    return "";
  }
}

export function parseAdStudioPrefill(params: RawParams | undefined): AdStudioPrefill {
  if (!params) return EMPTY_PREFILL;
  return {
    url: cleanUrl(first(params.url)),
    offer: cleanText(first(params.offer)),
    audience: cleanText(first(params.audience)),
    source: first(params.source).trim().toLowerCase() === "rally" ? "rally" : "",
  };
}

export function hasPrefill(prefill: AdStudioPrefill): boolean {
  return Boolean(prefill.url || prefill.offer || prefill.audience);
}

/** Manual-entry description seeded from the carried offer and audience. */
export function prefillDescription(prefill: AdStudioPrefill): string {
  return [prefill.offer && `Offer: ${prefill.offer}`, prefill.audience && `For: ${prefill.audience}`]
    .filter(Boolean)
    .join("\n");
}
