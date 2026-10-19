"use client";

import { cn } from "@/lib/utils";
import {
  PAYMENT_PROVIDERS,
  type PaymentProvider,
} from "@/lib/types";

/** Human-readable label + hint for each supported payment provider. */
const PROVIDER_META: Record<PaymentProvider, { label: string; hint: string }> = {
  stripe: { label: "Stripe", hint: "Cards worldwide" },
  iyzico: { label: "iyzico", hint: "For Turkey (TR)" },
  creem: { label: "Creem", hint: "Global cards & wallets, tax handled" },
  polar: { label: "Polar", hint: "Global cards & wallets, tax handled" },
  dodo: { label: "Dodo Payments", hint: "Global cards & wallets, tax handled" },
  paddle: { label: "Paddle", hint: "Global cards & wallets, tax handled" },
};

interface ProviderToggleProps {
  readonly value: PaymentProvider;
  readonly onChange: (provider: PaymentProvider) => void;
  readonly disabled?: boolean;
  /**
   * The providers to render, in order. Defaults to every known provider; pass
   * the ENABLED subset from `GET /billing/providers` to show only configured
   * options.
   */
  readonly providers?: readonly PaymentProvider[];
}

/**
 * Segmented toggle for choosing the checkout payment provider. Presentational
 * and controlled by the parent so the choice can drive the checkout request.
 */
export function ProviderToggle({
  value,
  onChange,
  disabled = false,
  providers = PAYMENT_PROVIDERS,
}: ProviderToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Payment provider"
      className="neu-inset inline-flex items-center gap-1 rounded-xl p-1"
    >
      {providers.map((provider) => {
        const active = provider === value;
        const meta = PROVIDER_META[provider];
        return (
          <button
            key={provider}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            title={meta.hint}
            onClick={() => onChange(provider)}
            className={cn(
              "press-sink rounded-lg border border-transparent px-4 py-1.5 text-sm font-medium",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              "disabled:cursor-not-allowed disabled:opacity-50",
              active
                ? "neu-raised text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}
