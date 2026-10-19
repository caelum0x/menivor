import { getTranslations } from "@/lib/i18n/server";
import type { TranslationKey } from "@/lib/i18n/translator";

interface Step {
  readonly number: string;
  readonly labelKey: TranslationKey;
  readonly titleKey: TranslationKey;
  readonly bodyKey: TranslationKey;
}

/**
 * The real pipeline, stage by stage. Every claim here maps to a shipped
 * component of the monorepo: the desktop recorder (openscreen), the script /
 * voice / avatar / caption stages (provider adapters + caption engine), and
 * the 9:16 render + publishing connectors.
 */
const STEPS: readonly Step[] = [
  {
    number: "01",
    labelKey: "landing.step1Label",
    titleKey: "landing.step1Title",
    bodyKey: "landing.step1Body",
  },
  {
    number: "02",
    labelKey: "landing.step2Label",
    titleKey: "landing.step2Title",
    bodyKey: "landing.step2Body",
  },
  {
    number: "03",
    labelKey: "landing.step3Label",
    titleKey: "landing.step3Title",
    bodyKey: "landing.step3Body",
  },
];

/**
 * Numbered pipeline rail for the landing page: ruled columns with timecode
 * kickers instead of icon cards. Anchored at #how-it-works.
 */
export async function HowItWorks() {
  const t = await getTranslations();
  return (
    <section id="how-it-works" className="scroll-mt-20 border-b border-border">
      <div className="container py-20">
        <div className="mb-12 max-w-2xl">
          <p className="kicker text-muted-foreground">{t("landing.howKicker")}</p>
          <h2 className="mt-4 text-display font-bold">{t("landing.howTitle")}</h2>
        </div>

        <ol className="grid gap-x-10 gap-y-10 md:grid-cols-3">
          {STEPS.map((step) => (
            <li key={step.number} className="border-t border-border pt-6">
              <p className="kicker">
                <span className="text-primary">{step.number}</span>
                <span className="text-muted-foreground"> / {t(step.labelKey)}</span>
              </p>
              <h3 className="mt-4 text-lg font-semibold text-foreground">
                {t(step.titleKey)}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {t(step.bodyKey)}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
