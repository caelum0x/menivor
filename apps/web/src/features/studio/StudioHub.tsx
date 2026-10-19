"use client";

import * as React from "react";
import {
  Boxes,
  Briefcase,
  Captions,
  Clapperboard,
  Code2,
  Cpu,
  Film,
  Flame,
  FolderOpen,
  Hash,
  Images,
  KeyRound,
  Languages,
  Link2,
  LayoutTemplate,
  Megaphone,
  Mic,
  Music,
  Palette,
  Radio,
  Scissors,
  Send,
  ShieldCheck,
  Sparkles,
  SquareScissors,
  SquareUserRound,
  TrendingUp,
  Type,
  Users,
  Wand2,
} from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

interface HubItem {
  href: string;
  title: string;
  blurb: string;
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
}

const ITEMS: HubItem[] = [
  { href: "/projects", title: "Projects", blurb: "Everything you have made — reels, edits, and AI clips — with edit and publish one click away.", Icon: FolderOpen },
  { href: "/create/templates", title: "Genre templates", blurb: "One-tap viral formats — Minecraft split, ASMR loop, movie recap.", Icon: Sparkles },
  { href: "/characters", title: "Characters", blurb: "Save an identity-locked character and reuse it across episodes.", Icon: Users },
  { href: "/film", title: "AI film planner", blurb: "Turn a beat sheet into a character-consistent multi-shot film.", Icon: Clapperboard },
  { href: "/editor?job=", title: "Timeline editor", blurb: "Trim, reorder, caption & overlay a finished reel into a new non-destructive export.", Icon: Scissors },
  { href: "/blueprints", title: "Shot blueprints", blurb: "The hook → rising → payoff → loop structures the renderer composes against, per genre.", Icon: LayoutTemplate },
  { href: "/captions", title: "Caption styles", blurb: "Preview the burned-in caption presets — Hormozi, karaoke, brainrot pop-in — before you render.", Icon: Type },
  { href: "/model-governance", title: "Model governance", blurb: "See each model's license class + lifecycle — which can back a paid render, and which are sunsetting.", Icon: ShieldCheck },
  { href: "/media/playground", title: "Media gateway", blurb: "One key + one balance → any image or video model. Kling, Veo, Runway, Luma, more.", Icon: Wand2 },
  { href: "/render", title: "AI video render", blurb: "Render a text-to-video shot on GPU — capped spend, charged only when it completes.", Icon: Cpu },
  { href: "/discover", title: "Discover", blurb: "Trending sounds, hashtags, and viral templates ranked by opportunity — build before the wave peaks.", Icon: TrendingUp },
  { href: "/discover/sounds", title: "Trending sounds", blurb: "Sounds ranked by opportunity + saturation — attach the right audio before the wave peaks.", Icon: Music },
  { href: "/discover/hashtags", title: "Trending hashtags", blurb: "Rising hashtags with velocity and saturation signals — ride the tag while it still reaches.", Icon: Hash },
  { href: "/discover/creators", title: "Rising formats", blurb: "Format-kind trends plus the full viral template gallery — spot the shape that's breaking out.", Icon: Flame },
  { href: "/trends", title: "Trends explorer", blurb: "The live ranked trend feed, plus a ranker for counts you track yourself.", Icon: TrendingUp },
  { href: "/models", title: "Model catalog", blurb: "Every generation model by capability, with price and provider, ready to pick for a render.", Icon: Boxes },
  { href: "/studio/voices", title: "Voice catalog", blurb: "Every narrator voice + lipsync provider — preview and pre-select one straight into a new reel.", Icon: Mic },
  { href: "/studio/avatars", title: "Avatars & characters", blurb: "Avatar presets, the live HeyGen catalog, and your identity-locked characters in one gallery.", Icon: SquareUserRound },
  { href: "/broll-library", title: "B-roll library", blurb: "Browse, filter, and reuse your AI B-roll clips — drop one into a reel or launch a new generation.", Icon: Film },
  { href: "/studio/captions", title: "Caption safe zones", blurb: "Per-platform font size, margin, and safe-zone position for burned-in captions before you render.", Icon: Captions },
  { href: "/studio/dub", title: "Dub a video", blurb: "Upload a video and get it back in another language, with a new voice track and subtitle files. Free voices by default.", Icon: Languages },
  { href: "/studio/clips", title: "Auto-clip jobs", blurb: "Turn long uploads into ranked short clips, then promote the best cut into a reel draft.", Icon: SquareScissors },
  { href: "/showcase", title: "Showcase", blurb: "The public template gallery plus your completed reels — proof of what the pipeline ships.", Icon: Images },
  { href: "/api-docs", title: "API reference", blurb: "The real generation endpoints — params, auth, cURL, and response shapes for building on Menivor.", Icon: Code2 },
  { href: "/clipmarket", title: "Clip marketplace", blurb: "Post a CPM campaign or earn on verified views.", Icon: Megaphone },
  { href: "/publish", title: "Native publish", blurb: "Post a finished reel straight to a connected platform.", Icon: Send },
  { href: "/channels", title: "Channel console", blurb: "Connected accounts, the posting queue, and A/B experiments per channel.", Icon: Radio },
  { href: "/import", title: "Import from a URL", blurb: "Paste a product or article link and get a hook-first reel draft to carry into the wizard.", Icon: Link2 },
  { href: "/presets", title: "Brand kits", blurb: "Save your favourite avatar, voice, layout, caption, and music combos to pre-fill every new reel.", Icon: Palette },
  { href: "/agency", title: "Agency", blurb: "Run a client roster: per-client credit pools, white-label watermark, client keys, and revenue in one place.", Icon: Briefcase },
  { href: "/gateway", title: "API gateway", blurb: "Mint your own resale API keys, each with a daily spend cap and markup, billed only on success.", Icon: KeyRound },
];

/** Studio hub — a single navigational surface for the creation + growth tools. */
export function StudioHub() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {ITEMS.map(({ href, title, blurb, Icon }) => (
        <a key={href} href={href} className="group block focus:outline-none">
          <Card className="h-full transition-colors group-hover:border-primary">
            <CardContent className="flex h-full flex-col gap-2 py-5">
              <div className="flex items-center gap-2">
                <Icon className="h-5 w-5 text-primary" aria-hidden />
                <h3 className="font-semibold">{title}</h3>
              </div>
              <p className="flex-1 text-sm text-muted-foreground">{blurb}</p>
              <span className="text-sm text-primary group-hover:underline">Open →</span>
            </CardContent>
          </Card>
        </a>
      ))}
    </div>
  );
}
