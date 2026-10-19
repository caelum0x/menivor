/**
 * Insights domain — analytics, notifications, performance.
 * (GET /me/analytics, /me/insights, /me/notifications/*, /jobs/{id}/performance)
 */

export {
  getAnalytics,
  getInsights,
  getJobPerformance,
  getLeaderboard,
  getUnreadCount,
  getWinningHooks,
  getWinningTemplates,
  listMyPerformance,
  listNotifications,
  logJobPerformance,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
