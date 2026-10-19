import type { ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export interface ErrorPanelProps {
  /** Short heading (e.g. "Couldn't load the leaderboard"). */
  title: string;
  /** The specific error message from the API / network. */
  message: string;
  onRetry: () => void;
}

/** A retryable error card, matching the marketplace/insights error styling. */
export function ErrorPanel({
  title,
  message,
  onRetry,
}: Readonly<ErrorPanelProps>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">{title}</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}

export interface EmptyPanelProps {
  icon: ReactNode;
  title: string;
  description: string;
}

/** A dashed empty-state card for "nothing to show yet" surfaces. */
export function EmptyPanel({
  icon,
  title,
  description,
}: Readonly<EmptyPanelProps>) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
          {icon}
        </span>
        <div>
          <p className="font-medium">{title}</p>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </CardContent>
    </Card>
  );
}
