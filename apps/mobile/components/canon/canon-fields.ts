/**
 * Shared canon value-field helpers.
 *
 * The create and lock screens edit the SAME value surface (style, palette,
 * typography, voice, product, brand). This module holds the flat, all-string
 * form-field shape ({@link CanonValueFields}) plus the pure conversions between
 * that shape and the API's typed value body — so both screens stay in sync and
 * the route files stay small. List fields are entered as comma-separated text.
 */

import type { CanonValues } from "@/lib/canon";

/** Flat, all-string editable shape of a canon's values (list fields are CSV text). */
export interface CanonValueFields {
  style: string;
  palette: string;
  typography: string;
  voice_id: string;
  voice_tone: string;
  language: string;
  product_name: string;
  product_descriptors: string;
  product_claims: string;
  brand_tone: string;
  brand_avoid: string;
}

/** The typed value slice shared by create/lock request bodies. */
export interface CanonValueBody {
  style: string;
  palette: string[];
  typography: string[];
  voice_id: string;
  voice_tone: string;
  language: string;
  product_name: string;
  product_descriptors: string[];
  product_claims: string[];
  brand_tone: string[];
  brand_avoid: string[];
}

/** An all-empty field set for a fresh create form. */
export const EMPTY_CANON_FIELDS: CanonValueFields = {
  style: "",
  palette: "",
  typography: "",
  voice_id: "",
  voice_tone: "",
  language: "",
  product_name: "",
  product_descriptors: "",
  product_claims: "",
  brand_tone: "",
  brand_avoid: "",
};

/** Split a comma-separated input into a trimmed, non-empty string list. */
export function splitList(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/** Join a string list back into the comma-separated text used by inputs. */
export function joinList(value: readonly string[]): string {
  return value.join(", ");
}

/** Seed a form's fields from an existing locked snapshot's values. */
export function fieldsFromValues(values: CanonValues): CanonValueFields {
  return {
    style: values.style,
    palette: joinList(values.palette),
    typography: joinList(values.typography),
    voice_id: values.voice_id,
    voice_tone: values.voice_tone,
    language: values.language,
    product_name: values.product_name,
    product_descriptors: joinList(values.product_descriptors),
    product_claims: joinList(values.product_claims),
    brand_tone: joinList(values.brand_tone),
    brand_avoid: joinList(values.brand_avoid),
  };
}

/** Produce the typed value body slice sent to create/lock endpoints. */
export function fieldsToBody(fields: CanonValueFields): CanonValueBody {
  return {
    style: fields.style.trim(),
    palette: splitList(fields.palette),
    typography: splitList(fields.typography),
    voice_id: fields.voice_id.trim(),
    voice_tone: fields.voice_tone.trim(),
    language: fields.language.trim(),
    product_name: fields.product_name.trim(),
    product_descriptors: splitList(fields.product_descriptors),
    product_claims: splitList(fields.product_claims),
    brand_tone: splitList(fields.brand_tone),
    brand_avoid: splitList(fields.brand_avoid),
  };
}

/** True when a field set carries no meaningful value (blocks empty locks). */
export function fieldsAreEmpty(fields: CanonValueFields): boolean {
  const body = fieldsToBody(fields);
  return (
    !body.style &&
    !body.voice_id &&
    !body.voice_tone &&
    !body.language &&
    !body.product_name &&
    body.palette.length === 0 &&
    body.typography.length === 0 &&
    body.product_descriptors.length === 0 &&
    body.product_claims.length === 0 &&
    body.brand_tone.length === 0 &&
    body.brand_avoid.length === 0
  );
}
