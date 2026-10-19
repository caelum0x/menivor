import * as React from "react";
import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "success"
  | "destructive";

const VARIANTS: Record<BadgeVariant, string> = {
  default: "border-primary/25 bg-primary/[0.14] text-primary",
  secondary: "border-white/10 bg-white/[0.06] text-secondary-foreground",
  outline: "border-white/[0.14] bg-white/[0.03] text-foreground",
  success: "border-success/25 bg-success/[0.14] text-success",
  destructive: "border-destructive/30 bg-destructive/[0.14] text-destructive",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
