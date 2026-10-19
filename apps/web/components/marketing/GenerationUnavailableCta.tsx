import Link from "next/link";
import { ArrowRight, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WAITLIST_ANCHOR } from "@/lib/waitlist";

/**
 * Follow-up actions for the "generation is not available for this account"
 * cards (reel Wizard, B-roll Studio). Instead of a dead end, the visitor can
 * sign up for launch updates on the landing page or see the live
 * style gallery with the sample reels.
 */
export function GenerationUnavailableCta() {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <Button asChild size="sm">
        <Link href={`/#${WAITLIST_ANCHOR}`}>
          <Mail className="size-4" aria-hidden /> Get launch updates
        </Link>
      </Button>
      <Button asChild variant="outline" size="sm">
        <Link href="/styles">
          <ArrowRight className="size-4" aria-hidden /> See sample reels
        </Link>
      </Button>
    </div>
  );
}
