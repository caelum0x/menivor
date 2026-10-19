/**
 * Registers this install for Expo push notifications once the user is signed in,
 * so a finished render can reach them even when the app is backgrounded (the
 * in-app notification center only advances while focused — see JobsScreen /
 * JobDetailScreen polling). This is a best-effort background nicety: every step
 * is guarded and NEVER surfaces an error to the UI. Denied permission, a
 * simulator with no push support, or an unconfigured backend all degrade to a
 * silent no-op rather than blocking the signed-in experience.
 *
 * Flow (only when `apiKey` is present):
 *   1. Ensure notification permission (ask once if undetermined).
 *   2. On Android, ensure a default channel exists so banners actually show.
 *   3. Mint the Expo push token with the build's EAS projectId.
 *   4. POST it via {@link registerPushToken}, keyed by the same stable
 *      SecureStore installId used for the device session, so re-registering
 *      refreshes rather than duplicates.
 *
 * The token is registered at most once per app session (and again if it rotates)
 * via a ref guard, so focus/remount churn does not spam the backend.
 *
 * No secrets here: auth flows through the session key as `x-api-key`.
 */

import { useEffect, useRef } from "react";
import { Platform } from "react-native";

import Constants from "expo-constants";
import * as Notifications from "expo-notifications";

import { getOrCreateInstallId, useSession } from "@/src/shared/auth";
import { registerPushToken } from "@/lib/api";

/** The EAS projectId Expo's push service needs to mint a token for this build. */
function easProjectId(): string | null {
  const fromExtra = Constants.expoConfig?.extra?.eas?.projectId;
  if (typeof fromExtra === "string" && fromExtra.length > 0) return fromExtra;
  // easConfig is the legacy location on some SDKs; read it defensively.
  const fromEas = (Constants as { easConfig?: { projectId?: unknown } }).easConfig
    ?.projectId;
  return typeof fromEas === "string" && fromEas.length > 0 ? fromEas : null;
}

/** Ensure notification permission, asking once when still undetermined. */
async function ensurePermission(): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) return true;
  // Only prompt when the user has not answered yet; respect a prior denial.
  if (current.canAskAgain === false) return false;
  const requested = await Notifications.requestPermissionsAsync();
  return requested.granted;
}

/** On Android a channel is required for heads-up banners; create it once. */
async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync("default", {
    name: "Render updates",
    importance: Notifications.AndroidImportance.DEFAULT,
  });
}

export function usePushRegistration(): void {
  const { apiKey } = useSession();
  // The last Expo token we successfully registered this session; guards against
  // re-POSTing on every focus/remount while still catching a rotated token.
  const registeredToken = useRef<string | null>(null);

  useEffect(() => {
    if (!apiKey) {
      // Signed out: forget the last token so a future sign-in re-registers.
      registeredToken.current = null;
      return;
    }

    const projectId = easProjectId();
    if (!projectId) return; // Owner step: set the EAS projectId (app.json extra.eas).

    let active = true;

    const run = async (): Promise<void> => {
      try {
        const granted = await ensurePermission();
        if (!active || !granted) return;

        await ensureAndroidChannel();

        const { data: expoToken } = await Notifications.getExpoPushTokenAsync({
          projectId,
        });
        // Keyed by token AND session: switching accounts without an explicit
        // sign-out (e.g. /account-access recovery) must re-own the install row
        // for the new account, or pushes keep going to the previous one.
        const registrationKey = `${apiKey}::${expoToken}`;
        if (!active || !expoToken || registeredToken.current === registrationKey) {
          return;
        }

        const installId = await getOrCreateInstallId();
        const platform = Platform.OS === "ios" ? "ios" : "android";
        await registerPushToken(expoToken, platform, installId, {
          token: apiKey,
        });
        if (active) registeredToken.current = registrationKey;
      } catch {
        // Best-effort only: denied permission, a simulator without push, or an
        // unconfigured backend must never disrupt the signed-in experience.
      }
    };

    void run();

    return () => {
      active = false;
    };
  }, [apiKey]);
}
