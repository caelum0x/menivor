import Link from "next/link";
import { Navbar } from "@/components/marketing/Navbar";
import { getLaunchPosture } from "@/src/shared/launch-posture/server";

/** Marketing chrome for /beta (it lives outside the (marketing) route group). */
export default async function BetaLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const posture = await getLaunchPosture();
  return (
    <div className="flex min-h-dvh flex-col">
      <Navbar launchMode={posture.mode} />
      <main className="flex-1">{children}</main>
      <footer className="border-t border-border">
        <div className="container flex flex-wrap items-center justify-between gap-4 py-8 text-sm text-muted-foreground">
          <Link href="/" className="font-display font-bold text-foreground">
            Menivor
          </Link>
          <nav className="flex gap-4">
            <Link href="/privacy" className="hover:text-foreground">Privacy</Link>
            <Link href="/terms" className="hover:text-foreground">Terms</Link>
            <Link href="/legal/acceptable-use" className="hover:text-foreground">Acceptable use</Link>
            <Link href="/contact" className="hover:text-foreground">Contact</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
