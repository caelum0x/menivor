"use client";

import * as React from "react";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export interface ErrorPanelProps {
  title?: string;
  message: string;
  onRetry: () => void;
}

/** Consistent error surface with a retry affordance. */
export function ErrorPanel({
  title = "Something went wrong",
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

export interface EmptyStateProps {
  title: string;
  message: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

/** Consistent empty surface for a catalog with no results. */
export function EmptyState({
  title,
  message,
  icon,
  action,
}: Readonly<EmptyStateProps>) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          {icon ?? <Inbox className="size-6" aria-hidden />}
        </span>
        <div>
          <p className="font-medium">{title}</p>
          <p className="mx-auto max-w-sm text-sm text-muted-foreground">
            {message}
          </p>
        </div>
        {action}
      </CardContent>
    </Card>
  );
}

export interface CardGridSkeletonProps {
  count?: number;
  /** Height of each skeleton card body. */
  lines?: number;
}

/** Grid of placeholder cards shown while a catalog loads. */
export function CardGridSkeleton({
  count = 8,
  lines = 2,
}: Readonly<CardGridSkeletonProps>) {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, i) => (
        <li key={i}>
          <Card>
            <CardContent className="space-y-3 p-5">
              <Skeleton className="h-5 w-2/3" />
              {Array.from({ length: lines }).map((__, j) => (
                <Skeleton key={j} className="h-4 w-full" />
              ))}
              <Skeleton className="h-4 w-1/3" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
