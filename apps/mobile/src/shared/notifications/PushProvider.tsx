/**
 * Wires Expo push notifications into the navigation tree. It does three things,
 * all side-effects (it renders its children untouched):
 *
 *   1. Configures the foreground presentation once so a push that arrives while
 *      the app is open still shows a banner (by default Expo suppresses these).
 *   2. Registers this install's push token after sign-in (see
 *      {@link usePushRegistration}).
 *   3. Routes a notification TAP to the finished reel: it reads `job_id` from
 *      the push payload — the same `data.job_id` shape the in-app notification
 *      list uses (see components/notifications/notification-meta) — and deep
 *      links to `/job/{id}`, matching the in-app tap behaviour. Both a warm tap
 *      (app already running) and a cold start (app launched by tapping the push)
 *      are handled.
 *
 * Must live under <SessionContext.Provider> because token registration reads the
 * session key. It uses the expo-router `router` singleton (not the `useRouter`
 * hook) so it can navigate from a listener callback without depending on render
 * order within the layout.
 */

import { useEffect, type PropsWithChildren } from "react";

import * as Notifications from "expo-notifications";
import { router } from "expo-router";

import { jobIdFromData } from "@/components/notifications/notification-meta";
import { usePushRegistration } from "./usePushRegistration";

// Foreground behaviour is process-global, so set it once at module load. On
// Expo SDK 54's expo-notifications the banner/list flags replace the older
// `shouldShowAlert`; badge management stays with the in-app unread count.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/** Navigate to the reel a notification points at, when it carries a job id. */
function routeToJob(response: Notifications.NotificationResponse | null): void {
  const data = response?.notification.request.content.data;
  const jobId = jobIdFromData(data);
  if (jobId) router.push(`/job/${jobId}`);
}

export function PushProvider({ children }: PropsWithChildren) {
  usePushRegistration();

  useEffect(() => {
    let active = true;

    // Cold start: the app was launched by tapping a push while terminated.
    Notifications.getLastNotificationResponseAsync()
      .then((response) => {
        if (active) routeToJob(response);
      })
      .catch(() => {
        // No last response / unsupported platform: nothing to route.
      });

    // Warm tap: the app was already running (foreground or background).
    const subscription = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        routeToJob(response);
      },
    );

    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  return <>{children}</>;
}
