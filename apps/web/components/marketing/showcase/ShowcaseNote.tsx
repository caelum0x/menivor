import Link from "next/link";

/** How the showcase reels were made, in one honest paragraph. */
export function ShowcaseNote() {
  return (
    <div className="mx-auto max-w-[1600px] px-4 pb-14">
      <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
        How these were made: every reel above is a real render from the same pipeline you use, from a
        typed script with a neural voice and word captions. The businesses are examples filmed with
        licensed stock footage; the two reels about Menivor and Scribase are our own products, recorded
        from their live pages.{" "}
        <Link href="/styles" className="underline underline-offset-4 hover:text-foreground">
          See every style
        </Link>
        .
      </p>
    </div>
  );
}
