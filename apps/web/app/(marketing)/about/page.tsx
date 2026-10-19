import type { Metadata } from "next";
import Link from "next/link";
import {
  ENTITY_DESCRIPTION,
  PRESS_DESCRIPTION_LONG,
  SUPPORT_EMAIL,
} from "@/lib/seo/entity";
import { PRODUCT_FAMILY } from "./family";

export const metadata: Metadata = {
  title: "About Menivor",
  description: ENTITY_DESCRIPTION,
  alternates: { canonical: "/about" },
};

export default function AboutPage() {
  return (
    <div className="container py-16 lg:py-24">
      <div className="max-w-3xl">
        <p className="kicker text-muted-foreground">About</p>
        <h1 className="mt-4 text-display-lg font-bold">About Menivor</h1>
        <p className="mt-4 text-pretty text-lg leading-relaxed text-muted-foreground">
          {PRESS_DESCRIPTION_LONG}
        </p>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">How to say it</h2>
          <p className="text-muted-foreground">Menivor is pronounced MEN-ih-vor.</p>
        </section>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">The product family</h2>
          <ul className="space-y-2 text-muted-foreground">
            {PRODUCT_FAMILY.map((product) => (
              <li key={product.name}>
                <a
                  href={product.url}
                  className="font-medium text-primary underline underline-offset-4"
                >
                  {product.name}
                </a>
                : {product.what}.
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-12 space-y-3">
          <h2 className="text-2xl font-semibold">Contact</h2>
          <p className="text-muted-foreground">
            Email{" "}
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="font-medium text-primary underline underline-offset-4"
            >
              {SUPPORT_EMAIL}
            </a>
            , or see the{" "}
            <Link href="/contact" className="font-medium text-primary underline underline-offset-4">
              contact page
            </Link>{" "}
            and the{" "}
            <Link href="/press" className="font-medium text-primary underline underline-offset-4">
              press kit
            </Link>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
