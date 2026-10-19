import { LOGO_PATH } from "@/lib/seo/entity";

/** Logo files shipped in public/brand (existing brand kit). */
export const LOGO_FILES: readonly { readonly label: string; readonly href: string }[] = [
  { label: "Mark, SVG", href: "/brand/menivor-mark.svg" },
  { label: "Mark, gradient SVG", href: "/brand/menivor-mark-gradient.svg" },
  { label: "Mark, PNG 512 px", href: LOGO_PATH },
  { label: "App icon, SVG", href: "/brand/menivor-app-icon.svg" },
  { label: "App icon, PNG 512 px", href: "/brand/icon-512.png" },
];

/** Reels rendered by Menivor, shipped in public/samples/showcase. */
export const SAMPLE_REELS: readonly { readonly title: string; readonly slug: string }[] = [
  { title: "Bakery morning", slug: "bakery-morning" },
  { title: "Burger point of view", slug: "burger-pov" },
  { title: "Car before and after", slug: "car-before-after" },
];
