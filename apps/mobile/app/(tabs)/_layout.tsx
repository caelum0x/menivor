import { Redirect, Tabs } from "expo-router";

import { useSession } from "@/src/shared/auth";
import { colors } from "@/src/shared/theme";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { Icon, type IconName } from "@/components/ui/Icon";
import { ReelTabBar } from "@/src/ui/menivor";
import { AiProcessingConsent } from "@/src/shared/legal/AiProcessingConsent";
import { useGenerationCapabilities } from "@/src/shared/hooks";
import { isBrollAvailable } from "@/src/features/broll-studio/availability";

/** Tab bar icon: filled when focused, outline otherwise. */
function tabIcon(filled: IconName, outline: IconName) {
  function TabIcon({
    color,
    size,
    focused,
  }: {
    color: string;
    size: number;
    focused: boolean;
  }) {
    return <Icon name={focused ? filled : outline} size={size} color={color} />;
  }
  return TabIcon;
}

/**
 * Authenticated tab navigator: four icon-only destinations (Create, Reels,
 * B-roll, Me) on Menivor's film-strip rail. No visible labels; each tab keeps
 * an accessibility label. Redirects to sign-in when no API key is present.
 * The B-roll tab only appears when the server has AI B-roll switched on for
 * this account, so no tab can only say "unavailable".
 */
export default function TabsLayout() {
  const { apiKey, loading } = useSession();
  const capabilityState = useGenerationCapabilities(apiKey ?? undefined);
  const brollVisible = isBrollAvailable(capabilityState.capabilities);

  if (!loading && !apiKey) {
    return <Redirect href="/" />;
  }

  return (
    <>
    <AiProcessingConsent token={apiKey ?? undefined} />
    <Tabs
        tabBar={(props) => <ReelTabBar {...props} />}
        screenOptions={{
          sceneStyle: { backgroundColor: colors.bg },
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.textPrimary,
          headerTitleStyle: { color: colors.textPrimary },
        }}
      >
        <Tabs.Screen
          name="create"
          options={{
            title: "Create",
            tabBarAccessibilityLabel: "Create",
            tabBarIcon: tabIcon("add-circle", "add-circle-outline"),
            headerRight: () => <NotificationBell compact />,
          }}
        />
        <Tabs.Screen
          name="jobs"
          options={{
            title: "Reels",
            tabBarAccessibilityLabel: "Reels",
            tabBarIcon: tabIcon("film", "film-outline"),
            headerRight: () => <NotificationBell compact />,
          }}
        />
        <Tabs.Screen
          name="broll"
          options={{
            title: "B-roll",
            href: brollVisible ? undefined : null,
            tabBarAccessibilityLabel: "B-roll",
            tabBarIcon: tabIcon("sparkles", "sparkles-outline"),
            headerRight: () => <NotificationBell compact />,
          }}
        />
        <Tabs.Screen
          name="me"
          options={{
            title: "Me",
            tabBarAccessibilityLabel: "Me",
            tabBarIcon: tabIcon("person-circle", "person-circle-outline"),
            headerRight: () => <NotificationBell compact />,
          }}
        />
      </Tabs>
    </>
  );
}
