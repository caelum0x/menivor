"use client";

import * as React from "react";
import { Info, Lightbulb } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { WinExplanation } from "./types";

export interface WhyItWonProps {
  explanation: WinExplanation | null;
  earlyRead: boolean;
  hasWinner: boolean;
}

/** Plain-language "why it won": metric comparisons, what differed, and caveats. */
export function WhyItWon({ explanation, earlyRead, hasWinner }: Readonly<WhyItWonProps>) {
  const title = hasWinner ? "Why it won" : "Current leader";
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Lightbulb className="size-4" aria-hidden /> {title}
          </span>
          {explanation && explanation.confidence !== "none" && (
            <Badge variant={explanation.confidence === "high" ? "success" : "secondary"}>
              {explanation.confidence === "high" ? "High confidence" : "Low confidence"}
            </Badge>
          )}
        </CardTitle>
        {earlyRead && !hasWinner && (
          <p className="text-xs text-muted-foreground">
            Early read: the check window has not closed, so this can still change.
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {!explanation ? (
          <p className="text-muted-foreground">
            The explanation appears after the first metrics check, once at least two variants
            have been live for the check window.
          </p>
        ) : (
          <>
            <p className="font-medium">{explanation.headline}</p>
            {explanation.reasons.length > 1 && (
              <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                {explanation.reasons.slice(1).map((reason) => (
                  <li key={reason.metric}>{reason.text}</li>
                ))}
              </ul>
            )}
            {explanation.differences.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  What was different
                </p>
                <ul className="space-y-2">
                  {explanation.differences.map((diff) => (
                    <li key={diff.aspect} className="rounded-md bg-secondary/40 p-2">
                      <p>{diff.text}</p>
                      {diff.aspect === "hook" && (
                        <div className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                          <p>
                            <span className="font-medium text-foreground">Winner:</span> {diff.winner}
                          </p>
                          {diff.others.map((other) => (
                            <p key={other}>
                              <span className="font-medium">Other:</span> {other}
                            </p>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {explanation.caveats.length > 0 && (
              <ul className="space-y-1 text-xs text-muted-foreground">
                {explanation.caveats.map((caveat) => (
                  <li key={caveat} className="flex items-start gap-1.5">
                    <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {caveat}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
