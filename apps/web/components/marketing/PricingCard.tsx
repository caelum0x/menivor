import Link from "next/link";
import { Check, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A single credit pack shown on the pricing page. Treated as read-only. */
export interface PricingPlan {
  readonly name: string;
  /**
   * Backend `plan_key` used at checkout (e.g. "starter"). Omitted for packs
   * that don't go through checkout (the Free tier just routes to sign-up).
   */
  readonly planKey?: string;
  /** Number of reel credits included in the pack. */
  readonly credits: number;
  /** Display price, e.g. "$0" or "$19". */
  readonly price: string;
  /** Short qualifier under the price, e.g. "forever" or "one-time". */
  readonly period: string;
  readonly description: string;
  readonly features: readonly string[];
  readonly ctaLabel: string;
  /**
   * Fallback link target used when no `onSelect` handler is provided (e.g. the
   * Free tier or the marketing page for signed-out visitors).
   */
  readonly ctaHref?: string;
  /** Visually emphasize this plan as the recommended pack. */
  readonly highlighted?: boolean;
}

interface PricingCardProps {
  readonly plan: PricingPlan;
  /**
   * When supplied, the CTA becomes a button that invokes this handler instead
   * of navigating, enabling client-side checkout. If omitted, the card renders
   * a plain `<Link>` to `plan.ctaHref`.
   */
  readonly onSelect?: (plan: PricingPlan) => void;
  /** Shows a spinner and disables the CTA while a checkout is in flight. */
  readonly pending?: boolean;
  /** Disables the CTA (e.g. while another card's checkout is running). */
  readonly disabled?: boolean;
}

/**
 * Presentational pricing card for one credit pack. Props are immutable; all
 * copy is supplied by the caller so this component stays reusable.
 */
export function PricingCard({
  plan,
  onSelect,
  pending = false,
  disabled = false,
}: PricingCardProps) {
  const variant = plan.highlighted ? "default" : "outline";

  return (
    <Card
      className={cn(
        "relative flex h-full flex-col",
        plan.highlighted &&
          "border-primary/60 bg-[linear-gradient(180deg,hsl(var(--primary)/0.08),hsl(var(--primary)/0)_45%)] shadow-[inset_0_1px_0_hsl(var(--primary)/0.25),0_28px_60px_-28px_hsl(var(--primary)/0.45)]",
      )}
    >
      {plan.highlighted ? (
        <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 border-primary/50 bg-[hsl(44_40%_11%)]">
          Good first pack
        </Badge>
      ) : null}

      <CardHeader>
        <h2 className="text-xl font-semibold leading-none tracking-tight">
          {plan.name}
        </h2>
        <CardDescription>{plan.description}</CardDescription>
        <div className="mt-4 flex items-baseline gap-1.5">
          <span className="text-4xl font-bold tracking-tight text-foreground">
            {plan.price}
          </span>
          <span className="text-sm text-muted-foreground">{plan.period}</span>
        </div>
        <p className="mt-1 text-sm font-medium text-primary">
          {plan.credits} reel credits
        </p>
      </CardHeader>

      <CardContent className="flex-1">
        <ul className="flex flex-col gap-3">
          {plan.features.map((feature) => (
            <li key={feature} className="flex items-start gap-2 text-sm">
              <Check className="mt-0.5 size-4 shrink-0 text-success" />
              <span className="text-muted-foreground">{feature}</span>
            </li>
          ))}
        </ul>
      </CardContent>

      <CardFooter>
        {onSelect ? (
          <Button
            className="w-full"
            size="lg"
            variant={variant}
            disabled={pending || disabled}
            aria-busy={pending}
            onClick={() => onSelect(plan)}
          >
            {pending ? (
              <>
                <Loader2 className="animate-spin" aria-hidden />
                Redirecting…
              </>
            ) : (
              plan.ctaLabel
            )}
          </Button>
        ) : (
          <Button asChild className="w-full" size="lg" variant={variant}>
            <Link href={plan.ctaHref ?? "/sign-up"}>{plan.ctaLabel}</Link>
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
