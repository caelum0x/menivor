import { cn } from "@/lib/utils";
import { initials } from "@/components/creators/format";

export interface CreatorAvatarProps {
  /** The creator's display name (used to derive initials). */
  name: string;
  /** The creator's handle (fallback source for initials). */
  handle: string;
  /**
   * Tailwind size + text classes for the circle (e.g. "size-16 text-xl").
   * Defaults to a compact list avatar.
   */
  className?: string;
}

/**
 * An initials-only avatar placeholder. The safe public profile carries no image,
 * so identity is rendered as the creator's initials on a tinted disc — purely
 * presentational.
 */
export function CreatorAvatar({
  name,
  handle,
  className,
}: Readonly<CreatorAvatarProps>) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex shrink-0 select-none items-center justify-center rounded-full bg-primary/10 font-semibold text-primary",
        "size-10 text-sm",
        className,
      )}
    >
      {initials(name, handle)}
    </span>
  );
}
