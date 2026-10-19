import Link from "next/link";

interface AupNoticeProps {
  readonly className?: string;
}

/**
 * One quiet line shown on every generate surface: generating means agreeing
 * to the Acceptable Use Policy (prompts are moderated before generation).
 */
export function AupNotice({ className }: AupNoticeProps) {
  return (
    <p className={className ?? "text-center text-xs text-muted-foreground"}>
      By generating you agree to our{" "}
      <Link href="/legal/acceptable-use" className="underline underline-offset-4">
        Acceptable Use Policy
      </Link>
      . Prompts are checked automatically; blocked ones are never charged.
    </p>
  );
}
