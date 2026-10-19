/**
 * Sign-out with a confirmation step. Store builds show a plain prompt; lab
 * sessions warn about unlinked device test accounts (see ./sign-out-copy).
 */

import { useCallback } from "react";
import { Alert } from "react-native";

import { useRouter } from "expo-router";

import { useSession } from "./session";
import { useSupabaseAuth } from "./supabase-auth";
import { isLabEnabled } from "@/src/shared/release/build-flags";
import { isRouteAvailable } from "@/src/shared/release/surface";

import { signOutPrompt } from "./sign-out-copy";

export function useConfirmSignOut(): () => void {
  const router = useRouter();
  const { signOut } = useSession();
  const { configured, user } = useSupabaseAuth();
  const linked = user !== null;

  const doSignOut = useCallback(async () => {
    await signOut();
    router.replace("/");
  }, [router, signOut]);

  return useCallback(() => {
    const prompt = signOutPrompt({ linked, lab: isLabEnabled() });
    if (!prompt.offerLink) {
      Alert.alert(prompt.title, prompt.message, [
        { text: "Cancel", style: "cancel" },
        { text: "Sign out", style: "destructive", onPress: () => void doSignOut() },
      ]);
      return;
    }
    Alert.alert(prompt.title, prompt.message, [
      { text: "Cancel", style: "cancel" },
      ...(configured && isRouteAvailable("/social-sign-in")
        ? [{ text: "Link sign-in first", onPress: () => router.push("/social-sign-in") }]
        : []),
      { text: "Sign out anyway", style: "destructive" as const, onPress: () => void doSignOut() },
    ]);
  }, [configured, doSignOut, linked, router]);
}
