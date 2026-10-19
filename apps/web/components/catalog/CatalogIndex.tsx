import * as React from "react";
import Link from "next/link";
import {
  Image as ImageIcon,
  LayoutGrid,
  Mic,
  Music,
  Quote,
  Sparkles,
  Type,
  User,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface CatalogCategory {
  href: string;
  title: string;
  description: string;
  icon: React.ReactNode;
}

const CATEGORIES: readonly CatalogCategory[] = [
  {
    href: "/catalog/templates",
    title: "Templates",
    description:
      "Curated viral formats that pre-fill the hook, pacing, captions and audio for a new reel.",
    icon: <Sparkles className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/caption-styles",
    title: "Caption styles",
    description:
      "Karaoke caption presets with primary and highlight colours you can preview.",
    icon: <Type className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/layouts",
    title: "Layouts",
    description: "Composition layouts that arrange your footage, avatar and captions.",
    icon: <LayoutGrid className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/music",
    title: "Music",
    description: "Background-music tracks you can drop onto any reel.",
    icon: <Music className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/hooks",
    title: "Hooks",
    description: "Native opening-line hooks by language to stop the scroll.",
    icon: <Quote className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/cover-styles",
    title: "Cover styles",
    description: "Thumbnail / cover presets for the still frame that sells the click.",
    icon: <ImageIcon className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/avatars",
    title: "Avatars",
    description: "Browse presenter avatars — curated talking heads and your own photos.",
    icon: <User className="size-5" aria-hidden />,
  },
  {
    href: "/catalog/voices",
    title: "Voices",
    description: "Narrator voices with previews and language / accent labels.",
    icon: <Mic className="size-5" aria-hidden />,
  },
];

/** Landing grid linking to every browsable catalog. Presentational (server-safe). */
export function CatalogIndex() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {CATEGORIES.map((category) => (
        <li key={category.href}>
          <Link href={category.href} className="block h-full">
            <Card className="h-full transition-colors hover:border-primary/60">
              <CardContent className="flex h-full flex-col gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
                  {category.icon}
                </span>
                <div>
                  <h2 className="font-semibold leading-tight">
                    {category.title}
                  </h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {category.description}
                  </p>
                </div>
              </CardContent>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}
