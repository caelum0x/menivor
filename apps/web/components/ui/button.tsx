import * as React from "react";
import { cn } from "@/lib/utils";

export type ButtonVariant =
  | "default"
  | "secondary"
  | "outline"
  | "ghost"
  | "destructive"
  | "link";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<ButtonVariant, string> = {
  // Raised brand-yellow CTA: soft neumorphic depth, sinks on press.
  default: "neu-primary text-primary-foreground focus-visible:ring-primary",
  secondary:
    "neu-raised text-secondary-foreground hover:brightness-110 focus-visible:ring-ring",
  // Glass pill: translucent fill + hairline, no blur (cheap in lists).
  outline:
    "border border-white/[0.12] bg-white/[0.04] shadow-[inset_0_1px_0_hsl(0_0%_100%/0.06)] hover:border-white/20 hover:bg-white/[0.08] focus-visible:ring-ring",
  ghost: "bg-transparent hover:bg-white/[0.06] focus-visible:ring-ring",
  destructive:
    "bg-destructive text-destructive-foreground shadow-[inset_0_1px_0_hsl(0_0%_100%/0.2),0_8px_20px_-10px_hsl(0_72%_55%/0.6)] hover:bg-destructive/90 focus-visible:ring-destructive",
  link: "bg-transparent text-primary underline-offset-4 hover:underline focus-visible:ring-ring",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
  icon: "h-10 w-10",
};

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /**
   * Render the button's styles onto the single child element instead of a
   * `<button>` (e.g. to style a Next.js `<Link>`). Minimal Radix-Slot-style
   * behavior without the dependency.
   */
  asChild?: boolean;
}

/**
 * Primary action button. Composes a variant + size into Tailwind classes.
 * Props are treated as read-only (immutable) and spread through unchanged.
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = "default", size = "md", type, asChild = false, children, ...props },
    ref,
  ) => {
    const classes = cn(
      "press-sink inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      "disabled:pointer-events-none disabled:opacity-50",
      "[&_svg]:size-4 [&_svg]:shrink-0",
      VARIANTS[variant],
      SIZES[size],
      className,
    );

    if (asChild && React.isValidElement(children)) {
      const child = children as React.ReactElement<{ className?: string }>;
      return React.cloneElement(child, {
        className: cn(classes, child.props.className),
      });
    }

    return (
      <button ref={ref} type={type ?? "button"} className={classes} {...props}>
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
