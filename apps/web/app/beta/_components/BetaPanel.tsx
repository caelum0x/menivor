"use client";

import Link from "next/link";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBetaLaunchStatus } from "../_lib/use-launch-status";
import { AvailableFormats } from "./AvailableFormats";
import { BetaRequestForm } from "./BetaRequestForm";

/**
 * /beta body. Reads the live launch phase: during the private beta it shows
 * the request form next to the formats that work today; once the server
 * reports public access it points straight at free signup instead.
 */
export function BetaPanel() {
  const { status, loading, failed } = useBetaLaunchStatus();

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Checking beta status
      </p>
    );
  }

  if (status?.phase === "public") {
    return (
      <div className="space-y-4">
        <p className="text-muted-foreground">
          Menivor is open to everyone now, no request needed.
        </p>
        <Button asChild size="lg">
          <Link href="/sign-up">
            Start free <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,360px)]">
      <BetaRequestForm source="beta-page" />
      <aside className="border-t border-border pt-8 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
        {status ? (
          <AvailableFormats formats={status.availableFormats} />
        ) : failed ? (
          <p className="text-sm text-muted-foreground">
            We could not load which formats are live right now. Your request still goes through.
          </p>
        ) : null}
      </aside>
    </div>
  );
}
