/**
 * Data-driven navigation registry.
 *
 * Screens self-register their metadata here. The "Me" hub and any RegistryMenu
 * render from this data, so adding a new screen to the registry automatically
 * surfaces it in the UI without touching _layout.tsx or the tab layouts.
 *
 * How to register a screen:
 * 1. Call `registerScreen({ route, title, group, order, subtitle })` at module
 *    top-level (not inside a component).
 * 2. The screen will appear in `getRegistryGroups()` and in `<RegistryMenu />`.
 * 3. _layout.tsx does NOT need a new <Stack.Screen> for the registration to
 *    work — expo-router auto-discovers files under app/. Add a Stack.Screen
 *    only when you need a custom header title or presentation style.
 *
 * Group ordering convention:
 *   1  Core            — create, studio tools
 *   2  Content         — publishing, calendar, trends
 *   3  Analytics       — analytics, performance, leaderboard
 *   4  Monetize        — wallet, marketplace, clipmarket
 *   5  Workspace       — team, connections, developer
 *   6  Settings        — account, privacy, support
 *   7  Admin           — platform-staff surfaces (audience "staff")
 *   99 Labs            — experimental features
 *
 * Example:
 * ```ts
 * // At the top of lib/ideas.ts or app/ideas.tsx:
 * import { registerScreen } from "@/lib/nav/registry";
 * registerScreen({
 *   route: "/ideas",
 *   title: "Spark · Idea Engine",
 *   subtitle: "Turn your app into ready-to-shoot viral concepts",
 *   group: "Core",
 *   groupOrder: 1,
 *   order: 10,
 * });
 * ```
 */

import { isRouteAvailable } from "@/src/shared/release/surface";

/** A registered screen's metadata. */
export interface ScreenMeta {
  /** Expo-router path, e.g. "/ideas" */
  route: string;
  /** Short display title */
  title: string;
  /** One-line description shown under the title in menus */
  subtitle?: string;
  /** Display group name, e.g. "Core", "Analytics" */
  group: string;
  /** Sort key for groups (lower = higher in the list) */
  groupOrder?: number;
  /** Sort key within the group (lower = first) */
  order?: number;
  /** Whether the item is hidden from navigation menus (e.g. internal-only) */
  hidden?: boolean;
  /**
   * Extra search terms (synonyms, aliases) that should match this screen in the
   * navigation hub search but do not need to appear in the title/subtitle.
   */
  keywords?: readonly string[];
  /**
   * "staff" screens are platform-operator surfaces (admin console, model
   * governance, internal kernels). They are listed only for accounts the server
   * confirms as staff (see usePlatformAdmin) and never in a consumer's menus.
   */
  audience?: "everyone" | "staff";
}

/** Menu visibility options for registry reads. */
export interface RegistryViewOptions {
  /** Include staff-only screens (only when the server confirmed staff). */
  includeStaff?: boolean;
}

/** Ordered group of screen entries. */
export interface ScreenGroup {
  name: string;
  order: number;
  screens: ScreenMeta[];
}

// ---------------------------------------------------------------------------
// Registry store (module-level singleton; never mutated externally)
// ---------------------------------------------------------------------------

const _registry = new Map<string, ScreenMeta>();

/**
 * Register a screen. Calling this multiple times for the same route overwrites
 * the previous entry (safe to call in hot-reload environments).
 */
export function registerScreen(meta: ScreenMeta): void {
  _registry.set(meta.route, { ...meta });
}

/** Return all non-hidden registered screens visible to this audience. */
export function getRegisteredScreens(
  options: RegistryViewOptions = {},
): readonly ScreenMeta[] {
  return Array.from(_registry.values()).filter(
    (s) =>
      !s.hidden &&
      (options.includeStaff === true || s.audience !== "staff") &&
      // Store builds list only the release surface (see src/shared/release).
      isRouteAvailable(s.route),
  );
}

/** Return screens organised into sorted groups. */
export function getRegistryGroups(
  options: RegistryViewOptions = {},
): readonly ScreenGroup[] {
  const screens = getRegisteredScreens(options);

  const groupMap = new Map<string, ScreenGroup>();
  for (const screen of screens) {
    const key = screen.group;
    if (!groupMap.has(key)) {
      groupMap.set(key, { name: key, order: screen.groupOrder ?? 50, screens: [] });
    }
    groupMap.get(key)!.screens.push(screen);
  }

  // Sort screens within each group by `order`, then title
  for (const group of groupMap.values()) {
    group.screens.sort((a, b) => {
      const orderDiff = (a.order ?? 50) - (b.order ?? 50);
      return orderDiff !== 0 ? orderDiff : a.title.localeCompare(b.title);
    });
  }

  // Sort groups by groupOrder, then name
  return Array.from(groupMap.values()).sort((a, b) => {
    const diff = a.order - b.order;
    return diff !== 0 ? diff : a.name.localeCompare(b.name);
  });
}

/** Look up a single screen by route. */
export function getScreen(route: string): ScreenMeta | undefined {
  return _registry.get(route);
}

// ---------------------------------------------------------------------------
// Pre-register the existing ~90 app screens so the registry is populated
// without modifying every existing screen file. New screens register themselves.
// ---------------------------------------------------------------------------

const SOCIAL_SIGN_IN_CONFIGURED =
  (process.env.EXPO_PUBLIC_SUPABASE_URL?.trim() ?? "").length > 0 &&
  (process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY?.trim() ?? "").length > 0;

const EXISTING_SCREENS: readonly ScreenMeta[] = [
  // Core — create
  { route: "/create/advanced", title: "Full Reel Editor", subtitle: "Screen recording, custom script, music, captions, variants and workspace billing", group: "Core", groupOrder: 1, order: 0.5, keywords: ["advanced", "wizard", "recording", "script", "music"] },
  { route: "/ad-studio", title: "Ad Studio", subtitle: "Paste a product link, get ad angles, render showcase, before/after and avatar ads", group: "Core", groupOrder: 1, order: 0.6, keywords: ["ads", "product", "ugc", "shopify", "amazon", "trendyol", "ecommerce", "marketing"] },
  { route: "/compose", title: "Reel Compose", subtitle: "Template-first authoring — browse, generate, review", group: "Core", groupOrder: 1, order: 1 },
  { route: "/brand", title: "Brand Watermark", subtitle: "Overlay your logo on every reel at a chosen corner and opacity", group: "Core", groupOrder: 1, order: 5 },
  { route: "/characters", title: "Characters", subtitle: "Save an identity-locked character and reuse it across episodes", group: "Core", groupOrder: 1, order: 6 },
  { route: "/ideas", title: "Spark · Idea Engine", subtitle: "Turn your app into ready-to-shoot viral concepts", group: "Core", groupOrder: 1, order: 7 },
  { route: "/film", title: "Film Studio", subtitle: "Plan a character-consistent multi-shot film, render every shot, export one video", group: "Core", groupOrder: 1, order: 8 },
  { route: "/render", title: "GPU Render", subtitle: "Start a model render — charged only when it completes", group: "Core", groupOrder: 1, order: 9 },
  { route: "/capture", title: "Capture & Import", subtitle: "Import footage, trim & export, or start from a template", group: "Core", groupOrder: 1, order: 10 },
  { route: "/editor", title: "Timeline Editor", subtitle: "Pick a finished reel, then trim, reorder, caption & overlay it into a new export", group: "Core", groupOrder: 1, order: 11 },
  { route: "/speak-studio", title: "Speak Studio", subtitle: "Live voice transcription and TTS preview", group: "Core", groupOrder: 1, order: 12 },
  { route: "/media-gateway", title: "Media Gateway", subtitle: "One key + one balance → any image or video model", group: "Core", groupOrder: 1, order: 13 },
  { route: "/library", title: "Library & Studio", subtitle: "Catalog, studio galleries, wallet, insights and account in one hub", group: "Core", groupOrder: 1, order: 14 },
  { route: "/catalog/model-catalog", title: "Model Catalog", subtitle: "Compare reviewed models by price, latency and provider health", group: "Core", groupOrder: 1, order: 15, keywords: ["models", "model gallery", "providers", "compare", "price"] },
  { route: "/catalog", title: "Content Catalog", subtitle: "Models, presets, caption styles, music, layouts, templates and more", group: "Core", groupOrder: 1, order: 15 },
  { route: "/studio/captions", title: "Caption Studio", subtitle: "Hook score, punch captions, safe zones, loop check, beat fit & SEO", group: "Core", groupOrder: 1, order: 16 },
  { route: "/studio/characters/canon", title: "Character Canon", subtitle: "Lock canonical brand/character identities and version them", group: "Core", groupOrder: 1, order: 17 },
  { route: "/studio/motion", title: "Motion Presets", subtitle: "The versioned camera-move catalog you can compile onto a reel", group: "Core", groupOrder: 1, order: 18 },
  { route: "/studio/templates", title: "Template Studio", subtitle: "Browse compile-ready reel templates and preview them before you build", group: "Core", groupOrder: 1, order: 19 },
  { route: "/studio/scripts", title: "Script Studio", subtitle: "Generate, edit and save narration scripts to reuse across your reels", group: "Core", groupOrder: 1, order: 20 },
  { route: "/account/voices", title: "Brand Voices", subtitle: "Clone your voice into a private narrator, preview samples and manage them", group: "Core", groupOrder: 1, order: 21 },
  { route: "/account/avatars", title: "Custom Avatars", subtitle: "Turn a selfie into a talking-photo avatar, preview it and run a lip-sync test", group: "Core", groupOrder: 1, order: 22 },
  { route: "/jobs/reels/tasks", title: "Task Queue", subtitle: "Live async tasks — watch running jobs and batches, inspect or cancel one", group: "Core", groupOrder: 1, order: 23 },
  { route: "/catalog/studio", title: "Stock Libraries", subtitle: "Uploadable music and video-material stores the render pipeline draws from", group: "Core", groupOrder: 1, order: 24, keywords: ["stock", "bgm", "background music", "materials", "footage", "upload", "assets"] },
  { route: "/studio/design", title: "Design Studio", subtitle: "Static posts, stories and banners in your brand: layouts, text edits, exported PNGs", group: "Core", groupOrder: 1, order: 25, keywords: ["design", "post", "banner", "story", "carousel", "png", "brand kit"] },
  { route: "/studio/dub", title: "Dub a Video", subtitle: "Dub any uploaded video into another language with subtitle files, free voices by default", group: "Core", groupOrder: 1, order: 26, keywords: ["dub", "translate", "language", "subtitles", "voice"] },

  // Content — publishing
  { route: "/connections/publish", title: "Publish a Reel", subtitle: "Post a finished reel straight to a connected platform", group: "Content", groupOrder: 2, order: 1 },
  { route: "/scheduled", title: "Scheduled Publishes", subtitle: "Review and cancel reels queued to auto-publish", group: "Content", groupOrder: 2, order: 3 },
  { route: "/uploads", title: "Uploads", subtitle: "Your uploaded clips, images and audio — preview, reuse in Create, delete", group: "Content", groupOrder: 2, order: 4 },
  { route: "/inbox", title: "Social Inbox", subtitle: "Comments and messages on your published posts: read, reply where allowed, mark done", group: "Content", groupOrder: 2, order: 4.5, keywords: ["inbox", "comments", "messages", "dm", "reply", "engagement"] },
  { route: "/calendar", title: "Publishing Calendar", subtitle: "See your scheduled and published reels by day, and reschedule", group: "Content", groupOrder: 2, order: 4 },
  { route: "/calendar/channels", title: "Channels", subtitle: "Connect Telegram, Discord and Mastodon, post now or schedule, and see the queue", group: "Content", groupOrder: 2, order: 4.2, keywords: ["telegram", "discord", "mastodon", "channel", "queue"] },
  { route: "/approvals", title: "Approvals", subtitle: "Approve, edit or reject reply drafts, held posts and budget changes", group: "Content", groupOrder: 2, order: 0.5, keywords: ["approve", "reject", "review", "held", "drafts", "comment"] },
  { route: "/clipfarm-console", title: "Clipfarm Console", subtitle: "Point the unattended runner at a channel — runs, pacing & schedule", group: "Content", groupOrder: 2, order: 5 },
  { route: "/trends-feed", title: "Trends", subtitle: "Ranked, recommended sounds — score your own series and observe the ones you build to", group: "Content", groupOrder: 2, order: 7 },
  { route: "/repurpose/clipping", title: "Content Engine", subtitle: "Turn a long recording or a URL into AI-scored vertical shorts", group: "Content", groupOrder: 2, order: 8 },
  { route: "/catalog/trend-pull", title: "Pull Trends", subtitle: "Trigger a ToS-gated trend scrape on demand and watch it land in your feed", group: "Content", groupOrder: 2, order: 9 },

  // Analytics
  { route: "/analytics", title: "Creator Dashboard", subtitle: "Funnel, spend, render times and usage breakdowns over time", group: "Analytics", groupOrder: 3, order: 1 },
  { route: "/insights", title: "Insights", subtitle: "Lifetime totals, referral program, presets and winning templates", group: "Analytics", groupOrder: 3, order: 1.5 },
  { route: "/insights/winners", title: "Winners & Remake Loop", subtitle: "See which hook variant won, why, and remake the winner as 3 new variants", group: "Analytics", groupOrder: 3, order: 1.6, keywords: ["winner", "loop", "remake", "a/b", "hooks", "variants", "ranking"] },
  { route: "/performance", title: "Hook Performance", subtitle: "Log how your reels performed and see your winning hooks", group: "Analytics", groupOrder: 3, order: 2 },
  { route: "/leaderboard", title: "Creator Leaderboard", subtitle: "See the top creators ranked by reputation, clones and win-score", group: "Analytics", groupOrder: 3, order: 3 },
  { route: "/experiments", title: "Hook A/B Experiments", subtitle: "Test several hooks on one reel body and see which variant retains best", group: "Analytics", groupOrder: 3, order: 4, keywords: ["ab", "a/b", "split test", "hooks", "variants"] },

  // Monetize
  { route: "/marketplace", title: "Template Marketplace", subtitle: "Browse, clone and rate templates published by other creators", group: "Monetize", groupOrder: 4, order: 1 },
  { route: "/clipmarket", title: "Clip Marketplace", subtitle: "Post a CPM campaign or earn on verified views", group: "Monetize", groupOrder: 4, order: 2 },
  { route: "/wallet", title: "Wallet", subtitle: "See your USD balance and ledger activity, and top up credit", group: "Monetize", groupOrder: 4, order: 3 },
  { route: "/wallet/plans", title: "Plan & Usage", subtitle: "See your workspace plan, entitlements and usage, and upgrade", group: "Monetize", groupOrder: 4, order: 4 },
  { route: "/spend", title: "Spend", subtitle: "Detailed credit spend breakdown", group: "Monetize", groupOrder: 4, order: 6 },

  // Workspace
  { route: "/account/workspaces", title: "Team & Workspaces", subtitle: "Switch the active workspace, invite teammates, and manage members", group: "Workspace", groupOrder: 5, order: 1 },
  { route: "/account/workspaces/roles", title: "Team Roles & Permissions", subtitle: "See your access, review member roles, and read the audit trail", group: "Workspace", groupOrder: 5, order: 2 },
  { route: "/sso", title: "Enterprise SSO", subtitle: "Configure single sign-on and review your workspace security policy", group: "Workspace", groupOrder: 5, order: 3 },
  { route: "/connections/manage", title: "Connections", subtitle: "Connect TikTok, Instagram and YouTube to publish reels directly", group: "Workspace", groupOrder: 5, order: 4 },
  { route: "/account/developer-keys", title: "Developer & API Keys", subtitle: "API keys, per-key usage, webhooks and resale gateway keys", keywords: ["api", "keys", "usage", "quota", "webhooks", "developer", "gateway"], group: "Workspace", groupOrder: 5, order: 6 },
  { route: "/gateway", title: "API Gateway", subtitle: "For developers: resell generation under your own keys with a daily cap and markup", group: "Workspace", groupOrder: 5, order: 7 },
  { route: "/account/provider-keys", title: "Provider Keys (BYOK)", subtitle: "Store your own provider API keys for bring-your-own-key renders", group: "Workspace", groupOrder: 5, order: 8 },
  { route: "/workspaces/retention", title: "Data Retention", subtitle: "Set how long jobs, renders and media are kept before auto-deletion", group: "Workspace", groupOrder: 5, order: 9 },

  // Settings
  { route: "/notifications", title: "Notifications", subtitle: "View and manage your in-app notifications", group: "Settings", groupOrder: 6, order: 1 },
  { route: "/privacy", title: "Privacy & Data", subtitle: "Export your data, manage consent, or delete your account", group: "Settings", groupOrder: 6, order: 2 },
  { route: "/legal/creator-contract", title: "Creator Contract", subtitle: "Credits never expire, failed renders refunded, no training on your content", group: "Settings", groupOrder: 6, order: 2.5, keywords: ["refund", "expire", "credits", "training", "promise", "terms"] },
  { route: "/support", title: "Support", subtitle: "Get help with a job, export, purchase, or account", group: "Settings", groupOrder: 6, order: 3 },
  { route: "/account/launch-status", title: "Launch Status", subtitle: "See which features are open in the current launch phase", group: "Settings", groupOrder: 6, order: 6, keywords: ["gate", "gated", "waitlist", "checkout", "publishing", "pilot", "public launch"] },
  { route: "/account-access", title: "Account Access", subtitle: "Restore this device account or switch to an existing API key", group: "Settings", groupOrder: 6, order: 4 },
  // Hidden when this build has no Apple/Google sign-in configured (same public
  // env pair the Supabase client reads), so no dead entry reaches end users.
  { route: "/social-sign-in", title: "Sign in / Sync Account", subtitle: "Link an Apple or Google identity to sync across devices", group: "Settings", groupOrder: 6, order: 5, hidden: !SOCIAL_SIGN_IN_CONFIGURED },

  // Admin
  { route: "/account/admin", title: "Admin Console", subtitle: "Users, workspaces, revenue, jobs, retention and erasure requests", group: "Admin", groupOrder: 7, order: 1, audience: "staff" },
  { route: "/model-governance", title: "Model Governance", subtitle: "Each model's license class and lifecycle", group: "Admin", groupOrder: 7, order: 2, audience: "staff" },
  { route: "/effects-lab", title: "Effects Kernels", subtitle: "Scrub the camera and VFX animation kernels and preview the transform", group: "Admin", groupOrder: 7, order: 3, audience: "staff" },

  // Labs
  { route: "/hook-lab", title: "Hook Score Calculator", subtitle: "Enter first-3s signals by hand and see if a hook clears the 70% gate", group: "Labs", groupOrder: 99, order: 2 },
  { route: "/retention-lab", title: "Retention Calculator", subtitle: "Paste a viewer curve and read its reach tier and drop-off", group: "Labs", groupOrder: 99, order: 3 },
  { route: "/ab-lab", title: "A/B Winner Calculator", subtitle: "Enter the stats of two cuts and see which wins on retention-weighted score", group: "Labs", groupOrder: 99, order: 4 },
  { route: "/diffusion-lab", title: "Diffusion Planner", subtitle: "Model how a reel could spread through a follower network", group: "Labs", groupOrder: 99, order: 6 },
  { route: "/trend-lab", title: "Trend Calculator", subtitle: "Score a sound's opportunity, velocity and saturation from numbers you enter", group: "Labs", groupOrder: 99, order: 5 },
  { route: "/waitlist", title: "Waitlist", subtitle: "Join the early-access waitlist", group: "Labs", groupOrder: 99, order: 99, hidden: true },
];

// Seed the registry with existing screens
for (const screen of EXISTING_SCREENS) {
  registerScreen(screen);
}
