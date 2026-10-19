/**
 * Maps live hub signals onto specific nav rows so advanced surfaces advertise
 * what is waiting behind them (e.g. Notifications shows the unread count, the
 * Task Queue shows how many jobs are running). Pure: given the data, returns
 * the badge to render for a route, or null.
 */

import type { BadgeVariant } from "@/components/ui/Badge";
import type { NavHubData } from "./useNavHubData";

export interface RowBadge {
  label: string;
  variant: BadgeVariant;
}

export function badgeForRoute(
  route: string,
  data: NavHubData,
): RowBadge | null {
  switch (route) {
    case "/notifications":
      return data.unread && data.unread > 0
        ? { label: `${data.unread} new`, variant: "accent" }
        : null;
    case "/jobs/reels/tasks":
      return data.activeJobs && data.activeJobs > 0
        ? { label: `${data.activeJobs} running`, variant: "success" }
        : null;
    case "/wallet":
      return typeof data.credits === "number"
        ? { label: `${data.credits} cr`, variant: "neutral" }
        : null;
    default:
      return null;
  }
}
