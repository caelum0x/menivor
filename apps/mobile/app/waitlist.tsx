import { Pressable, StyleSheet, Text, View } from "react-native";

import { Stack, useRouter } from "expo-router";

import { WaitlistHome } from "@/src/shared/product";
import { useSession } from "@/src/shared/auth";
import { colors, spacing, typeScale } from "@/src/shared/theme";

/**
 * Standalone waitlist-era home, reachable without an API key. Sign-in routes
 * here only when the backend reports public signup closed for this launch
 * phase. The header always offers a way back to sign-in (retry, access key,
 * Apple/Google) and to the drafts saved on this device, so it is never a
 * dead end.
 */
export default function WaitlistScreen() {
  const { apiKey } = useSession();
  const router = useRouter();

  const backToSignIn = () => {
    if (router.canGoBack()) router.back();
    else router.replace("/");
  };

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          title: "Menivor",
          headerBackVisible: false,
          headerLeft: () =>
            apiKey ? null : (
              <Pressable
                onPress={backToSignIn}
                accessibilityRole="button"
                accessibilityLabel="Back to sign in"
                hitSlop={8}
              >
                <Text style={styles.headerLink}>Sign in</Text>
              </Pressable>
            ),
          headerRight: () => (
            <View style={styles.headerRight}>
              <Pressable
                onPress={() => router.push("/drafts")}
                accessibilityRole="button"
                accessibilityLabel="View drafts saved on this device"
                hitSlop={8}
              >
                <Text style={styles.headerLink}>Drafts</Text>
              </Pressable>
            </View>
          ),
        }}
      />
      <WaitlistHome token={apiKey ?? undefined} source="mobile-signin" />
    </>
  );
}

const styles = StyleSheet.create({
  headerRight: { flexDirection: "row", gap: spacing.lg },
  headerLink: {
    color: colors.accent,
    fontSize: typeScale.body,
    fontWeight: "700",
  },
});
