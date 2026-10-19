/**
 * The /pricing headline sits directly above the monthly plans and the credit
 * packs, so it has to name both offers (DISTRIBUTION-WAVE funnel fix). It
 * used to read "Pay per reel, not per month" above a monthly plan.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { en } from "@/lib/i18n/dictionaries/en";
import { es } from "@/lib/i18n/dictionaries/es";
import { tr } from "@/lib/i18n/dictionaries/tr";

const NOT_MONTHLY = /not per month|no (?:por|al) mes|aylık değil|no subscription|sin suscripción|abonelik yok/i;

describe("/pricing headline", () => {
  it("the page renders monthly plans next to the packs", () => {
    const checkout = fs.readFileSync(path.join(__dirname, "PricingCheckout.tsx"), "utf8");
    expect(checkout).toMatch(/<MonthlyPlans\b/);
  });

  for (const [locale, messages] of [["en", en], ["es", es], ["tr", tr]] as const) {
    it(`${locale}: names both offers and never denies the monthly plan`, () => {
      const { title, intro } = messages.pricing;
      expect(title).not.toMatch(NOT_MONTHLY);
      expect(intro).not.toMatch(NOT_MONTHLY);
      expect(`${title} ${intro}`).toMatch(/month|mes|aylık|ay\b/i);
      expect(`${title} ${intro}`).toMatch(/pack|paket/i);
    });
  }

  it("the per-reel billing explainer matches", () => {
    const features = fs.readFileSync(path.resolve(__dirname, "../../../lib/seo/features.ts"), "utf8");
    expect(features).not.toMatch(NOT_MONTHLY);
  });
});
