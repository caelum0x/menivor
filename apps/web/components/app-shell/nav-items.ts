import {
  BarChart3,
  Bot,
  CalendarClock,
  CalendarDays,
  Clapperboard,
  Code2,
  Coins,
  Cpu,
  CreditCard,
  Crown,
  Film,
  FolderOpen,
  FolderUp,
  Gauge,
  Gift,
  Hourglass,
  Images,
  Inbox,
  KeyRound,
  LayoutGrid,
  Lightbulb,
  LineChart,
  Link2,
  Lock,
  Mic,
  MonitorPlay,
  Palette,
  Plus,
  Radio,
  Rocket,
  ScrollText,
  ShoppingBag,
  Medal,
  Send,
  Bell,
  ShieldCheck,
  SlidersHorizontal,
  Stamp,
  Store,
  Trophy,
  UserRound,
  Users,
  Wallet,
  Compass,
  House,
  Settings,
  Library,
  Boxes,
  Building2,
  FlaskConical,
  GitCompare,
  PenTool,
  ScanLine,
  ClipboardCheck,
  Activity,
  Languages,
  PlugZap,
  Search,
  SquareStack,
  Telescope,
  UserRoundCheck,
  Workflow,
} from "lucide-react";
import type { ComponentType } from "react";
import { withoutHiddenSso } from "@/lib/sso-availability";

export interface AppNavItem {
  readonly href: string;
  readonly label: string;
  readonly icon: ComponentType<{ className?: string }>;
  /**
   * Shown in the default (simple) menu. Everything else is an advanced tool:
   * hidden from new users until they turn on "Show all tools" (staff see all).
   */
  readonly core?: boolean;
}

export interface AppNavGroup {
  readonly label: string;
  readonly items: readonly AppNavItem[];
}

export interface PrimaryNavItem {
  readonly href: string;
  /** Tooltip + accessible name; the control itself is icon-only. */
  readonly label: string;
  readonly icon: ComponentType<{ className?: string }>;
  /** Path prefixes that light this destination up. */
  readonly match: readonly string[];
}

/**
 * The five public destinations (WP3.2): Home, Create, Autopilot, Results,
 * Settings. Non-staff users see exactly these; verified staff also get "More",
 * which opens {@link APP_NAV_GROUPS}. Home is the reel library. Autopilot is
 * the scheduled-posting queue until the WP6.1 series page ships.
 */
export const PRIMARY_NAV_ITEMS: readonly PrimaryNavItem[] = [
  { href: "/reels", label: "Home", icon: House, match: ["/reels", "/dashboard"] },
  { href: "/create", label: "Create", icon: Plus, match: ["/create", "/new", "/editor", "/ad-studio", "/very-time", "/agent", "/month"] },
  {
    href: "/scheduled",
    label: "Autopilot",
    icon: CalendarClock,
    match: ["/scheduled", "/autopilot", "/connections", "/publish"],
  },
  {
    href: "/performance",
    label: "Results",
    icon: BarChart3,
    match: ["/performance", "/insights/winners"],
  },
  {
    href: "/account",
    label: "Settings",
    icon: Settings,
    match: [
      "/account",
      "/settings",
      "/wallet",
      "/billing",
      "/spend",
      "/usage",
      "/workspace",
      "/notifications",
      "/referral",
      "/presets",
      "/brand",
      "/voices",
    ],
  },
];

/**
 * Staff-only tools (WP3.2). Their pages stay in the tree and keep working for
 * staff; a signed-in non-staff user who opens one is sent to Home instead of a
 * 404. Everything linked from the five destinations stays public (for example
 * `/create/advanced`, `/new`, `/editor`, `/wallet`, `/spend`, `/workspace`).
 * `NEXT_PUBLIC_MENIVOR_STAFF_TOOLS=open` turns the gate off.
 */
export const STAFF_TOOL_ROUTES: readonly string[] = [
  "/ideas",
  "/import",
  "/studio",
  "/capture",
  "/broll",
  "/broll-library",
  "/film",
  "/render",
  "/ad-studio/catalog",
  "/channels",
  "/calendar",
  "/reels/calendar",
  "/approvals",
  "/inbox",
  "/insights",
  "/analytics",
  "/ads/report",
  "/marketplace",
  "/leaderboard",
  "/settings/team",
  "/settings/sso",
  "/settings/audit",
  "/developer",
  "/discover",
  "/catalog",
  "/media",
  "/models",
  "/agency",
  "/hook-lab",
  "/ab-lab",
  "/retention-lab",
  "/trend-lab",
  "/effects-lab",
  "/workflows-lab",
];

/** Public pages that sit under a staff-only prefix. */
const STAFF_TOOL_EXCEPTIONS: readonly string[] = ["/insights/winners"];

function underPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

/** Whether `pathname` is a staff-only tool page. */
export function isStaffToolRoute(pathname: string): boolean {
  if (STAFF_TOOL_EXCEPTIONS.some((p) => underPrefix(pathname, p))) return false;
  return STAFF_TOOL_ROUTES.some((p) => underPrefix(pathname, p));
}

/** Whether the staff-tools gate is on (default on; `open` turns it off). */
export function staffToolsGated(
  value: string | undefined = process.env.NEXT_PUBLIC_MENIVOR_STAFF_TOOLS,
): boolean {
  return (value ?? "").trim().toLowerCase() !== "open";
}

/** Whether `pathname` belongs to a primary destination (exact or nested). */
export function isPrimaryActive(pathname: string, item: PrimaryNavItem): boolean {
  return item.match.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/**
 * The single app-wide navigation map. Every signed-in / guest surface reaches
 * every other through this grouped menu instead of per-page header rows.
 */
export const APP_NAV_GROUPS: readonly AppNavGroup[] = [
  {
    label: "Library",
    items: [
      { href: "/reels", label: "My reels", icon: Clapperboard , core: true },
      { href: "/reels/calendar", label: "Reel calendar", icon: CalendarDays },
      { href: "/projects", label: "Projects", icon: FolderOpen },
      { href: "/uploads", label: "Uploads", icon: FolderUp },
    ],
  },
  {
    label: "Create",
    items: [
      { href: "/create", label: "New reels (topic or link)", icon: Plus , core: true },
      { href: "/agent", label: "Brand agent", icon: Bot, core: true },
      { href: "/review", label: "Review queue", icon: SquareStack },
      { href: "/actors", label: "AI actors", icon: UserRoundCheck },
      { href: "/translate", label: "Video translate", icon: Languages },
      { href: "/workflows", label: "Workflows", icon: Workflow },
      { href: "/new", label: "Product demo wizard", icon: MonitorPlay },
      { href: "/ad-studio", label: "Product ad studio", icon: ShoppingBag , core: true },
      { href: "/ad-studio/catalog", label: "Store catalog import", icon: ShoppingBag },
      { href: "/create/advanced", label: "Own narration / AI clip", icon: Mic },
      { href: "/very-time", label: "Very ___ Time", icon: Hourglass },
      { href: "/import", label: "Import from URL", icon: Link2 },
      { href: "/ideas", label: "Spark ideas", icon: Lightbulb },
      { href: "/studio", label: "Studio", icon: LayoutGrid },
      { href: "/studio/design", label: "Design Studio", icon: PenTool },
      { href: "/capture", label: "Capture", icon: ScanLine },
      { href: "/broll", label: "B-roll studio", icon: Film },
      { href: "/film", label: "Film studio", icon: Film },
      { href: "/render", label: "AI video render", icon: Cpu },
    ],
  },
  {
    label: "Publish & grow",
    items: [
      { href: "/connections", label: "Publish", icon: Send , core: true },
      { href: "/channels", label: "Channels", icon: Radio },
      { href: "/scheduled", label: "Scheduled", icon: CalendarClock , core: true },
      { href: "/calendar", label: "Calendar", icon: CalendarDays },
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
      { href: "/inbox", label: "Social inbox", icon: Inbox },
      { href: "/insights", label: "Insights", icon: BarChart3 },
      { href: "/insights/winners", label: "Winner loop", icon: Medal , core: true },
      { href: "/analytics", label: "Analytics", icon: LineChart },
      { href: "/performance", label: "Performance", icon: Trophy , core: true },
      { href: "/ads/report", label: "Ad network report", icon: BarChart3 },
      { href: "/keywords", label: "Keyword tracker", icon: Search },
      { href: "/launch-kit", label: "Launch kit", icon: Rocket },
      { href: "/competitors", label: "Competitor ads", icon: Telescope },
      { href: "/ad-fatigue", label: "Ad fatigue", icon: Activity },
    ],
  },
  {
    label: "Community",
    items: [
      { href: "/showcase", label: "Showcase", icon: Images },
      { href: "/marketplace", label: "Marketplace", icon: Store },
      { href: "/leaderboard", label: "Leaderboard", icon: Crown },
      { href: "/referral", label: "Referrals", icon: Gift , core: true },
    ],
  },
  {
    label: "Brand",
    items: [
      { href: "/presets", label: "Brand kits", icon: Palette , core: true },
      { href: "/brand", label: "Watermark", icon: Stamp },
      { href: "/voices", label: "Brand voice", icon: Mic },
    ],
  },
  {
    label: "Account & billing",
    items: [
      { href: "/account", label: "Account", icon: UserRound , core: true },
      { href: "/wallet", label: "Wallet", icon: Wallet , core: true },
      { href: "/wallet/plans", label: "Buy credits", icon: Coins , core: true },
      { href: "/billing", label: "Workspace plan", icon: CreditCard },
      { href: "/spend", label: "Spend controls", icon: SlidersHorizontal },
      { href: "/usage", label: "API usage", icon: Gauge },
      { href: "/notifications", label: "Notifications", icon: Bell },
    ],
  },
  {
    label: "Team & settings",
    // MN7a: the SSO entry is left out until real SSO ships (lib/sso-availability).
    items: withoutHiddenSso([
      { href: "/workspace", label: "Team workspaces", icon: Users },
      { href: "/settings/team", label: "Roles & permissions", icon: ShieldCheck },
      { href: "/settings/sso", label: "SSO & SCIM", icon: Lock },
      { href: "/settings/audit", label: "Audit log", icon: ScrollText },
      { href: "/settings/privacy", label: "Privacy & data", icon: ShieldCheck },
      { href: "/account/api-keys", label: "API keys", icon: KeyRound },
      { href: "/developer", label: "Developer", icon: Code2 },
      { href: "/settings/mcp", label: "MCP connector", icon: PlugZap },
    ]),
  },
  {
    // Secondary surfaces and interactive labs. None are core, so the whole
    // group only appears once "Show all tools" is on (staff always see it).
    label: "More tools",
    items: [
      { href: "/discover", label: "Discover trends", icon: Compass },
      { href: "/catalog", label: "Asset catalog", icon: Library },
      { href: "/media", label: "Media gateway", icon: Boxes },
      { href: "/models/compare", label: "Compare models", icon: GitCompare },
      { href: "/agency", label: "Agency", icon: Building2 },
      { href: "/hook-lab", label: "Hook score lab", icon: FlaskConical },
      { href: "/ab-lab", label: "A/B winner lab", icon: FlaskConical },
      { href: "/retention-lab", label: "Retention lab", icon: FlaskConical },
      { href: "/trend-lab", label: "Trend lab", icon: FlaskConical },
      { href: "/effects-lab", label: "Effects lab", icon: FlaskConical },
      { href: "/workflows-lab", label: "Workflows lab", icon: FlaskConical },
    ],
  },
];

/** Where "Show all tools" is remembered for this browser. */
export const NAV_ADVANCED_STORAGE_KEY = "menivor.nav.advanced";

/**
 * The menu for the chosen mode: every group in advanced mode, otherwise only
 * core items, dropping groups left empty. Pure, so it is unit-testable.
 */
export function visibleNavGroups(
  groups: readonly AppNavGroup[],
  advanced: boolean,
): readonly AppNavGroup[] {
  if (advanced) return groups;
  return groups
    .map((group) => ({ ...group, items: group.items.filter((item) => item.core) }))
    .filter((group) => group.items.length > 0);
}

/** Count of tools hidden in simple mode (for the toggle label). */
export function hiddenNavCount(groups: readonly AppNavGroup[]): number {
  return groups.reduce(
    (total, group) => total + group.items.filter((item) => !item.core).length,
    0,
  );
}
