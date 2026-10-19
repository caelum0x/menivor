"use client";

import Link from "next/link";
import { Coins } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

interface CreditsLinkProps {
  readonly credits?: number;
  readonly loading?: boolean;
}

/** Credit balance pill that opens the wallet (balance, activity, top-up). */
export function CreditsLink({ credits, loading = false }: CreditsLinkProps) {
  if (loading && credits === undefined) {
    return <Skeleton className="h-7 w-24 rounded-full" />;
  }
  const low = typeof credits === "number" && credits <= 0;
  return (
    <Link
      href={low ? "/wallet/plans" : "/wallet"}
      title={low ? "Out of credits — buy more" : "Credits — open wallet"}
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs transition-colors hover:border-primary/60 hover:bg-secondary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Coins className="size-3.5 text-accent" aria-hidden />
      <span className="font-medium tabular-nums">{credits ?? 0}</span>
      <span className="text-muted-foreground">{low ? "credits · top up" : "credits"}</span>
    </Link>
  );
}
